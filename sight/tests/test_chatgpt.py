import asyncio
import json
import time
from urllib.parse import parse_qs,urlsplit
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sight_core.chatgpt import ChatGPT,ChatGPTPolicy,AUTH
from sight_core.config import Config
from sight_core.store import Store


class MemoryVault:
    def __init__(self):self.data={'accounts':{},'active':None}
    def get(self):return json.loads(json.dumps(self.data))
    def set(self,data):self.data=json.loads(json.dumps(data))


@pytest.fixture
def oauth(tmp_path):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))|{'kid':'fixture','alg':'RS256','use':'sig'}
    state={'key':key,'jwk':jwk,'claims':{},'requests':[],'body':None,'status':200,'scope':'chatgpt.tokens.use.direct openid offline_access','revoke':200}
    store=Store(tmp_path/'data');vault=MemoryVault();urls=[]
    client=ChatGPT(store,Config(tmp_path/'data'),vault=vault,opener=lambda url:urls.append(url) or True)
    def handler(request):
        state['requests'].append(request)
        if request.url.path.endswith('jwks.json'):return httpx.Response(200,json={'keys':[jwk]})
        if request.url.path.endswith('openid-configuration'):return httpx.Response(200,json={'revocation_endpoint':AUTH+'/revoke'})
        if request.url.path=='/revoke':return httpx.Response(state['revoke'])
        if request.url.path.endswith('/token'):
            claims={'iss':AUTH,'aud':'oaiapp_fixture','sub':'owner-fixture','iat':int(time.time()),'exp':int(time.time())+300,'nonce':state.get('nonce',''),'email':'fixture@example.invalid'}|state['claims']
            token=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'fixture'})
            return httpx.Response(200,json={'access_token':'access-fixture','refresh_token':'refresh-fixture','id_token':token,'expires_in':300,'token_type':'Bearer','scope':state['scope']})
        if request.url.path.endswith('/models'):return httpx.Response(200,json={'models':[{'slug':'fixture-model','visibility':'list'},{'slug':'hidden','visibility':'hidden'}]})
        if request.url.path.endswith('/responses'):return httpx.Response(state['status'],content=state['body'],headers={'content-type':'text/event-stream','retry-after':'3600'})
        raise AssertionError(request.url)
    client.transport=httpx.MockTransport(handler)
    return client,state,urls


def begin(client,state):
    client.begin('owner-session');state['nonce']=client.pending['nonce']
    return {'state':client.pending['state'],'code':'code-fixture','client_id':'oaiapp_fixture'}


def connect(client,state):asyncio.run(client.callback(begin(client,state),lambda session:session=='owner-session'))


def test_pkce_state_nonce_and_single_use(oauth):
    client,state,urls=oauth;params=begin(client,state)
    query=parse_qs(urlsplit(urls[0]).query)
    assert query['client_id']==['dynamic_agent_client'] and query['code_challenge_method']==['S256']
    assert query['redirect_uri']==['http://127.0.0.1:8080/auth/callback'] and query['ext_agent_host_id'][0].startswith('urn:uuid:')
    assert 'code_verifier' not in query
    with pytest.raises(ValueError):asyncio.run(client.callback(params|{'state':'wrong'},lambda _:True))
    assert not state['requests']
    asyncio.run(client.callback(params,lambda _:True))
    with pytest.raises(ValueError):asyncio.run(client.callback(params,lambda _:True))
    assert client.status()['status']=='connected_disabled'
    assert 'access-fixture' not in json.dumps(client.status())
    identifier=client.status()['active_account'];host=query['ext_agent_host_id']
    client.begin('owner-session',identifier)
    query=parse_qs(urlsplit(urls[-1]).query)
    assert query['client_id']==['oaiapp_fixture'] and query['ext_agent_host_id']==host and 'agent_name_hint' not in query


@pytest.mark.parametrize('claim,value',[('nonce','wrong'),('aud','wrong-client'),('iss','https://evil.invalid'),('exp',0),('sub',None)])
def test_invalid_identity_rejected(oauth,claim,value):
    client,state,_=oauth;state['claims']={claim:value}
    with pytest.raises((ValueError,jwt.PyJWTError,TypeError)):asyncio.run(client.callback(begin(client,state),lambda _:True))
    assert not client.vault.get()['accounts']


def test_missing_plan_scope_and_wrong_client_rejected(oauth):
    client,state,_=oauth;state['scope']='openid'
    with pytest.raises(ValueError):connect(client,state)
    assert not client.vault.get()['accounts']
    state['scope']='chatgpt.tokens.use.direct';connect(client,state)
    account=client.status()['active_account'];client.begin('session',account)
    with pytest.raises(ValueError):asyncio.run(client.callback({'state':client.pending['state'],'code':'new','client_id':'oaiapp_different'},lambda _:True))


def test_refresh_serialized_rotates_tokens_and_keeps_identity(oauth):
    client,state,_=oauth;connect(client,state)
    data=client.vault.get();data['accounts'][data['active']]['expires_at']=0;client.vault.set(data)
    async def calls():return await asyncio.gather(client.access(),client.access())
    assert asyncio.run(calls())==['access-fixture','access-fixture']
    assert sum(b'grant_type=refresh_token' in r.content for r in state['requests'])==1
    assert asyncio.run(client.models())['items']==[{'slug':'fixture-model','display_name':'fixture-model'}]


@pytest.mark.parametrize('end,expected',[('response.completed','ok'),('response.failed','provider_error'),('response.incomplete','provider_error'),(None,'provider_error')])
def test_stream_requires_completed_and_no_paid_fallback(oauth,end,expected):
    client,state,_=oauth;connect(client,state)
    client.store.set_setting('chatgpt.policy',ChatGPTPolicy(enabled=True,allow_remote_text=True,plan_only_confirmed=True,model='fixture-model').model_dump())
    events=[{'type':'response.output_text.delta','delta':'4'}]+([{'type':end,'response':{'usage':{'input_tokens':4,'output_tokens':1}}}] if end else [])
    state['body']=''.join('data: '+json.dumps(e)+'\n\n' for e in events)
    response=asyncio.run(client.generate('2 plus 2'))
    assert response['status']==expected
    post=next(r for r in state['requests'] if r.url.path.endswith('/responses'));body=json.loads(post.content)
    assert body['store'] is False and body['stream'] is True
    count=len(state['requests']);assert asyncio.run(client.generate('again'))['status']=='rate_limited';assert len(state['requests'])==count


@pytest.mark.parametrize('remote',[200,503])
def test_disconnect_clears_tokens_and_reports_revocation(oauth,remote):
    client,state,_=oauth;connect(client,state);state['revoke']=remote
    result=asyncio.run(client.disconnect())
    assert result['remote_revocation_confirmed']==(remote==200)
    assert 'access-fixture' not in json.dumps(client.vault.get())
    assert 'refresh-fixture' not in json.dumps(client.vault.get())
    assert client.status()['status']=='not_connected'
