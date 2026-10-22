import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from sight_core.brain_store import BrainStore
from sight_core.memory import MemoryService,MemoryInput
from sight_core.forge import Forge,SkillManifest,sandbox
from sight_core.jobs import Jobs,Job,Step,RolePolicy
from sight_core.tools import LocalFiles
from sight_core.api import create_app
from sight_core.config import Config


@pytest.fixture
def brain(tmp_path):
    store=BrainStore(tmp_path/'data')
    return store,MemoryService(store),Forge(store)


def recipe(op='upper',expected='HELLO'):
    return SkillManifest(id='text.upper',title='Uppercase',operations=[{'op':op}],tests=[{'text':'hello','expected':expected},{'text':'Hi','expected':'HI' if op=='upper' else 'hi'}])


def engine(brain):
    class Router:
        async def generate(self,text,**kwargs):return {'status':'ok','say':text,'offline':True}
    return Jobs(*brain,LocalFiles(brain[0].root/'files'),Router())


def run_job(jobs,steps,key='test-key-123',**kwargs):
    row=jobs.submit(Job(idempotency_key=key,title='Test',steps=steps,**kwargs))
    asyncio.run(jobs.run(row['id']))
    return jobs.get(row['id'])


def approve(client,path,args):
    prepared=client.post('/api/actions/prepare',json={'path':path,'args':args})
    assert prepared.status_code==200,prepared.text
    grant=prepared.json()
    return client.post(path,json=grant['args']|{'actionApproval':grant['approvalId']})


def test_memory_provenance_project_privacy_and_forgetting(brain):
    store,memory,_=brain
    a=memory.put(MemoryInput(key='color',content='cobalt',ttl_days=1))
    b=memory.put(MemoryInput(key='color',content='orange',project_id='other',privacy_scope='cloud_allowed'))
    assert memory.search('cobalt')[0]['source_event_id'].startswith('owner-')
    assert not memory.search('cobalt',remote=True)
    assert not memory.search('orange')
    summary=memory.compact([a['id']])
    assert len(memory.search('cobalt'))==2
    edited=memory.put(MemoryInput(key='color',content='jade'),a['id'])
    assert edited['revision']==2 and memory.get(summary['id']) is None
    assert not memory.search('cobalt')
    memory.delete(a['id'])
    assert not memory.context('jade')['text'] and memory.export('default')==[]
    assert memory.get(b['id'])
    assert 'cobalt' not in json.dumps(store.events())


def test_expired_source_disables_summary_without_purge(brain):
    _,memory,_=brain;now=time.time();memory.clock=lambda:now
    a=memory.put(MemoryInput(key='temporary',content='quartz',ttl_days=1))
    b=memory.compact([a['id']]);c=memory.compact([b['id']])
    now+=86401
    assert memory.get(a['id']) is None and memory.get(b['id']) is None and memory.get(c['id']) is None
    assert memory.export()==[] and memory.search('quartz')==[]
    assert memory.purge_expired()['purged']==1


def test_memory_rejects_secrets_and_sql_fts_syntax(brain):
    _,m,_=brain
    with pytest.raises(ValueError):m.put(MemoryInput(key='key',content='gsk_'+'x'*30))
    m.put(MemoryInput(key='note',content='safe'))
    assert isinstance(m.search('" OR * : () safe'),list)


def test_forge_generation_schema_and_invalid_json(brain):
    from sight_core.forge import SkillGenerate
    class Router:
        answer='{"operations": ["trim"]]}'
        async def generate(self,text,**kwargs):
            assert kwargs['json_schema']['properties']['operations']['items']
            return {'status':'ok','say':self.answer}
    router=Router();request=SkillGenerate(id='text.generated',description='Uppercase text',tests=[{'text':'hi','expected':'HI'},{'text':'bye','expected':'BYE'}])
    assert asyncio.run(brain[2].generate(request,router))['state']=='rejected'
    router.answer='{"operations":[{"op":"upper"}]}'
    assert asyncio.run(brain[2].generate(request,router))['state']=='tested'


def test_ollama_uses_structured_format_for_forge(tmp_path,monkeypatch):
    import httpx
    from sight_core.models import OllamaProvider,ModelStatus
    from sight_core.forge import OperationPlan
    calls=[]
    def respond(request):
        calls.append(json.loads(request.content));return httpx.Response(200,json={'message':{'content':'{"operations":[{"op":"upper"}]}'}})
    provider=OllamaProvider(Config(tmp_path,model='fixture'),transport=httpx.MockTransport(respond))
    async def health():return ModelStatus('ready','fixture','fixture',True)
    monkeypatch.setattr(provider,'_metadata_health',health)
    result=asyncio.run(provider.generate_json('uppercase text',OperationPlan.model_json_schema()))
    assert result['status']=='ok' and calls[0]['format']==OperationPlan.model_json_schema()


