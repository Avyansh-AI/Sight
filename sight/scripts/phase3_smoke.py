"""Live Windows launcher + HTTP/WS/local tools + restart smoke. No cloud calls."""
import asyncio
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import httpx
import websockets

ROOT=Path(__file__).resolve().parents[1]
MODEL='hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED:Q4_K_M'

def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    data=ROOT.parent/'test-data'/('live-phase3-'+stamp);data.mkdir(parents=True)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}';log=(data/'server.log').open('w',encoding='utf-8');process=None
    evidence={'timestamp_utc':stamp,'model':MODEL,'cloud_requests':0,'checks':[],'complete':False,'launcher':'Phase-3/Start-SIGHT.ps1','test_data':str(data)}
    def check(name,passed,detail=None):
        evidence['checks'].append({'name':name,'passed':bool(passed),'detail':detail})
        if not passed:raise AssertionError(name)
    def start():
        executable=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        return subprocess.Popen([str(executable),'-NoProfile','-NonInteractive','-File',str(ROOT.parent/'Start-SIGHT.ps1')],cwd=ROOT,env=dict(os.environ,SIGHT_DATA_DIR=str(data),SIGHT_PORT=str(port),SIGHT_OLLAMA_MODEL=MODEL),stdout=log,stderr=subprocess.STDOUT,creationflags=0x08000000)
    def stop():
        if process is not None and process.poll() is None:
            executable=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/taskkill.exe'
            subprocess.run([str(executable),'/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=10,creationflags=0x08000000)
            process.wait(10)
    def connect():
        client=httpx.Client(base_url=url,timeout=130,trust_env=False)
        for _ in range(150):
            if process.poll() is not None:raise RuntimeError('Launcher stopped')
            try:
                if client.get('/').status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        claim=client.post('/api/session/claim',headers={'origin':url},json={'token':(data/'browser-token').read_text()});claim.raise_for_status()
        client.headers['x-sight-csrf']=client.get('/api/session').json()['csrf'];return client
    def invoke(client,identifier,args):
        started=time.perf_counter();path='/api/capability/invoke'
        response=client.post('/api/actions/prepare',json={'path':path,'args':{'id':identifier,'arguments':args}});response.raise_for_status();grant=response.json()
        response=client.post(path,json=grant['args']|{'actionApproval':grant['approvalId']});response.raise_for_status()
        result=response.json();check(identifier,result.get('ok'),{'seconds':round(time.perf_counter()-started,4)});return result['result']
    try:
        process=start()
        with closing(connect()) as client:
            health=client.get('/api/health').json();check('Phase 3 launcher local-only',health['phase']==3 and not health['cloud_enabled'])
            model=client.get('/api/models').json();check('installed Gemma ready',model['local']['status']=='ready')
            for identifier,args in [
                ('files.search',{'query':''}),('documents.docx',{'title':'Live verification','text':'Local document'}),('documents.markdown',{'title':'Note','text':'Live note'}),
                ('coding.inspect',{'text':'def add(a,b):\n    return a+b\n'}),('coding.diff',{'before':'a\n','after':'b\n'}),('coding.site',{'title':'Local page','text':'SIGHT live test'}),
                ('calendar.export',{'title':'Local test event','start':'2026-10-20T10:00:00+05:30','end':'2026-10-20T10:30:00+05:30'}),
                ('cad.box',{'x':20,'y':10,'z':5}),('circuit.ohm',{'volts':5,'ohms':1000}),('geo.distance',{'lat1':0,'lon1':0,'lat2':0,'lon2':1}),
                ('vision.landmarks',{'thumb':[.5,.5],'index':[.51,.5]}),('windows.info',{}),('speech.render',{'text':'SIGHT local smoke test.'}),
                ('browser.inspect',{'html':'<title>Live SIGHT</title><h1>Offline browser</h1><input id="name">','fields':{'name':'Synthetic owner'}}),
                ('reminders.add',{'id':'live-reminder','title':'Synthetic in-app reminder','due':datetime.now(timezone.utc).isoformat()}),
                ('monitor.configure',{'enabled':False}),('briefing.local',{}),('mcp.local',{})]:
                result=invoke(client,identifier,args)
                if artifact:=result.get('artifact'):
                    response=client.get(artifact['download']);check(identifier+' artifact hash',response.status_code==200 and hashlib.sha256(response.content).hexdigest()==artifact['sha256'])
                if identifier=='browser.inspect':check('isolated browser observed text',result['title']=='Live SIGHT' and result['fields']['name']=='Synthetic owner' and not result['network_allowed']);saved=artifact
            for family in ('home','android','printer','camera','call','mcp'):
                result=invoke(client,'contracts.simulate',{'family':family,'scenario':'success'});check(family+' simulated only',result['simulation'] and not result['real_device'])
            async def chat():
                ticket=client.post('/api/access/ticket',json={}).json()['ticket'];cookie='; '.join(k+'='+v for k,v in client.cookies.items())
                async with websockets.connect(url.replace('http:','ws:')+'/ws/app?ticket='+ticket,origin=url,additional_headers={'Cookie':cookie}) as ws:
                    hello=json.loads(await ws.recv());await ws.send(json.dumps({'type':'utterance','text':'Reply only the number: 2 plus 2?','requestId':uuid.uuid4().hex}))
                    while True:
                        value=json.loads(await asyncio.wait_for(ws.recv(),130))
                        if value.get('type')=='response':return hello,value
            started=time.perf_counter();hello,answer=asyncio.run(chat());check('live WebSocket Gemma',hello['phase']==3 and answer['status']=='ok' and answer['say'].strip().rstrip('.')=='4',{'seconds':round(time.perf_counter()-started,4),'answer':answer['say'],'offline':answer['offline']})
            for _ in range(40):
                notifications=client.get('/api/capability/schedules').json()['notifications']
                if notifications:break
                time.sleep(.1)
            check('live reminder delivery',len(notifications)==1)
            check('unchanged original home response',client.get('/').content==(ROOT/'apps/ui/index.html').read_bytes())
        stop();process=start()
        with closing(connect()) as client:
            time.sleep(1.2)
            schedules=client.get('/api/capability/schedules').json();check('restart without duplicate reminder',len(schedules['notifications'])==1 and schedules['items'][0]['state']=='delivered')
            check('immutable artifact survives restart',hashlib.sha256(client.get(saved['download']).content).hexdigest()==saved['sha256'])
            invoke(client,'reminders.cancel',{'id':'live-reminder'})
            check('skill index survives restart',client.get('/api/capability/skills').json()['total']==212)
            check('local-only policy survives restart',not client.get('/api/health').json()['cloud_enabled'])
        evidence['complete']=True
    except Exception as exc:
        evidence['error_type']=type(exc).__name__;raise
    finally:
        stop();log.close();evidence['passed']=evidence['complete'] and all(r['passed'] for r in evidence['checks'])
        path=ROOT.parent/'evidence'/('live_phase3_'+stamp+'.json');path.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        (ROOT/'reports/live_phase3_latest.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        print(json.dumps({'evidence':str(path),'passed':evidence['passed'],'checks':len(evidence['checks'])}))

if __name__=='__main__':main()
