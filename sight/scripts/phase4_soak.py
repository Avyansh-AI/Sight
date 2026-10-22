"""Wall-clock local-model soak with real HTTP/WS, crash/restart and telemetry.

The host network is never disabled. Faults are confined to this test server's
loopback model transport. No provider keys, remote inference or owner data used.
"""
import argparse
import asyncio
import ctypes
from ctypes import wintypes
from datetime import datetime,timezone
import hashlib
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import socket
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import uuid
import httpx
import websockets

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sight_core.recovery import backup_all,restore_all

def source_hashes():
    result = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('sight_core','apps') for p in sorted((ROOT/folder).rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    for name in ('requirements.lock', 'requirements-bootstrap.lock', 'scripts/launch.py',
                 'scripts/soak_worker.py'):
        result[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    return result

def dependency_versions():
    return dict(sorted((d.metadata['Name'], d.version) for d in distributions()))

class Telemetry:
    def __init__(self,path,pidfile):self.path=path;self.pidfile=pidfile;self.stop=threading.Event();self.previous=None;self.samples=[]
    def sample(self):
        class Memory(ctypes.Structure):
            _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[(k,ctypes.c_uint64) for k in ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(k,ctypes.c_size_t) for k in ('peak_ws','working_set','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
        mem=Memory();mem.length=ctypes.sizeof(mem)
        if not kernel.GlobalMemoryStatusEx(ctypes.byref(mem)):raise ctypes.WinError(ctypes.get_last_error())
        idle,kern,user=ctypes.c_uint64(),ctypes.c_uint64(),ctypes.c_uint64()
        if not kernel.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kern),ctypes.byref(user)):raise ctypes.WinError(ctypes.get_last_error())
        total=kern.value+user.value;cpu=None
        if self.previous and total>self.previous[1]:cpu=round(100*(1-(idle.value-self.previous[0])/(total-self.previous[1])),2)
        self.previous=(idle.value,total)
        row={'utc':datetime.now(timezone.utc).isoformat(),'host_ram_total_mib':round(mem.total/2**20,2),'host_ram_available_mib':round(mem.available/2**20,2),
             'host_commit_available_mib':round(mem.page_available/2**20,2),'host_cpu_percent':cpu,'cpu_temperature_c':None,'server_working_set_mib':None}
        if self.pidfile.exists():
            kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            handle=kernel.OpenProcess(0x410,False,int(self.pidfile.read_text()))
            if handle:
                try:
                    counters=Counters();counters.cb=ctypes.sizeof(counters)
                    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
                    if psapi.GetProcessMemoryInfo(handle,ctypes.byref(counters),counters.cb):row['server_working_set_mib']=round(counters.working_set/2**20,2)
                finally:kernel.CloseHandle(handle)
        try:
            result=subprocess.run(['nvidia-smi','--query-gpu=memory.total,memory.used,utilization.gpu,temperature.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=8,creationflags=0x08000000,check=True)
            fields=[float(v.strip()) for v in result.stdout.splitlines()[0].split(',')]
            row.update(gpu_total_mib=fields[0],gpu_used_mib=fields[1],gpu_utilization_percent=fields[2],gpu_temperature_c=fields[3])
        except (OSError,subprocess.SubprocessError,ValueError,IndexError) as exc:row['gpu_error']=type(exc).__name__
        return row
    def run(self):
        with self.path.open('w',encoding='utf-8') as output:
            while not self.stop.is_set():
                try:row=self.sample()
                except Exception as exc:row={'utc':datetime.now(timezone.utc).isoformat(),'telemetry_error':type(exc).__name__}
                self.samples.append(row);output.write(json.dumps(row)+'\n');output.flush();self.stop.wait(5)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=3600);parser.add_argument('--model',required=True)
    parser.add_argument('--thinking',action='store_true',help='Explicit comparison run; default uses the selected non-thinking configuration')
    args=parser.parse_args()
    if not 10<=args.seconds<=7200:raise ValueError('Duration must be 10..7200 real seconds')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]
    evidence_dir=ROOT.parent/'evidence'/('soak-'+stamp);evidence_dir.mkdir(parents=True)
    data=ROOT.parent/'test-data'/('soak-'+stamp);data.mkdir(parents=True)
    (data/'local-model.json').write_text(json.dumps({'model':args.model,'thinking':args.thinking}),encoding='utf-8')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}';process=None;client=None;log=(evidence_dir/'server.log').open('w',encoding='utf-8')
    control=data/'test-transport-fault';control.write_text('')
    result={'started_utc':datetime.now(timezone.utc).isoformat(),'requested_seconds':args.seconds,'model':args.model,'thinking':args.thinking,'data_dir':str(data),'checks':[],
            'cloud_requests':0,'fault_scope':'Test-process loopback model transport; host network unchanged','source_hashes':source_hashes(),'dependency_versions':dependency_versions(),'complete':False,'cycles':0,'model_calls':[],'planned_server_crashes':0,'unplanned_server_exits':0}
    checks=result['checks'];ws_ids=[];job_ids=[];telemetry=Telemetry(evidence_dir/'telemetry.jsonl',data/'soak-server.pid')
    thread=threading.Thread(target=telemetry.run,daemon=True);thread.start();start=time.monotonic()
    def save():
        result['elapsed_seconds']=round(time.monotonic()-start,3)
        (evidence_dir/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        (ROOT/'reports/soak_progress.json').write_text(json.dumps({'evidence':str(evidence_dir),'elapsed_seconds':result['elapsed_seconds'],'requested_seconds':args.seconds,'cycles':result['cycles'],'failed_checks':sum(not c['passed'] for c in checks),'complete':result['complete']},indent=2),encoding='utf-8')
    def check(name,passed,detail=None):
        checks.append({'name':name,'passed':bool(passed),'elapsed_seconds':round(time.monotonic()-start,3),'detail':detail})
        if not passed:save();raise AssertionError(name)
    def launch():
        return subprocess.Popen([sys.executable,'-B',str(ROOT/'scripts/soak_worker.py')],cwd=ROOT,env=dict(os.environ,SIGHT_DATA_DIR=str(data),SIGHT_PORT=str(port),SIGHT_OLLAMA_MODEL=args.model),stdout=log,stderr=subprocess.STDOUT,creationflags=0x08000000)
    def stop():
        if process is not None and process.poll() is None:
            subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/taskkill.exe'),'/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15,creationflags=0x08000000)
            process.wait(10)
    def connect():
        c=httpx.Client(base_url=url,timeout=135,trust_env=False)
        for _ in range(200):
            if process.poll() is not None:raise RuntimeError('Soak server exited')
            try:
                if c.get('/api/session',timeout=2).status_code==401:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        c.post('/api/session/claim',json={'token':(data/'browser-token').read_text()},headers={'origin':url}).raise_for_status()
        c.headers['x-sight-csrf']=c.get('/api/session').json()['csrf'];return c
    def action(path,arguments):
        prepared=client.post('/api/actions/prepare',json={'path':path,'args':arguments});prepared.raise_for_status();grant=prepared.json()
        response=client.post(path,json=grant['args']|{'actionApproval':grant['approvalId']});response.raise_for_status();return response.json()
    async def socket_request(identifier,text):
        ticket=client.post('/api/access/ticket',json={}).json()['ticket']
        cookie='; '.join(k+'='+v for k,v in client.cookies.items())
        async with websockets.connect(url.replace('http:','ws:')+'/ws/app?ticket='+ticket,origin=url,additional_headers={'Cookie':cookie}) as ws:
            hello=json.loads(await asyncio.wait_for(ws.recv(),5));check('authenticated WebSocket reconnect',hello['type']=='hello' and hello['phase']==4)
            await ws.send(json.dumps({'type':'utterance','text':text,'requestId':identifier}))
            while True:
                response=json.loads(await asyncio.wait_for(ws.recv(),130))
                if response.get('type')=='response':return response
    try:
        process=launch();client=connect()
        check('home HTML exact bytes',client.get('/').content==(ROOT/'apps/ui/index.html').read_bytes())
        due=datetime.now(timezone.utc).isoformat()
        action('/api/capability/invoke',{'id':'reminders.add','arguments':{'id':'soak-reminder','title':'Synthetic soak notification','due':due}})
        cycle=0
        while time.monotonic()-start<args.seconds:
            cycle_start=time.monotonic()
            if process.poll() is not None:result['unplanned_server_exits']+=1;check('server still running',False)
            health=client.get('/api/health').json();check('core healthy and cloud disabled',health['ok'] and health['phase']==4 and not health['cloud_enabled'])
            answer=action('/api/capability/invoke',{'id':'circuit.ohm','arguments':{'volts':5,'ohms':1000}})
            check('approved local tool',answer['result']['amperes']==.005)
            identifier=uuid.uuid4().hex;ws_ids.append(identifier)
            answer=asyncio.run(socket_request(identifier,'help'));check('socket response received',answer['status']=='ok')
            repeated=asyncio.run(socket_request(identifier,'help'));check('socket retry is idempotent',repeated==answer)
            job=action('/api/learning/jobs/submit',{'idempotency_key':'soak-'+uuid.uuid4().hex,'title':'Synthetic durable write','steps':[{'id':'write','op':'file.write','name':f'cycle-{cycle}.txt','text':f'cycle {cycle}'}],'model_budget':0})
            job_ids.append(job['id'])
            for _ in range(100):
                job=client.get('/api/learning/jobs/'+job['id']).json()
                if job['state'] in ('complete','failed','needs_review'):break
                time.sleep(.1)
            check('durable task completes once',job['state']=='complete' and len(job['receipts'])==1)
            if cycle%5==0:
                request={'text':'What is 17 plus 25? Reply with the number only.','requestId':uuid.uuid4().hex}
                tick=time.monotonic();answer=client.post('/api/utterance',json=request).json()
                result['model_calls'].append({'cycle':cycle,'seconds':round(time.monotonic()-tick,3),'status':answer.get('status'),'answer':answer.get('say'),'expected_answer':'42','answer_correct':answer.get('say','').strip().strip('.')=='42','recovery':answer.get('recovery'),'local_inference_requests':answer.get('local_inference_requests',1)})
                check('real Gemma inference completes',answer.get('status')=='ok' and bool(answer.get('say','').strip()) and answer.get('offline'))
            if cycle%10==3:
                control.write_text('disconnect')
                try:
                    failed=client.post('/api/utterance',json={'text':'Synthetic connection failure check','requestId':uuid.uuid4().hex}).json()
                    check('injected runtime outage fails locally',failed.get('status')=='offline' and failed.get('offline'))
                    check('UI survives unavailable runtime',client.get('/').status_code==200)
                finally:control.write_text('')
                check('runtime metadata reconnects',client.get('/api/models').json()['local']['status']=='ready')
            if cycle in (10,30,50):
                control.write_text('delay')
                pending=action('/api/learning/jobs/submit',{'idempotency_key':'crash-'+uuid.uuid4().hex,'title':'Interrupted model task','steps':[{'id':'ask','op':'model.reply','text':'Synthetic crash test'}]})
                for _ in range(100):
                    pending=client.get('/api/learning/jobs/'+pending['id']).json()
                    if pending['steps'][0]['state']=='running':break
                    time.sleep(.05)
                check('durable model step running before crash',pending['steps'][0]['state']=='running')
                client.close();stop();result['planned_server_crashes']+=1;control.write_text('')
                process=launch();client=connect()
                restored=client.get('/api/learning/jobs/'+pending['id']).json()
                check('interrupted model task not replayed',restored['state']=='needs_review')
                check('completed task survives process crash',client.get('/api/learning/jobs/'+job_ids[-1]).json()['state']=='complete')
            result['cycles']=cycle+1;save();print(json.dumps({'cycle':cycle,'elapsed_seconds':result['elapsed_seconds'],'failed_checks':sum(not c['passed'] for c in checks)}),flush=True)
            cycle+=1
            while time.monotonic()-cycle_start<60 and time.monotonic()-start<args.seconds:time.sleep(min(1,max(.01,args.seconds-(time.monotonic()-start))))
        check('one reminder without replay',len(client.get('/api/capability/schedules').json()['notifications'])==1)
        client.close();client=None;stop()
        with sqlite3.connect(data/'sight.sqlite3') as db:
            count=db.execute("SELECT COUNT(*) FROM requests WHERE state='complete'").fetchone()[0]
            check('all WebSocket requests durably recorded',all(db.execute("SELECT state FROM requests WHERE id=?",(key,)).fetchone()==('complete',) for key in ws_ids),{'completed_requests':count})
            check('event start and finish records retained',db.execute("SELECT COUNT(*) FROM events WHERE type='task.started'").fetchone()[0]==db.execute("SELECT COUNT(*) FROM events WHERE type='task.finished'").fetchone()[0])
        with sqlite3.connect(data/'brain.sqlite3') as db:
            check('no stuck durable agents',db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('running','queued')").fetchone()[0]==0)
            check('exactly one receipt per completed task',db.execute("SELECT COUNT(*) FROM receipts WHERE state='complete'").fetchone()[0]==len(job_ids))
        bundle=evidence_dir/'backup';recovered=data.parent/(data.name+'-restored')
        backup_all(data,bundle);restore_all(bundle,recovered)
        check('soak output files survive full restore',all((recovered/'files'/f'cycle-{i}.txt').read_text()==f'cycle {i}' for i in range(result['cycles'])))
        result['source_unchanged_during_run']=source_hashes()==result['source_hashes'];check('runtime source unchanged during soak',result['source_unchanged_during_run'])
        result['dependencies_unchanged_during_run']=dependency_versions()==result['dependency_versions'];check('installed dependencies unchanged during soak',result['dependencies_unchanged_during_run'])
        result['complete']=True
    except Exception as exc:
        result['error_type']=type(exc).__name__;result['error']=str(exc)
    finally:
        if client:client.close()
        stop();log.close();telemetry.stop.set();thread.join(15)
        values=lambda name:[r[name] for r in telemetry.samples if isinstance(r.get(name),(int,float))]
        result['telemetry']={'samples':len(telemetry.samples),'peak_gpu_mib':max(values('gpu_used_mib'),default=None),'peak_gpu_temperature_c':max(values('gpu_temperature_c'),default=None),
                             'minimum_available_host_ram_mib':min(values('host_ram_available_mib'),default=None),'peak_host_cpu_percent':max(values('host_cpu_percent'),default=None),
                             'peak_server_working_set_mib':max(values('server_working_set_mib'),default=None),'cpu_temperature':'not available from the standard interfaces used'}
        result['elapsed_seconds']=round(time.monotonic()-start,3)
        result['one_hour_qualified']=result['complete'] and args.seconds>=3600 and result['elapsed_seconds']>=3600 and all(c['passed'] for c in checks) and bool(values('gpu_used_mib')) and max(values('gpu_used_mib'))<8192
        if result['model_calls']:
            times=sorted(r['seconds'] for r in result['model_calls']);result['model_latency']={'median_seconds':statistics.median(times),'max_seconds':max(times),'sample_count':len(times)}
            result['model_answer_correct_count']=sum(r['answer_correct'] for r in result['model_calls'])
            result['quality_scope']='Stability qualification measures runtime completion, not reasoning correctness; answer checks are reported separately.'
        save();(ROOT/'reports/soak_latest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({'evidence':str(evidence_dir),'complete':result['complete'],'one_hour_qualified':result['one_hour_qualified'],'error':result.get('error')}),flush=True)
    return 0 if result['complete'] else 1

if __name__=='__main__':raise SystemExit(main())