def test_launcher_rejects_corrupt_snapshot_and_preserves_baseline(tmp_path):
    from sight_core.releases import Releases
    root=Path(__file__).resolve().parents[1]
    releases=Releases(tmp_path/'data');snapshot=releases.snapshot();releases.select(snapshot['id'])
    environment=dict(os.environ,SIGHT_DATA_DIR=str(tmp_path/'data'))
    command=[sys.executable,str(root/'scripts/launch.py'),'--check']
    good=subprocess.run(command,cwd=root,env=environment,capture_output=True,text=True,timeout=10)
    assert good.returncode==0 and Path(good.stdout.strip())==releases.root/snapshot['id']
    (releases.root/snapshot['id']/'sight_core/api.py').write_text('faulty update')
    bad=subprocess.run(command,cwd=root,env=environment,capture_output=True,text=True,timeout=10)
    assert bad.returncode==0 and Path(bad.stdout.strip())==root
    assert 'failed verification' in bad.stderr


def test_backup_restore_hash_migration_and_corruption(brain,tmp_path):
    store,m,_=brain;m.put(MemoryInput(key='color',content='blue'))
    backup=tmp_path/'snapshots'/'one.db';store.backup(backup)
    restored=BrainStore.restore(backup,tmp_path/'restored')
    assert MemoryService(restored).preferences()[0]['content']=='blue'
    assert restored.owner_id==store.owner_id
    backup.write_bytes(backup.read_bytes()+b'tamper')
    with pytest.raises(ValueError,match='hash'):BrainStore.restore(backup,tmp_path/'bad')


def test_corrupt_memory_keeps_core_ui_available(tmp_path):
    data=tmp_path/'bad';data.mkdir();(data/'brain.sqlite3').write_bytes(b'broken database')
    app=create_app(Config(data))
    with TestClient(app,base_url='http://127.0.0.1:8080') as client:
        assert client.get('/').status_code==200
        client.post('/api/session/claim',json={'token':app.state.bootstrap_token},headers={'origin':'http://127.0.0.1:8080'})
        assert client.get('/api/learning/status').json()['status']=='storage_error'
        assert client.get('/api/learning/memory').status_code==503
        assert client.get('/api/health').status_code==200
    assert (data/'brain.sqlite3').read_bytes()==b'broken database'


def test_forge_promote_reuse_failed_candidate_rollback_forget(brain):
    store,_,f=brain;c=f.stage(recipe());assert c['state']=='tested'
    first=f.promote(c['candidate_id'],c['digest']);assert first['version']==1
    with pytest.raises(ValueError):f.promote(c['candidate_id'],c['digest'])
    assert f.invoke('text.upper','ab')['text']=='AB'
    assert f.invoke('text.upper','cd')['version']==1
    assert f.curator()['skills'][0]['reused']==1
    bad=f.stage(recipe(expected='wrong'));assert bad['state']=='rejected'
    with pytest.raises(ValueError):f.promote(bad['candidate_id'],bad['digest'])
    assert f.active('text.upper')['version']==1
    good=f.stage(recipe('lower','hello'));f.promote(good['candidate_id'],good['digest'])
    assert f.invoke('text.upper','Ab')['text']=='ab'
    f.rollback('text.upper',1);assert f.invoke('text.upper','Ab')['text']=='AB'
    with store.connect() as db:db.execute('UPDATE procedures SET last_used=?,created_at=?',(time.time()-15*86400,time.time()-15*86400))
    assert f.curator()['skills'][0]['proposal']=='archive_review'
    f.archive('text.upper',1);assert f.active('text.upper') is None
    f.rollback('text.upper',1);assert f.active('text.upper')
    f.forget('text.upper');assert not f.list()
    with pytest.raises(ValueError):f.invoke('text.upper','Ab')


@pytest.mark.parametrize('payload',[
    {'op':'exec','value':'import os'}, {'op':'read_file','value':'C:/secret'},
    {'op':'http','value':'https://example.com'}, {'op':'upper','shell':'whoami'},
    {'op':'replace_literal','old':'','new':'X'},
])
def test_sandbox_rejects_authority_escalation(payload):
    with pytest.raises(ValueError):sandbox('hello',[payload])


def test_forge_manifest_rejects_dependencies_network(brain):
    for update in ({'dependencies':['https://evil.invalid/pkg']},{'network_required':True},{'secrets':['key']},{'permissions':['file.write']}):
        with pytest.raises(ValidationError):SkillManifest.model_validate(recipe().model_dump()|update)
    candidate=brain[2].stage(SkillManifest.model_validate(recipe().model_dump()|{'dependencies':['example==1.0']}))
    assert candidate['state']=='needs_dependency_review' and candidate['tests']==[]
    with pytest.raises(ValueError):brain[2].promote(candidate['candidate_id'],candidate['digest'])


