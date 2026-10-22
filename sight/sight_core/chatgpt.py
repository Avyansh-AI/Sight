"""Optional official ChatGPT plan connection. No API key or borrowed app session."""
import asyncio
import base64
import hashlib
import json
import math
import re
import secrets
import time
import uuid
import webbrowser
from urllib.parse import urlencode,urlsplit

import httpx
import jwt
from pydantic import Field
from .tools import StrictModel
from .security import Vault
from .quotas import QuotaLedger,rate_observation

AUTH='https://auth.openai.com'
RESOURCE='https://api.openai.com/v1'
SCOPE='openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'


class ChatGPTPolicy(StrictModel):
    enabled: bool = False
    allow_remote_text: bool = False
    plan_only_confirmed: bool = False
    model: str = Field(default='',max_length=120,pattern=r'^[A-Za-z0-9_.-]*$')
    daily_request_limit: int = Field(default=3,ge=1,le=10)
    requests_per_minute: int = Field(default=1,ge=1,le=3)
    daily_token_limit: int = Field(default=10000,ge=512,le=20000)
    minute_token_limit: int = Field(default=3000,ge=512,le=5000)
    daily_budget_usd: float = Field(default=0.0,ge=0,le=0)
    max_output_tokens: int = Field(default=256,ge=16,le=512)


class Connect(StrictModel):
    account: str = Field(default='',pattern=r'^(|[a-f0-9]{24})$')


class OAuthVault:
    """Chunk to fit Windows Credential Manager; atomically replace the index last."""
    def __init__(self,path):
        self.service='SIGHT.ChatGPT.'+hashlib.sha256(str(path).encode()).hexdigest()[:24]

    def get(self):
        if not Vault().status()['available']:return {'accounts':{},'active':None}
        import keyring
        head=keyring.get_password(self.service,'index')
        if not head:return {'accounts':{},'active':None}
        index=json.loads(head)
        if not 1<=index['count']<=100:raise ValueError('Invalid OAuth vault index')
        raw=''.join(keyring.get_password(self.service,index['id']+'/'+str(i)) or '' for i in range(index['count']))
        if hashlib.sha256(raw.encode()).hexdigest()!=index['sha256']:raise ValueError('OAuth vault integrity failed')
        return json.loads(raw)

    def set(self,value):
        if not Vault().status()['available']:raise ValueError('OS vault unavailable')
        import keyring
        raw=json.dumps(value,ensure_ascii=True);parts=[raw[i:i+900] for i in range(0,len(raw),900)]
        if len(parts)>100:raise ValueError('OAuth vault exceeds account limit')
        previous=keyring.get_password(self.service,'index');identifier=uuid.uuid4().hex
        for i,part in enumerate(parts):keyring.set_password(self.service,identifier+'/'+str(i),part)
        keyring.set_password(self.service,'index',json.dumps({'id':identifier,'count':len(parts),'sha256':hashlib.sha256(raw.encode()).hexdigest()}))
        if previous:
            old=json.loads(previous)
            for i in range(min(old['count'],100)):
                try:keyring.delete_password(self.service,old['id']+'/'+str(i))
                except keyring.errors.KeyringError:pass


