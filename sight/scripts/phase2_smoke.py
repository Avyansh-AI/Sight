"""Live HTTP/UI/WS smoke with the installed Gemma model; cloud is disabled."""
import asyncio
from datetime import datetime,timezone
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

def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    data=ROOT.parent/'test-data'/('live-phase2-'+stamp);data.mkdir(parents=True)
    model='hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED:Q4_K_M'
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}';log=(data/'server.log').open('w',encoding='utf-8')
    process=subprocess.Popen([sys.executable,'-m','sight_core.cli','start','--local-only'],cwd=ROOT,env=dict(os.environ,SIGHT_DATA_DIR=str(data),SIGHT_PORT=str(port),SIGHT_OLLAMA_MODEL=model),stdout=log,stderr=subprocess.STDOUT)
    evidence={'timestamp_utc':stamp,'model':model,'cloud_requests':0,'checks':[]}
    def check(name,passed,detail=None):
        evidence['checks'].append({'name':name,'passed':bool(passed),'detail':detail})
        if not passed:raise AssertionError(name)
    try:
        with httpx.Client(base_url=url,timeout=130,trust_env=False) as client:
            for _ in range(150):
                if process.poll() is not None:raise RuntimeError('Smoke server stopped')
                try:
                    if client.get('/').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            claim=client.post('/api/session/claim',headers={'origin':url},json={'token':(data/'browser-token').read_text()})
            check('owner session',claim.status_code==200)
            client.headers['x-sight-csrf']=client.get('/api/session').json()['csrf']
            def action(name,args):
                path='/api/learning/'+name
                prep=client.post('/api/actions/prepare',json={'path':path,'args':args});prep.raise_for_status();grant=prep.json()
                response=client.post(path,json=grant['args']|{'actionApproval':grant['approvalId']});response.raise_for_status();return response.json()
            for endpoint in ('/api/health','/api/models','/api/learning/status','/learning.html'):
                started=time.perf_counter();r=client.get(endpoint);check(endpoint,r.status_code==200,{'seconds':round(time.perf_counter()-started,3)})
            memory=action('memory/save',{'key':'text.case','content':'upper'})
            started=time.perf_counter();draft=action('forge/generate',{'id':'text.liveclean','description':'Remove duplicate lines and sort alphabetically.','tests':[{'text':'b\na\nb','expected':'a\nb'},{'text':'z\nx\nz','expected':'x\nz'}]})
            check('live Gemma Forge draft',draft.get('state')=='tested',{'state':draft.get('state'),'seconds':round(time.perf_counter()-started,3),'method':draft.get('generation_method')})
            promoted=action('forge/promote',{'candidate_id':draft['candidate_id'],'expected_digest':draft['digest']})
            async def ws_check():
                ticket=client.post('/api/access/ticket',json={}).json()['ticket']
                cookie='; '.join(k+'='+v for k,v in client.cookies.items())
                async with websockets.connect(url.replace('http:','ws:')+'/ws/app?ticket='+ticket,origin=url,additional_headers={'Cookie':cookie}) as ws:
                    hello=json.loads(await ws.recv());await ws.send(json.dumps({'type':'utterance','text':'Reply only the number: 2 plus 2?','requestId':uuid.uuid4().hex}))
                    while True:
                        result=json.loads(await asyncio.wait_for(ws.recv(),130))
                        if result.get('type')=='response':return result
            ws_result=asyncio.run(ws_check());check('live WebSocket Gemma chat',ws_result['status']=='ok' and ws_result['say'].strip().rstrip('.')=='4',{'status':ws_result['status'],'say':ws_result['say'],'memory_sources':ws_result.get('memory_sources')})
            versions=[]
            for repeat in range(2):
                row=action('jobs/submit',{'idempotency_key':uuid.uuid4().hex,'title':'Live learned skill reuse','model_budget':0,'steps':[{'id':'clean','op':'skill.invoke','skill_id':'text.liveclean','text':'b\na\nb'},{'id':'save','op':'file.write','name':f'live-{repeat}.txt','depends_on':['clean'],'input_from':'clean'},{'id':'verify','op':'verify.equals','depends_on':['save'],'input_from':'save','expected':'a\nb'}]})
                for _ in range(100):
                    row=client.get('/api/learning/jobs/'+row['id']).json()
                    if row['state'] not in ('queued','running'):break
                    time.sleep(.05)
                check('durable task '+str(repeat+1),row['state']=='complete' and len(row['receipts'])==1,{'state':row['state'],'tool_calls':row['tool_calls'],'version':row['steps'][0]['result']['version']})
                versions.append(row['steps'][0]['result']['version'])
                check('file receipt '+str(repeat+1),client.get('/api/tools/files/read',params={'name':f'live-{repeat}.txt'}).json()['content']=='a\nb')
            check('same immutable skill reused',versions==[promoted['version']]*2)
            action('memory/delete',{'id':memory['id']});action('forge/forget',{'id':'text.liveclean'})
            check('forget memory and procedural behavior',not client.get('/api/learning/memory').json()['items'] and not client.get('/api/learning/skills').json()['items'])
            check('home HTML unchanged',client.get('/').content==(ROOT/'apps/ui/index.html').read_bytes())
    finally:
        process.terminate()
        try:process.wait(10)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()
        evidence['passed']=bool(evidence['checks']) and all(c['passed'] for c in evidence['checks'])
        path=ROOT.parent/'evidence'/('live_phase2_'+stamp+'.json');path.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        (ROOT/'reports/live_phase2_latest.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        print(json.dumps({'evidence':str(path),'passed':evidence['passed'],'checks':len(evidence['checks'])}))

if __name__=='__main__':main()
