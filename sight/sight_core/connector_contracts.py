"""Transport-independent contracts. No socket, subprocess, camera, or device access.

These fixtures are intentionally not registered as real device transports. Their
passing tests cannot certify a physical peripheral or enable a remote channel.
"""
import hashlib
import hmac
import json
import secrets
import time
from typing import Literal
from pydantic import Field,model_validator
from .tools import StrictModel
from .security import canonical

class Simulation(StrictModel):
    family:Literal['home','android','printer','camera','call','mcp']
    scenario:Literal['success','disconnect','denied']='success'

class PrintPlan(StrictModel):
    size_mm:tuple[float,float,float]
    build_mm:tuple[float,float,float]
    material:Literal['PLA','PETG']
    profile:str=Field(min_length=1,max_length=80,pattern=r'^[a-zA-Z0-9 _.-]+$')
    nozzle_c:int=Field(ge=170,le=260)
    @model_validator(mode='after')
    def fits(self):
        import math
        if any(not math.isfinite(v) or not 0<v<=1000 for v in (*self.size_mm,*self.build_mm)):raise ValueError('Finite positive dimensions required')
        if any(a>b for a,b in zip(self.size_mm,self.build_mm)):raise ValueError('Model exceeds build volume')
        if self.material=='PLA' and not 180<=self.nozzle_c<=220:raise ValueError('Temperature outside reviewed fixture PLA profile')
        if self.material=='PETG' and not 220<=self.nozzle_c<=250:raise ValueError('Temperature outside reviewed fixture PETG profile')
        return self

class FixtureDevice:
    """Deliberately simulated peripheral, with explicit state/revision and receipts."""
    def __init__(self,trust,identifier,token,connected=True):
        self.trust=trust;self.id=identifier;self.token=token;self.connected=connected;self.revision=0;self.light=False;self.notifications=[]
    def call(self,scope,request_id,args):
        self.trust.authorize(self.id,self.token,scope,request_id)
        if not self.connected:raise ConnectionError('Fixture disconnected; no state fabricated')
        if scope=='status':return {'simulation':True,'revision':self.revision,'connected':True}
        if scope=='home.light':
            if set(args)!={'on','expected_revision'} or type(args['on']) is not bool or args['expected_revision']!=self.revision:raise ValueError('Invalid or stale device command')
            self.light=args['on'];self.revision+=1;return {'simulation':True,'on':self.light,'revision':self.revision}
        if scope=='android.notify':
            if set(args)!={'text'} or not isinstance(args['text'],str) or not 0<len(args['text'])<=200:raise ValueError('Invalid notification')
            self.notifications.append(args['text']);return {'simulation':True,'acknowledged':True,'external_delivery':False}
        if scope=='printer.prepare':
            plan=PrintPlan.model_validate(args);return {'simulation':True,'prepared_digest':hashlib.sha256(canonical(plan.model_dump()).encode()).hexdigest(),'submitted':False}
        raise ValueError('Unsupported fixture operation')

class DeviceTrust:
    """Ephemeral simulator pairing; tokens hashed, requests scoped and single-use."""
    def __init__(self,clock=time.time):self.clock=clock;self.devices={};self.replays=set()
    def pair(self,identifier,scopes):
        if identifier in self.devices:raise ValueError('Already paired')
        if not scopes or not set(scopes)<={'status','home.light','android.notify','printer.prepare'}:raise ValueError('Unsupported scope')
        if len(self.devices)>=16:raise ValueError('Pair limit')
        token=secrets.token_urlsafe(32)
        self.devices[identifier]={'hash':hashlib.sha256(token.encode()).digest(),'scopes':set(scopes),'expires':self.clock()+300}
        return token
    def authorize(self,identifier,token,scope,request_id):
        row=self.devices.get(identifier)
        if not row or self.clock()>=row['expires'] or not hmac.compare_digest(row['hash'],hashlib.sha256(token.encode()).digest()):raise ValueError('Untrusted device')
        if scope not in row['scopes'] or (identifier,request_id) in self.replays:raise ValueError('Scope or replay denied')
        if len(self.replays)>=1000:raise ValueError('Session limit reached; pair a new session')
        self.replays.add((identifier,request_id));return True
    def revoke(self,identifier):self.devices.pop(identifier,None)

