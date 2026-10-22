"""Typed progressive capability discovery and owner-approved local dispatch."""
import asyncio
import base64
import csv
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
from pydantic import Field
from fastapi import HTTPException
from fastapi.responses import FileResponse
from . import local_adapters as local
from .artifacts import Artifacts,TYPES
from .connector_contracts import Simulation,simulate
from .proactive import Proactive,Reminder,Select,Monitor
from .security import canonical,TOKEN_PATTERN
from .tools import StrictModel

ROOT=Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Spec:
    id:str
    family:str
    description:str
    schema:type
    permissions:str='local.compute'
    risk:str='read'
    dependencies:tuple=()
    available:bool=True
    reason:str=''

SPECS=[
    Spec('files.search','files','Find names in the private SIGHT text workspace',local.Search,'sight.workspace.read'),
    Spec('documents.docx','documents','Create a plain text Word document without macros',local.Document,'artifacts.create','reversible-write'),
    Spec('documents.markdown','documents','Create a Markdown note',local.Document,'artifacts.create','reversible-write'),
    Spec('coding.inspect','coding','Parse Python syntax and list symbols without execution',local.Text),
    Spec('coding.diff','coding','Preview a unified text diff; never apply or run it',local.Diff),
    Spec('coding.site','coding','Create an escaped static HTML draft',local.Document,'artifacts.create','reversible-write'),
    Spec('calendar.export','calendar','Create one local ICS event; no invitations or account writes',local.Calendar,'artifacts.create','reversible-write'),
    Spec('cad.box','cad','Generate a watertight rectangular cuboid STL in millimetres',local.Box,'artifacts.create','reversible-write'),
    Spec('circuit.ohm','circuit','Calculate ideal resistor current/power below 25 V; no wiring control',local.Circuit),
    Spec('geo.distance','geospatial','Calculate great-circle distance between supplied coordinates',local.Geo),
    Spec('vision.landmarks','vision','Measure pinch distance in supplied normalized landmarks; no camera or action',local.Gesture),
    Spec('browser.inspect','browser','Inspect owner-supplied HTML, fill local fields, and capture a screenshot; offline, scripts disabled',local.BrowserHTML,'browser.isolated','read',('Playwright Chromium',)),
    Spec('speech.render','speech','Render text to an offline WAV with installed Windows voice; no microphone or playback',local.Speech,'artifacts.create','reversible-write',('Windows System.Speech and installed voice',),os.name=='nt','Windows desktop voice required'),
    Spec('windows.info','windows','Read operating system and Python architecture; no process/window contents',local.Empty,'system.read','read',('Windows',),os.name=='nt','Windows required'),
    Spec('reminders.add','notifications','Schedule a durable in-app reminder, optionally at a fixed UTC interval',Reminder,'notifications.schedule','reversible-write'),
    Spec('reminders.cancel','notifications','Cancel one scheduled in-app reminder',Select,'notifications.schedule','reversible-write'),
    Spec('monitor.configure','proactive','Enable local disk health change alerts and UTC quiet hours',Monitor,'notifications.monitor','reversible-write'),
    Spec('briefing.local','proactive','Compose actual local reminders and capability availability; online feeds reported unavailable',local.Empty,'notifications.read'),
    Spec('contracts.simulate','contracts','Run an explicitly simulated peripheral trust contract; no device traffic',Simulation),
    Spec('mcp.local','mcp','Inspect the owner-authenticated local MCP tool bridge and its approval requirements',local.Empty),
]