def test_task_memory_privacy_survives_transformation(brain):
    jobs=engine(brain);brain[1].put(MemoryInput(key='text.case',content='upper'))
    seen=[]
    async def model(text,**kwargs):seen.append(kwargs);return {'status':'ok','say':text}
    jobs.router.generate=model
    row=run_job(jobs,[Step(id='mem',op='memory.format',text='Hi'),Step(id='trim',op='text.transform',input_from='mem',depends_on=['mem'],operations=[{'op':'trim'}]),Step(id='ask',op='model.reply',input_from='trim',depends_on=['trim'])])
    assert row['state']=='complete' and seen==[{'allow_cloud':False}]


def test_task_pause_resume_role_budget_deadline(brain):
    jobs=engine(brain)
    row=jobs.submit(Job(idempotency_key='pause-task-key',title='pause',steps=[Step(id='one',op='memory.format')]))
    jobs.pause(row['id']);asyncio.run(jobs.run(row['id']));assert jobs.get(row['id'])['state']=='paused'
    jobs.resume(row['id']);asyncio.run(jobs.run(row['id']));assert jobs.get(row['id'])['state']=='complete'
    brain[0].set_setting('role.coordinator',RolePolicy(role='coordinator',enabled=False).model_dump())
    assert run_job(jobs,[Step(id='one',op='memory.format')],key='role-blocked-key')['state']=='needs_review'
    row=jobs.submit(Job(idempotency_key='deadline-key',title='expired',steps=[Step(id='one',op='memory.format')]))
    with brain[0].connect() as db:db.execute('UPDATE jobs SET deadline=0 WHERE id=?',(row['id'],))
    asyncio.run(jobs.run(row['id']));assert jobs.get(row['id'])['state']=='expired'


def test_release_snapshot_rollback_corrupt_upgrade(tmp_path):
    from sight_core.releases import Releases
    releases=Releases(tmp_path/'data');first=releases.snapshot();second=releases.snapshot()
    releases.select(first['id']);assert releases.selected().name==first['id']
    releases.select(second['id']);assert releases.selected().name==second['id']
    broken=releases.root/second['id']/'sight_core/api.py';broken.write_text('broken upgrade')
    with pytest.raises(ValueError,match='hash'):releases.selected()
    releases.select(first['id']);assert releases.selected().name==first['id']
    with pytest.raises(ValueError):releases.select('../escape')
    (releases.root/first['id']/'unverified.py').write_text('unverified extra module')
    with pytest.raises(ValueError,match='unmanifested'):releases.selected()


def test_real_task_process_crash_and_resume(brain):
    jobs=engine(brain)
    row=jobs.submit(Job(idempotency_key='crash-task-key',title='crash',steps=[Step(id='save',op='file.write',name='task.txt',text='exactly once'),Step(id='verify',op='verify.equals',depends_on=['save'],input_from='save',expected='exactly once')],tool_budget=4))
    code="""import os,sys,asyncio
from pathlib import Path
from sight_core.brain_store import BrainStore
from sight_core.memory import MemoryService
from sight_core.forge import Forge
from sight_core.jobs import Jobs
from sight_core.tools import LocalFiles
store=BrainStore(Path(sys.argv[1]));jobs=Jobs(store,MemoryService(store),Forge(store),LocalFiles(store.root/'files'),None)
write=jobs.write_once
jobs.write_once=lambda *args:write(*args,after_publish=lambda:os._exit(88))
asyncio.run(jobs.run(sys.argv[2]))
"""
    process=subprocess.run([sys.executable,'-c',code,str(brain[0].root),row['id']],capture_output=True,text=True,timeout=10)
    assert process.returncode==88,process.stderr
    inode=(jobs.files.root/'task.txt').stat().st_ino
    assert jobs.get(row['id'])['state']=='running'
    jobs.recover();asyncio.run(jobs.run(row['id']));result=jobs.get(row['id'])
    assert result['state']=='complete' and len(result['receipts'])==1
    assert (jobs.files.root/'task.txt').stat().st_ino==inode


def test_task_dag_budgets_idempotency_and_receipts(brain):
    jobs=engine(brain)
    steps=[Step(id='format',op='text.transform',text=' hello ',operations=[{'op':'trim'}]),
           Step(id='save',op='file.write',name='result.txt',input_from='format',depends_on=['format']),
           Step(id='verify',op='verify.equals',input_from='save',depends_on=['save'],expected='hello')]
    r=run_job(jobs,steps)
    assert r['state']=='complete' and r['tool_calls']==3 and len(r['receipts'])==1
    assert jobs.files.read('result.txt')=='hello'
    assert jobs.submit(Job(idempotency_key='test-key-123',title='Test',steps=steps))['id']==r['id']
    with pytest.raises(ValueError):jobs.submit(Job(idempotency_key='test-key-123',title='Changed',steps=steps))
    assert run_job(jobs,steps,key='budget-key',tool_budget=1)['state']=='needs_review'
    with pytest.raises(ValidationError):Job(idempotency_key='cycle-key',title='cycle',steps=[Step(id='a',op='memory.format',depends_on=['a'])])