class MCPContract:
    """Pinned legacy 2025-06-18 client over an explicitly supplied trusted transport.

No discovered executable, remote URL, or advertised tool is automatically trusted.
Production transports remain disabled pending owner configuration and validation.
"""
    def __init__(self,transport,approved_tools):
        self.transport=transport;self.approved=set(approved_tools);self.sequence=0;self.ready=False
    async def request(self,method,params):
        self.sequence+=1;identifier=self.sequence
        request={'jsonrpc':'2.0','id':identifier,'method':method,'params':params}
        import asyncio
        response=await asyncio.wait_for(self.transport(request),timeout=5)
        if len(canonical(response).encode())>65536:raise ValueError('MCP response too large')
        if response.get('jsonrpc')!='2.0' or response.get('id')!=identifier or 'error' in response or 'result' not in response:raise ValueError('Invalid MCP response')
        return response['result']
    async def initialize(self):
        value=await self.request('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'SIGHT-contract','version':'0.3.0'}})
        if value.get('protocolVersion')!='2025-06-18' or 'tools' not in value.get('capabilities',{}):raise ValueError('Unsupported MCP negotiation')
        import asyncio
        await asyncio.wait_for(self.transport({'jsonrpc':'2.0','method':'notifications/initialized'}),timeout=5)
        self.ready=True;return value
    async def list(self):
        if not self.ready:raise ValueError('MCP initialization required')
        value=await self.request('tools/list',{})
        if not isinstance(value.get('tools'),list) or len(value['tools'])>100:raise ValueError('Invalid tool list')
        return [v for v in value['tools'] if isinstance(v,dict) and v.get('name') in self.approved]
    async def call(self,name,arguments):
        if not self.ready or name not in self.approved:raise ValueError('Unapproved MCP tool')
        value=await self.request('tools/call',{'name':name,'arguments':arguments})
        return {'untrusted_content':True,'is_error':bool(value.get('isError',False)),'content':value.get('content',[])}

def simulate(value:Simulation):
    # Exercise each family's bounded fixture behavior, never a real transport.
    scope={'home':'home.light','android':'android.notify','printer':'printer.prepare'}.get(value.family,'status')
    arguments={'home':{'on':True,'expected_revision':0},'android':{'text':'Synthetic fixture notification'},
               'printer':{'size_mm':[20,10,5],'build_mm':[180,180,180],'material':'PLA','profile':'fixture-only','nozzle_c':200}}.get(value.family,{})
    trust=DeviceTrust();token=trust.pair('fixture',['status'] if value.scenario=='denied' else [scope])
    device=FixtureDevice(trust,'fixture',token,connected=value.scenario!='disconnect')
    try:
        receipt=device.call(scope if value.scenario!='denied' or scope!='status' else 'android.notify','fixture-request',arguments)
    except (ValueError,ConnectionError):
        trust.revoke('fixture')
        return {'simulation':True,'real_device':False,'status':'permission_denied' if value.scenario=='denied' else 'offline','acted':False}
    trust.revoke('fixture')
    return {'simulation':True,'real_device':False,'status':'contract_pass','family':value.family,'paired_then_revoked':True,'acted':False,
            'fixture_receipt':receipt,'coverage':'Mock peripheral state for home/Android/printer; trust/status only for camera/call/MCP. Separate MCP protocol tests cover its lifecycle.',
            'requirements':{'printer':['device endpoint','profile','build volume','material','slicer','final owner print approval'],
                            'camera':['owner consent','camera','vision model','separate action approval'],
                            'call':['account/device','participant consent','final review','no impersonation'],
                            'home':['paired device','scoped local credentials','action review'],
                            'android':['authenticated gateway','per-device scopes','revocation'],
                            'mcp':['pinned protocol','approved server','trusted transport','per-tool schemas']}[value.family]}