class ChatGPT:
    def __init__(self,store,config,vault=None,transport=None,opener=webbrowser.open):
        self.store,self.config=store,config
        self.vault=vault or OAuthVault(config.data_dir)
        self.transport,self.opener=transport,opener
        self.pending=None;self.lock=asyncio.Lock();self.quota=QuotaLedger(store,'chatgpt')
        self.last_error=None

    @property
    def policy(self):return ChatGPTPolicy.model_validate(self.store.setting('chatgpt.policy',{}))

    def status(self):
        try:
            data=self.vault.get();active=data['accounts'].get(data['active'],{})
            accounts=[{'id':key,'email':row.get('email'),'label':row.get('email','ChatGPT')+' · '+row['client_id'][-8:],
                       'connected':bool(row.get('access_token'))} for key,row in data['accounts'].items()]
            return {'id':'chatgpt','status':'ready' if active.get('access_token') and self.policy.enabled and self.policy.plan_only_confirmed else 'connected_disabled' if active.get('access_token') else 'not_connected',
                    'active_account':data['active'],'accounts':accounts,'policy':self.policy.model_dump(),'last_error':self.last_error,
                    'quota':self.quota.status(self.policy),'usage_url':'https://chatgpt.com/settings/usage','live_qualified':False}
        except (ValueError,KeyError,TypeError):return {'id':'chatgpt','status':'vault_error','accounts':[]}

    async def request(self,method,url,**kwargs):
        async with asyncio.timeout(25), httpx.AsyncClient(transport=self.transport,trust_env=False,follow_redirects=False,timeout=20) as client:
            async with client.stream(method,url,**kwargs) as response:
                data=bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>1_000_000:raise ValueError('Oversized OAuth response')
                if response.status_code!=200:raise ValueError('Official service returned HTTP '+str(response.status_code))
                return json.loads(data) if data else {}

    def begin(self,session,account=''):
        data=self.vault.get();saved=data['accounts'].get(account)
        if account and not saved:raise ValueError('Unknown account')
        if not account and len(data['accounts'])>=5:raise ValueError('Five accounts already registered')
        host=self.store.setting('chatgpt.host')
        if not host:host='urn:uuid:'+str(uuid.uuid4());self.store.set_setting('chatgpt.host',host)
        self.pending={'state':secrets.token_urlsafe(32),'nonce':secrets.token_urlsafe(32),'verifier':secrets.token_urlsafe(64),
                      'redirect_uri':f'http://127.0.0.1:{self.config.port}/auth/callback','session':session,'expires':time.time()+600,
                      'client_id':saved['client_id'] if saved else 'dynamic_agent_client','subject':saved['subject'] if saved else None}
        p=self.pending
        params={'client_id':p['client_id'],'response_type':'code','redirect_uri':p['redirect_uri'],'scope':SCOPE,'resource':RESOURCE,
                'state':p['state'],'nonce':p['nonce'],'code_challenge_method':'S256',
                'code_challenge':base64.urlsafe_b64encode(hashlib.sha256(p['verifier'].encode()).digest()).rstrip(b'=').decode(),
                'ext_agent_host_id':host}
        if saved:
            if saved.get('id_token'):params['id_token_hint']=saved['id_token']
        else:params['agent_name_hint']='SIGHT'
        if not self.opener(AUTH+'/api/accounts/authorize?'+urlencode(params)):raise ValueError('Could not open the system browser')
        return {'started':True,'expires_in':600,'message':'Finish sign-in in the system browser, then return to Systems.'}

    async def identity(self,token,client_id,nonce=None,subject=None):
        header=jwt.get_unverified_header(token)
        if header.get('alg')!='RS256':raise ValueError('Unsupported ID token signature algorithm')
        keys=await self.request('GET',AUTH+'/.well-known/jwks.json')
        matching=[k for k in keys.get('keys',[]) if k.get('kid')==header.get('kid') and k.get('kty')=='RSA']
        if len(matching)!=1:raise ValueError('Unknown ID token signing key')
        claims=jwt.decode(token,jwt.PyJWK.from_dict(matching[0]).key,algorithms=['RS256'],audience=client_id,issuer=AUTH,
                          leeway=15,options={'require':['exp','iat','sub','aud','iss']})
        if nonce is not None and not secrets.compare_digest(str(claims.get('nonce','')),nonce):raise ValueError('ID token nonce mismatch')
        if subject is not None and claims['sub']!=subject:raise ValueError('Account identity changed')
        if len(claims['sub'])>256:raise ValueError('Invalid identity')
        return claims

    @staticmethod
    def token_record(tokens,previous=None):
        previous=previous or {}
        scopes=tokens.get('scope',' '.join(previous.get('scopes',[]))).split()
        if 'chatgpt.tokens.use.direct' not in scopes:raise ValueError('ChatGPT plan permission was not granted')
        expires=tokens.get('expires_in')
        if not isinstance(expires,(int,float)) or not math.isfinite(expires) or not 0<expires<=86400:raise ValueError('Invalid token expiry')
        if tokens.get('token_type','').lower()!='bearer' or not isinstance(tokens.get('access_token'),str) or not tokens['access_token']:raise ValueError('Invalid access token')
        return previous|{k:tokens.get(k,previous.get(k)) for k in ('access_token','refresh_token','id_token')}|{'scopes':scopes,'expires_at':time.time()+expires}

    async def callback(self,params,session_valid):
        p=self.pending
        if not p or time.time()>p['expires'] or not session_valid(p['session']) or not secrets.compare_digest(params.get('state',''),p['state']):raise ValueError('Invalid or expired OAuth state')
        self.pending=None  # One use, including denied and failed exchanges.
        if params.get('error'):raise ValueError('ChatGPT authorization was declined')
        client_id=params.get('client_id',p['client_id'])
        if not re.fullmatch(r'oaiapp_[A-Za-z0-9_-]{1,180}',client_id):raise ValueError('Issued client ID is missing')
        if p['client_id']!='dynamic_agent_client' and client_id!=p['client_id']:raise ValueError('Registration changed')
        code=params.get('code','')
        if not code or len(code)>4096:raise ValueError('Invalid authorization code')
        async with self.lock:
            tokens=await self.request('POST',AUTH+'/api/accounts/oauth/token',data={'grant_type':'authorization_code','client_id':client_id,'code':code,'code_verifier':p['verifier'],'redirect_uri':p['redirect_uri'],'resource':RESOURCE})
            identity=await self.identity(tokens['id_token'],client_id,p['nonce'],p['subject'])
            record=self.token_record(tokens)|{'client_id':client_id,'subject':identity['sub'],'email':identity.get('email','ChatGPT')}
            identifier=hashlib.sha256((client_id+'|'+identity['sub']).encode()).hexdigest()[:24]
            data=self.vault.get();data['accounts'][identifier]=record;data['active']=identifier;self.vault.set(data)
        self.last_error=None;return {'connected':True}

    async def access(self):
        data=self.vault.get();row=data['accounts'].get(data['active'])
        if not row or not row.get('access_token'):raise ValueError('ChatGPT is not connected')
        if row['expires_at']>time.time()+60:return row['access_token']
        async with self.lock:
            data=self.vault.get();row=data['accounts'][data['active']]
            if row['expires_at']<=time.time()+60:
                if not row.get('refresh_token'):raise ValueError('Sign in again')
                tokens=await self.request('POST',AUTH+'/api/accounts/oauth/token',data={'grant_type':'refresh_token','client_id':row['client_id'],'refresh_token':row['refresh_token'],'resource':RESOURCE})
                if tokens.get('id_token'):await self.identity(tokens['id_token'],row['client_id'],subject=row['subject'])
                data['accounts'][data['active']]=self.token_record(tokens,row);self.vault.set(data)
            return data['accounts'][data['active']]['access_token']

    async def models(self):
        access=await self.access()
        data=await self.request('GET',RESOURCE+'/models',headers={'Authorization':'Bearer '+access})
        return {'items':[{'slug':r['slug'],'display_name':r.get('display_name',r['slug'])} for r in data.get('models',[]) if r.get('visibility')=='list' and re.fullmatch(r'[A-Za-z0-9_.-]{1,120}',r.get('slug',''))]}

    async def disconnect(self,account=''):
        async with self.lock:
            data=self.vault.get();identifier=account or data['active'];row=data['accounts'].get(identifier)
            if not row:raise ValueError('Account not found')
            confirmed=False
            try:
                if row.get('refresh_token'):
                    discovery=await self.request('GET',AUTH+'/.well-known/openid-configuration')
                    endpoint=discovery.get('revocation_endpoint','');parsed=urlsplit(endpoint)
                    if parsed.scheme!='https' or parsed.netloc!='auth.openai.com':raise ValueError('Untrusted revocation endpoint')
                    await self.request('POST',endpoint,data={'token':row['refresh_token'],'token_type_hint':'refresh_token','client_id':row['client_id']})
                    confirmed=True
            except (httpx.HTTPError,ValueError):pass
            for k in ('access_token','refresh_token','id_token'):row.pop(k,None)
            data['accounts'][identifier]=row
            if data['active']==identifier:data['active']=None
            self.vault.set(data)
            self.pending=None
            policy=self.policy.model_dump();policy['enabled']=False;self.store.set_setting('chatgpt.policy',policy)
            return {'disconnected':True,'remote_revocation_confirmed':confirmed,'message':'Signed out.' if confirmed else 'Local tokens cleared. Remote revocation was not confirmed; disconnect SIGHT in ChatGPT Settings.'}

    async def generate(self,text):
        p=self.policy
        def failure(status,message):return {'status':status,'say':message,'provider':'chatgpt','offline':False}
        if not(p.enabled and p.allow_remote_text and p.plan_only_confirmed and p.model):return failure('API_billing_blocked','Enable a reviewed ChatGPT plan-only policy first.')
        verdict=self.quota.reserve(p,len(text.encode())+128+p.max_output_tokens,0)
        if not verdict['allowed']:return failure(verdict['status'],'ChatGPT local usage cap or cooldown reached.')
        try:
            access=await self.access()
            async with asyncio.timeout(45):
                async with httpx.AsyncClient(transport=self.transport,trust_env=False,follow_redirects=False,timeout=40) as client:
                    async with client.stream('POST',RESOURCE+'/responses',headers={'Authorization':'Bearer '+access},json={'model':p.model,'input':[{'role':'user','content':text}],'store':False,'stream':True,'max_output_tokens':p.max_output_tokens}) as response:
                        observation=rate_observation(response.headers)
                        if response.status_code!=200:
                            self.quota.observe(observation,max(60,observation.get('retry_after_seconds',0)) if response.status_code==429 else 0)
                            return failure('rate_limited' if response.status_code==429 else 'provider_error','ChatGPT rejected the request; no paid API fallback or automatic retry.')
                        text_parts=[];completed=False;size=0;usage=None
                        async for line in response.aiter_lines():
                            size+=len(line.encode())
                            if size>1_000_000:raise ValueError('Oversized stream')
                            if not line.startswith('data: '):continue
                            raw=line[6:]
                            if raw=='[DONE]':break
                            event=json.loads(raw);kind=event.get('type')
                            if kind=='response.output_text.delta':text_parts.append(event.get('delta',''))
                            if kind in ('response.failed','response.incomplete','error'):
                                self.quota.observe({'stream_failure':True},86400)
                                return failure('provider_error','ChatGPT did not complete the response. Review plan usage before retrying.')
                            if kind=='response.completed':completed=True;usage=event.get('response',{}).get('usage');break
                        answer=''.join(text_parts).strip()
                        if not completed or not answer:return failure('provider_error','ChatGPT stream ended without a completed answer.')
                        return {'status':'ok','say':answer[:32000],'offline':False,'provider':'chatgpt','model':p.model,'usage':usage}
        except (httpx.HTTPError,TimeoutError,ValueError,KeyError,TypeError,jwt.PyJWTError):
            return failure('provider_error','ChatGPT connection or validation failed. Sign in again if needed; nothing was retried.')