BLOCKED=[
    ('browser.remote','browser','External navigation, downloads and account form submission','DISABLED_SECURITY','Opt-in network policy and trusted browsing transport are not configured'),
    ('browser.cdp','browser','Connect to an existing browser session','DISABLED_SECURITY','Owner-authorized CDP endpoint and account access scope are absent'),
    ('windows.input','windows','Mouse, keyboard, focused windows and screen capture','DISABLED_SECURITY','Interactive target/window authorization and recovery qualification pending'),
    ('files.organize','files','Folder move/rename/delete with undo','DISABLED_SECURITY','Selected folder roots and reversible organization adapter pending'),
    ('documents.pdf','documents','PDF conversion, spreadsheets and presentations','REFERENCE_ONLY','Optional conversion engines and independently verified format adapters pending'),
    ('home.devices','home','Kasa and home device control','BLOCKED_HARDWARE','No paired home device or scoped credentials; simulator only'),
    ('calendar.account','calendar','Connected account calendar access','BLOCKED_CREDENTIALS','No calendar account authorization; local ICS export available'),
    ('android.gateway','android','Authenticated Android commands and revocation','BLOCKED_HARDWARE','No paired Android gateway; in-memory trust contract only'),
    ('speech.listen','speech','Local STT, wake detection and barge-in','BLOCKED_HARDWARE','STT model/backend and opt-in microphone pipeline absent; enrollment is a later owner gate'),
    ('camera.gesture','vision','Live camera gesture and face observations','BLOCKED_HARDWARE','No camera consent or installed vision pipeline; supplied landmarks only'),
    ('printer.submit','printers','Slicing and reviewed OctoPrint/Moonraker submission','BLOCKED_HARDWARE','No printer, slicer, material/profile or endpoint authorized; no Bambu support assumed'),
    ('calls.assistant','calls','Call or meeting assistant','BLOCKED_CREDENTIALS','No connected call account, participant consent or audio transport'),
    ('geo.live','geospatial','Weather, flight, ISS, earthquake and map services','DISABLED_SECURITY','No opt-in live data adapter; offline values are never fabricated'),
    ('mcp.remote','mcp','External MCP tools','DISABLED_SECURITY','No approved external server or transport; protocol contract fixtures only'),
    ('channels.remote','channels','Cross-device tool RPC','DISABLED_SECURITY','Remote channels have no listener; device trust and transport qualification pending'),
    ('games.update','coding','Game download and update automation','DISABLED_SECURITY','No platform authorization, download/storage limits or updater adapter'),
    ('communications.send','communications','Spotify, Discord and message delivery','BLOCKED_CREDENTIALS','No platform authorization or final reviewed recipient/action'),
]

class Invocation(StrictModel):
    id:str=Field(pattern=r'^[a-z][a-z0-9_.]{1,79}$')
    arguments:dict=Field(default_factory=dict)

