"""Bounded durable DAG runner. Only owner-approved declarative operations execute."""
import asyncio
import hashlib
import json
import os
import time
import uuid
from typing import Literal

from pydantic import Field, model_validator
from .tools import StrictModel, LocalFiles
from .security import canonical, private_directory, TOKEN_PATTERN
from .forge import Operation, sandbox

ROLES = ('coordinator','planner','research','code','test','security_review','browser','desktop','memory','forge','devices','verifier')
OPERATIONS = ('text.transform','memory.format','memory.search','skill.invoke','file.write','model.reply','verify.equals','coding.inspect')


class Step(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_-]{0,39}$')
    role: Literal[ROLES] = 'coordinator'
    op: Literal[OPERATIONS]
    depends_on: list[str] = Field(default_factory=list,max_length=16)
    input_from: str | None = None
    text: str = Field(default='',max_length=8192)
    operations: list[Operation] = Field(default_factory=list,max_length=12)
    skill_id: str = Field(default='',max_length=80)
    name: str = Field(default='',max_length=100)
    expected: str = Field(default='',max_length=8192)
    retries: int = Field(default=0,ge=0,le=2)


class Job(StrictModel):
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{8,100}$')
    title: str = Field(min_length=1,max_length=120)
    project_id: str = Field(default='default',pattern=r'^[A-Za-z0-9_-]{1,80}$')
    owner: Literal['local'] = 'local'
    steps: list[Step] = Field(min_length=1,max_length=16)
    timeout_seconds: int = Field(default=120,ge=1,le=3600)
    tool_budget: int = Field(default=16,ge=1,le=32)
    model_budget: int = Field(default=1,ge=0,le=3)

    @model_validator(mode='after')
    def validate_dag(self):
        ids={s.id for s in self.steps}
        if len(ids)!=len(self.steps):raise ValueError('Duplicate step id')
        done=set()
        for s in self.steps:
            if s.input_from and s.input_from not in s.depends_on:raise ValueError('Input source must be a dependency')
            if set(s.depends_on)-ids:raise ValueError('Missing dependency')
            if s.op=='text.transform' and not s.operations:raise ValueError('Transformation operations required')
            if s.op=='skill.invoke' and not s.skill_id:raise ValueError('Skill id required')
            if s.op=='model.reply' and s.retries:raise ValueError('Model requests are never automatically retried')
        while len(done)<len(ids):
            ready={s.id for s in self.steps if s.id not in done and set(s.depends_on)<=done}
            if not ready:raise ValueError('Cyclic dependency graph')
            done |= ready
        if TOKEN_PATTERN.search(canonical(self.model_dump())):raise ValueError('Credentials are forbidden in task definitions')
        return self


class JobSelect(StrictModel):
    id: str = Field(pattern=r'^[a-f0-9-]{36}$')


class RolePolicy(StrictModel):
    role: Literal[ROLES]
    enabled: bool = True
    tool_budget: int = Field(default=16,ge=0,le=32)
    model_budget: int = Field(default=1,ge=0,le=3)