def test_memory_correction_changes_task_then_forget_removes_effect(brain):
    jobs=engine(brain);_,m,_=brain
    steps=[Step(id='format',op='memory.format',text='Hello')]
    assert run_job(jobs,steps,key='before-key')['steps'][0]['result']['text']=='Hello'
    row=m.put(MemoryInput(key='text.case',content='upper'))
    assert run_job(jobs,steps,key='after-key')['steps'][0]['result']['text']=='HELLO'
    m.put(MemoryInput(key='text.case',content='lower'),row['id'])
    assert run_job(jobs,steps,key='edited-key')['steps'][0]['result']['text']=='hello'
    m.delete(row['id'])
    assert run_job(jobs,steps,key='forgot-key')['steps'][0]['result']['text']=='Hello'


def test_file_crash_recovery_real_process(brain):
    jobs=engine(brain);root=brain[0].root
    code="""import os,sys
from sight_core.brain_store import BrainStore
from sight_core.memory import MemoryService
from sight_core.forge import Forge
from sight_core.jobs import Jobs
from sight_core.tools import LocalFiles
store=BrainStore(sys.argv[1]);jobs=Jobs(store,MemoryService(store),Forge(store),LocalFiles(store.root/'files'),None)
jobs.write_once('crash-job','save','crash.txt','once',after_publish=lambda:os._exit(87))
"""
    result=subprocess.run([sys.executable,'-c',code,str(root)],capture_output=True,text=True,timeout=10)
    assert result.returncode==87,result.stderr
    inode=(jobs.files.root/'crash.txt').stat().st_ino
    r=jobs.write_once('crash-job','save','crash.txt','once')
    assert (jobs.files.root/'crash.txt').stat().st_ino==inode
    assert jobs.files.read('crash.txt')=='once'
    assert jobs.write_once('crash-job','save','crash.txt','once')['receipt_id']==r['receipt_id']
    jobs.files.write_new('unrelated.txt','once')
    with pytest.raises(ValueError):jobs.write_once('other','save','unrelated.txt','once')


def test_restart_interrupted_model_no_automatic_retry_and_cancel(brain):
    jobs=engine(brain)
    r=jobs.submit(Job(idempotency_key='restart-key',title='model',steps=[Step(id='one',op='model.reply',text='hello')]))
    with brain[0].connect() as db:
        db.execute("UPDATE jobs SET state='running' WHERE id=?",(r['id'],))
        db.execute("UPDATE steps SET state='running',attempts=1 WHERE job=?",(r['id'],))
    jobs.recover();assert jobs.get(r['id'])['state']=='needs_review'
    asyncio.run(jobs.run(r['id']));assert jobs.get(r['id'])['model_calls']==0
    r=jobs.submit(Job(idempotency_key='cancel-key',title='cancel',steps=[Step(id='one',op='memory.format')]))
    jobs.cancel(r['id']);asyncio.run(jobs.run(r['id']));assert jobs.get(r['id'])['state']=='cancelled'


def test_learning_api_grants_bound_to_content_and_ui(client):
    path='/api/learning/memory/save';args={'key':'text.case','content':'upper'}
    assert client.post(path,json=args).status_code==403
    r=approve(client,path,args);assert r.status_code==200,r.text
    identifier=r.json()['id']
    assert client.get('/api/learning/memory').json()['items'][0]['id']==identifier
    assert client.get('/api/learning/export').json()['memory'][0]['id']==identifier
    assert approve(client,'/api/learning/memory/delete',{'id':identifier}).status_code==200
    assert client.get('/api/learning/memory/'+identifier).status_code==404
    assert client.get('/api/learning/status').json()['enabled']
    assert len(client.get('/api/learning/roles').json()['items'])==12


def test_job_api_background_execution(client):
    r=approve(client,'/api/learning/jobs/submit',{'idempotency_key':'api-job-key','title':'Approved task','steps':[{'id':'one','op':'text.transform','text':'hello','operations':[{'op':'upper'}]}]})
    assert r.status_code==200,r.text
    for _ in range(100):
        row=client.get('/api/learning/jobs/'+r.json()['id']).json()
        if row['state']=='complete':break
        time.sleep(.02)
    assert row['state']=='complete' and row['steps'][0]['result']['text']=='HELLO'
    assert len(client.get('/api/learning/graph').json()['reviews'])==1