class Capabilities:
    def __init__(self,store,files):
        self.store=store;self.files=files;self.artifacts=Artifacts(store.path.parent)
        self.proactive=Proactive(store);self.specs={s.id:s for s in SPECS};self.lock=asyncio.Lock()
        self.skills=[];self.skill_error=None
        path=ROOT/'reports/hermes_skill_inventory.json'
        try:
            self.skills=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(self.skills,list) or any(not isinstance(r,dict) or not {'path','name'}<=r.keys() for r in self.skills):raise ValueError('Invalid inventory')
        except (ValueError,OSError):self.skills=[];self.skill_error='Skill index unavailable; restore the verified build inventory'

    def registry(self,schemas=False):
        rows=[]
        for spec in SPECS:
            row={'id':spec.id,'family':spec.family,'description':spec.description,'status':'approval_required' if spec.available else 'blocked',
                 'available':spec.available,'reason':spec.reason if not spec.available else '', 'permission_scope':spec.permissions,
                 'risk_tier':spec.risk,'dependencies':list(spec.dependencies),'required_network':[],'secrets':[],'timeout':25,
                 'rollback':'Immutable new artifact or local schedule only; no external rollback claimed','provenance':'Independent SIGHT implementation; reference concepts only',
                 'verification':'See reports/latest_test_run.json; runtime availability is not a hardware certification'}
            if schemas:row['input_schema']=spec.schema.model_json_schema()
            rows.append(row)
        rows.extend({'id':identifier,'family':family,'description':description,'status':status,'available':False,'reason':reason,
                     'permission_scope':'disabled','risk_tier':'high','dependencies':[reason],'required_network':['owner-approved transport'],
                     'secrets':['provider/device credentials when applicable'],'timeout':0,'verification':'UNVERIFIED_REAL_DEVICE'} for identifier,family,description,status,reason in BLOCKED)
        return rows

    def search(self,query='',limit=8):
        terms=re.findall(r'[a-z0-9]+',query.lower())[:12]
        rows=self.registry();ranked=[]
        for row in rows:
            hay=(row['id']+' '+row['family']+' '+row['description']).lower();score=sum(1 for word in terms if word in hay)
            if not terms or score:ranked.append((score,row))
        return [row for _,row in sorted(ranked,key=lambda v:(-v[0],v[1]['id']))[:max(1,min(limit,20))]]

    def validate(self,path,args):
        if path!='/api/capability/invoke':return None
        value=Invocation.model_validate(args);spec=self.specs.get(value.id)
        if not spec or not spec.available:raise ValueError('Capability unavailable')
        parsed=spec.schema.model_validate(value.arguments)
        normalized={'id':value.id,'arguments':parsed.model_dump(mode='json')}
        if TOKEN_PATTERN.search(canonical(normalized)):raise ValueError('Credentials are not tool arguments')
        return normalized,spec.description+'. Permission: '+spec.permissions+'. Review these exact arguments.'

    async def worker(self,identifier,args):
        # A fresh process per operation recovers from browser crashes; never attaches
        # to the user's browser. Kill the owned process tree on timeout/cancellation.
        process=await asyncio.create_subprocess_exec(sys.executable,'-I',str(ROOT/'sight_core/capability_worker.py'),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,
                                                     **({'creationflags':0x08000000} if os.name=='nt' else {'start_new_session':True}))
        try:
            output,_=await asyncio.wait_for(process.communicate(canonical({'id':identifier,'arguments':args}).encode()),22)
            if len(output)>12*1024**2 or process.returncode:raise ValueError('Adapter dependency unavailable or operation failed')
            result=json.loads(output)
            if 'error' in result:raise ValueError('Adapter failed')
            return result
        finally:
            if process.returncode is None:
                if os.name=='nt':
                    executable=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/taskkill.exe'
                    killer=await asyncio.create_subprocess_exec(str(executable),'/PID',str(process.pid),'/T','/F',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL,creationflags=0x08000000)
                    await killer.wait()
                else:
                    import signal
                    os.killpg(process.pid,signal.SIGKILL)
                await process.wait()

    async def invoke(self,args):
        normalized,_=self.validate('/api/capability/invoke',args)
        if self.lock.locked():raise ValueError('A capability is already running')
        async with self.lock:
            identifier=normalized['id'];value=self.specs[identifier].schema.model_validate(normalized['arguments']);started=time.monotonic()
            self.store.event('capability.started',{'id':identifier})
            try:
                if identifier=='files.search':result={'names':[name for name in self.files.list() if value.query.casefold() in name.casefold()]}
                elif identifier=='documents.docx':result={'artifact':self.artifacts.put(local.docx(value),'docx')}
                elif identifier=='documents.markdown':result={'artifact':self.artifacts.put('# '+value.title+'\n\n'+value.text+'\n','md')}
                elif identifier=='coding.inspect':result=local.inspect_python(value.text)
                elif identifier=='coding.diff':result={'diff':local.diff(value),'applied':False}
                elif identifier=='coding.site':result={'artifact':self.artifacts.put(local.static_site(value),'html'),'published':False}
                elif identifier=='calendar.export':result={'artifact':self.artifacts.put(local.calendar(value),'ics'),'invitations_sent':False}
                elif identifier=='cad.box':result={'artifact':self.artifacts.put(local.box_stl(value),'stl'),'volume_mm3':value.x*value.y*value.z,'triangles':12,'units':'mm','printed':False}
                elif identifier=='circuit.ohm':result={'amperes':value.volts/value.ohms,'watts':value.volts**2/value.ohms,'ideal_model':True,'hardware_controlled':False}
                elif identifier=='geo.distance':result=local.distance(value)
                elif identifier=='vision.landmarks':
                    import math
                    distance=math.dist(value.thumb,value.index);result={'distance':distance,'pinch':distance<0.05,'camera_accessed':False,'action_performed':False}
                elif identifier in ('browser.inspect','speech.render'):
                    result=await self.worker(identifier,normalized['arguments']);field,extension=('screenshot','png') if identifier=='browser.inspect' else ('wav','wav')
                    data=base64.b64decode(result.pop(field),validate=True);result['artifact']=self.artifacts.put(data,extension)
                elif identifier=='windows.info':result={'system':platform.system(),'release':platform.release(),'architecture':platform.machine()}
                elif identifier=='reminders.add':result=self.proactive.add(value)
                elif identifier=='reminders.cancel':result=self.proactive.cancel(value.id)
                elif identifier=='monitor.configure':result=self.proactive.configure(value)
                elif identifier=='briefing.local':result={'reminders':self.proactive.list(),'notifications':self.proactive.notifications(),'online_feeds':{'weather':'not_connected','flights':'not_connected','printer':'not_paired'},'measured_at':time.time()}
                elif identifier=='contracts.simulate':result=simulate(value)
                elif identifier=='mcp.local':
                    from .mcp_bridge import TOOLS,VERSION
                    result={'endpoint':'/api/mcp','protocol':VERSION,'tools':sorted(TOOLS),'authentication':'OS owner session plus CSRF','authorization':'exact one-use actionApproval per call','remote_enabled':False}
                else:raise ValueError('No implementation')
            except BaseException:
                self.store.event('capability.failed',{'id':identifier});raise
            self.store.event('capability.finished',{'id':identifier,'seconds':round(time.monotonic()-started,4)})
            return {'ok':True,'capability':identifier,'result':result}

    def mount(self,app):
        from .mcp_bridge import LocalMCP
        self.mcp=LocalMCP(self);self.mcp.mount(app)
        @app.get('/api/capability/search')
        async def search(q:str='',limit:int=8):
            if len(q)>200:raise HTTPException(422,'Query too long')
            return {'items':self.search(q,limit),'schemas_deferred':True}

        @app.get('/api/capability/describe/{identifier}')
        async def describe(identifier:str):
            row=next((r for r in self.registry(True) if r['id']==identifier),None)
            if row is None:raise HTTPException(404,'Unknown capability')
            return row

        @app.get('/api/capability/skills')
        async def skills(q:str='',offset:int=0):
            if len(q)>200 or not 0<=offset<=10000:raise HTTPException(422,'Invalid search')
            items=[r for r in self.skills if q.casefold() in (r['path']+' '+r['name']).casefold()]
            return {'items':items[offset:offset+25],'total':len(items),'executable':False,'error':self.skill_error}

        @app.get('/api/capability/artifacts')
        async def artifacts():return {'items':self.artifacts.list()}

        @app.get('/api/capability/artifacts/{identifier}')
        async def artifact(identifier:str):
            try:
                path=self.artifacts.path(identifier)
                if not path.is_file():raise ValueError()
            except (ValueError,OSError):raise HTTPException(404,'Artifact unavailable')
            return FileResponse(path,filename=identifier,media_type=TYPES[path.suffix[1:]],headers={'Content-Security-Policy':"sandbox; default-src 'none'"})

        @app.get('/api/capability/schedules')
        async def schedules():return {'items':self.proactive.list(),'notifications':self.proactive.notifications(),'error':self.proactive.error,'monitor':self.store.setting('phase3.monitor',Monitor().model_dump())}