class Jobs:
    def __init__(self, store, memory, forge, files, router):
        self.store,self.memory,self.forge,self.files,self.router=store,memory,forge,files,router
        self.staging=store.root/'staging'; private_directory(self.staging)
        self.worker=None; self.wakeup=asyncio.Event(); self.stopping=False

    def roles(self):
        return [self.store.setting('role.'+role,RolePolicy(role=role).model_dump()) | {'implementation':'logical role; shared inference lock','available_operations':list(OPERATIONS)} for role in ROLES]

    def validate(self, job):
        for step in job.steps:
            if step.op=='file.write':self.files.path(step.name)
        return job

    def submit(self, job):
        self.validate(job); body=canonical(job.model_dump()); fingerprint=hashlib.sha256(body.encode()).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT id,fingerprint FROM jobs WHERE idempotency_key=?',(job.idempotency_key,)).fetchone()
            if previous:
                if previous['fingerprint']!=fingerprint:raise ValueError('Idempotency key already used for a different plan')
                identifier=previous['id']
            else:
                if db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]>=32:raise ValueError('Task queue is full')
                identifier=str(uuid.uuid4());now=time.time()
                db.execute('INSERT INTO jobs(id,idempotency_key,fingerprint,definition,state,created_at,updated_at,deadline) VALUES(?,?,?,?,?,?,?,?)',
                           (identifier,job.idempotency_key,fingerprint,body,'queued',now,now,now+job.timeout_seconds))
                for step in job.steps:db.execute('INSERT INTO steps(job,id,definition,state) VALUES(?,?,?,?)',(identifier,step.id,canonical(step.model_dump()),'queued'))
                self.store.event('job.approved',identifier,{'fingerprint':fingerprint,'owner':'local'},db)
        self.wakeup.set();return self.get(identifier)

    def get(self, identifier):
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone()
            if not row:return None
            steps=[dict(s)|{'definition':json.loads(s['definition']),'result':json.loads(s['result']) if s['result'] else None} for s in db.execute('SELECT * FROM steps WHERE job=? ORDER BY rowid',(identifier,))]
            receipts=[dict(r) for r in db.execute('SELECT * FROM receipts WHERE job=?',(identifier,))]
        return dict(row)|{'definition':json.loads(row['definition']),'steps':steps,'receipts':receipts}

    def list(self):
        with self.store.connect() as db:ids=[r[0] for r in db.execute('SELECT id FROM jobs ORDER BY created_at DESC LIMIT 100')]
        return [self.get(i) for i in ids]

    def state(self, identifier, state, error=None):
        with self.store.connect() as db:
            db.execute('UPDATE jobs SET state=?,error=?,updated_at=? WHERE id=?',(state,error,time.time(),identifier))
            self.store.event('job.'+state,identifier,{'error':error},db)
            if state in ('complete','failed','needs_review','cancelled','expired'):
                # Debounced after-task proposal, never an automatic preference change.
                db.execute('INSERT OR IGNORE INTO reviews(task,created_at,lesson) VALUES(?,?,?)',(identifier,time.time(),'Review task outcome: '+state+'. Confirm any correction or skill before reuse.'))

    def recover(self):
        with self.store.connect() as db:
            running=[dict(r) for r in db.execute("SELECT job,id,definition FROM steps WHERE state='running'")]
            for s in running:
                ambiguous=json.loads(s['definition'])['op']=='model.reply'
                db.execute('UPDATE steps SET state=?,error=? WHERE job=? AND id=?',('needs_review' if ambiguous else 'queued','Interrupted model call; no automatic retry' if ambiguous else None,s['job'],s['id']))
                if ambiguous:db.execute("UPDATE jobs SET state='needs_review',error='Interrupted model call; inspect before a new request' WHERE id=?",(s['job'],))
            db.execute("UPDATE jobs SET state='queued' WHERE state='running'")
        self.wakeup.set()

    def cancel(self, identifier):
        with self.store.connect() as db:
            row=db.execute('SELECT state FROM jobs WHERE id=?',(identifier,)).fetchone()
            if not row:raise ValueError('Task not found')
            if row[0] not in ('queued','running','paused'):return {'id':identifier,'state':row[0]}
            db.execute('UPDATE jobs SET cancel_requested=1 WHERE id=?',(identifier,))
            if row[0]=='paused':db.execute("UPDATE jobs SET state='queued' WHERE id=?",(identifier,))
        self.wakeup.set();return {'id':identifier,'state':'cancelling','boundary':'between atomic operations'}

    def pause(self,identifier):
        row=self.get(identifier)
        if not row or row['state'] not in ('queued','running'):raise ValueError('Only pending tasks can be paused')
        self.state(identifier,'paused');return {'id':identifier,'state':'paused','boundary':'between atomic operations'}

    def resume(self,identifier):
        row=self.get(identifier)
        if not row or row['state']!='paused':raise ValueError('Only paused tasks can resume; failed or ambiguous model steps need a new reviewed plan')
        if time.time()>=row['deadline']:raise ValueError('Task deadline expired; submit a new plan')
        self.state(identifier,'queued');self.wakeup.set();return {'id':identifier,'state':'queued'}

    def write_once(self, job, step, name, content, after_publish=None):
        """Record a prepared inode before atomically publishing its unique hard link.

        A crash after publication is reconciled by identity and hash. Existing
        unrelated files are never accepted as receipts or overwritten.
        """
        target=self.files.path(name);data=content.encode();digest=hashlib.sha256(data).hexdigest()
        if len(data)>65536:raise ValueError('File content exceeds limit')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM receipts WHERE job=? AND step=?',(job,step)).fetchone()
            if not row:
                identifier=str(uuid.uuid4())
                db.execute('INSERT INTO receipts(id,job,step,name,content_hash,state) VALUES(?,?,?,?,?,?)',(identifier,job,step,name,digest,'intent'))
            else:identifier=row['id']
        with self.store.connect() as db:row=dict(db.execute('SELECT * FROM receipts WHERE id=?',(identifier,)).fetchone())
        if row['name']!=name or row['content_hash']!=digest:raise ValueError('Receipt conflicts with requested content')
        stage=self.staging/identifier
        if LocalFiles.is_link(stage) or LocalFiles.is_link(self.staging):raise ValueError('Invalid staging location')
        if row['state']=='intent':
            if stage.exists():stage.unlink()  # An unpublished crash fragment, private and receipt-bound.
            with stage.open('xb') as handle:
                handle.write(data);handle.flush();os.fsync(handle.fileno());info=os.fstat(handle.fileno())
            with self.store.connect() as db:db.execute("UPDATE receipts SET device=?,inode=?,state='prepared' WHERE id=?",(info.st_dev,info.st_ino,identifier))
            row.update(device=info.st_dev,inode=info.st_ino,state='prepared')
        if target.exists():
            info=target.stat()
            if (info.st_dev,info.st_ino)!=(row['device'],row['inode']) or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
                raise ValueError('Target already exists or was changed; manual review required')
        else:
            if row['state']=='complete':raise ValueError('Previously completed file was removed; no automatic rewrite')
            info=stage.stat()
            if (info.st_dev,info.st_ino)!=(row['device'],row['inode']) or hashlib.sha256(stage.read_bytes()).hexdigest()!=digest:raise ValueError('Prepared file integrity failed')
            os.link(stage,target)
            if after_publish:after_publish()
        if stage.exists():stage.unlink()
        with self.store.connect() as db:
            db.execute("UPDATE receipts SET state='complete' WHERE id=?",(identifier,))
            self.store.event('file.receipt',job,{'receipt':identifier,'step':step,'sha256':digest},db)
        return {'text':content,'receipt_id':identifier,'name':name,'sha256':digest,'source_event_id':identifier}

    async def operation(self, identifier, step, text, project, remote_allowed=True):
        if step.op=='text.transform':return {'text':await asyncio.to_thread(sandbox,text,[o.model_dump() for o in step.operations])}
        if step.op=='memory.format':
            preference=next((r for r in self.memory.preferences(project) if r['key']=='text.case'),None)
            case=preference['content'].strip().lower() if preference else ''
            return {'text':text.upper() if case=='upper' else text.lower() if case=='lower' else text,'source_event_id':preference['source_event_id'] if preference else None,'memory_id':preference['id'] if preference else None,'remote_allowed':not preference or preference['privacy_scope']=='cloud_allowed'}
        if step.op=='memory.search':
            rows=self.memory.search(text,project)
            return {'text':canonical(rows),'remote_allowed':all(r['privacy_scope']=='cloud_allowed' for r in rows)}
        if step.op=='skill.invoke':return await asyncio.to_thread(self.forge.invoke,step.skill_id,text,project,identifier)
        if step.op=='file.write':return self.write_once(identifier,step.id,step.name,text)
        if step.op=='coding.inspect':
            from .local_adapters import inspect_python
            return {'text':canonical(inspect_python(text)),'remote_allowed':False,'executed':False}
        if step.op=='verify.equals':
            if text!=step.expected:raise ValueError('Output did not match the approved expected value')
            return {'text':text,'verified':True}
        if step.op=='model.reply':
            answer=await self.router.generate(text,allow_cloud=remote_allowed)
            if answer['status']!='ok':raise ValueError('Model request unavailable: '+answer['status'])
            return {'text':answer['say'],'provider':answer.get('provider','local'),'usage':answer.get('usage')}
        raise ValueError('Unsupported operation')

    async def run(self, identifier):
        record=self.get(identifier)
        if not record or record['state'] not in ('queued','running'):return
        self.state(identifier,'running')
        while True:
            record=self.get(identifier);job=Job.model_validate(record['definition'])
            if record['state']=='paused':return
            if record['cancel_requested']:self.state(identifier,'cancelled');return
            if time.time()>=record['deadline']:self.state(identifier,'expired');return
            complete={s['id'] for s in record['steps'] if s['state']=='complete'}
            if len(complete)==len(job.steps):self.state(identifier,'complete');return
            chosen=next((s for s in record['steps'] if s['state']=='queued' and set(s['definition']['depends_on'])<=complete),None)
            if not chosen:self.state(identifier,'needs_review','A dependency requires review');return
            step=Step.model_validate(chosen['definition']);model=step.op=='model.reply'
            role=RolePolicy.model_validate(self.store.setting('role.'+step.role,RolePolicy(role=step.role).model_dump()))
            role_used=sum(s['attempts'] for s in record['steps'] if s['definition']['role']==step.role and (s['definition']['op']=='model.reply')==model)
            if not role.enabled or role_used >= (role.model_budget if model else role.tool_budget):self.state(identifier,'needs_review','Role disabled or role budget exhausted');return
            if record['model_calls' if model else 'tool_calls'] >= (job.model_budget if model else job.tool_budget):self.state(identifier,'needs_review','Approved task budget exhausted');return
            text=next(s['result']['text'] for s in record['steps'] if s['id']==step.input_from) if step.input_from else step.text
            remote_allowed=all(s['result'].get('remote_allowed',True) for s in record['steps'] if s['id']==step.input_from)
            with self.store.connect() as db:
                db.execute("UPDATE steps SET state='running',attempts=attempts+1 WHERE job=? AND id=?",(identifier,step.id))
                column='model_calls' if model else 'tool_calls'
                db.execute(f'UPDATE jobs SET {column}={column}+1 WHERE id=?',(identifier,))
                event=self.store.event('step.started',identifier,{'step':step.id,'role':step.role},db)
            try:
                if model:
                    result=await asyncio.wait_for(self.operation(identifier,step,text,job.project_id,remote_allowed),max(.01,record['deadline']-time.time()))
                else:result=await self.operation(identifier,step,text,job.project_id,remote_allowed)
                result['step_source_event_id']=event
                result['remote_allowed']=remote_allowed and result.get('remote_allowed',True)
                with self.store.connect() as db:
                    db.execute("UPDATE steps SET state='complete',result=?,error=NULL WHERE job=? AND id=?",(canonical(result),identifier,step.id))
                    self.store.event('step.complete',identifier,{'step':step.id,'source_event_id':event},db)
            except asyncio.CancelledError:
                # Shutdown checkpoints remain 'running' for conservative recovery.
                raise
            except Exception as exc:
                retry=step.op in ('text.transform','memory.search','memory.format','skill.invoke','verify.equals') and chosen['attempts']<step.retries
                with self.store.connect() as db:db.execute('UPDATE steps SET state=?,error=? WHERE job=? AND id=?',('queued' if retry else 'failed',type(exc).__name__,identifier,step.id))
                if not retry:self.state(identifier,'failed',str(exc)[:200] if isinstance(exc,ValueError) else type(exc).__name__);return

    async def loop(self):
        while not self.stopping:
            self.wakeup.clear()
            with self.store.connect() as db:row=db.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row:
                try:await self.run(row[0])
                except asyncio.CancelledError:raise
                except Exception:self.state(row[0],'needs_review','Task storage or execution unavailable')
            else:
                try:await asyncio.wait_for(self.wakeup.wait(),1)
                except TimeoutError:pass

    async def start(self):
        self.recover();self.stopping=False;self.worker=asyncio.create_task(self.loop())

    async def stop(self):
        self.stopping=True
        if self.worker:self.worker.cancel();await asyncio.gather(self.worker,return_exceptions=True)
