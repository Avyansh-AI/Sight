"""Owner-session learning endpoints; all mutations use the existing scoped grants."""
import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Literal
from fastapi import HTTPException
from pydantic import Field
from .brain_store import BrainStore
from .memory import MemoryService, MemoryInput, MemoryEdit, MemoryDelete
from .forge import Forge, SkillManifest, SkillGenerate, SkillPromote, SkillSelect
from .jobs import Jobs, Job, JobSelect, RolePolicy
from .tools import StrictModel
from .releases import Releases


class Compact(StrictModel):
    ids: list[str] = Field(min_length=1,max_length=20)
    project_id: str = Field(default='default',pattern=r'^[A-Za-z0-9_-]{1,80}$')


class ForgetSkill(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_.-]{2,79}$')


class Empty(StrictModel):pass


class Restore(StrictModel):
    id: str = Field(pattern=r'^[a-f0-9-]{36}$')


ACTIONS={
    'memory/save':MemoryInput,'memory/edit':MemoryEdit,'memory/delete':MemoryDelete,
    'memory/purge':Empty,'memory/compact':Compact,
    'forge/stage':SkillManifest,'forge/generate':SkillGenerate,'forge/promote':SkillPromote,
    'forge/rollback':SkillSelect,'forge/archive':SkillSelect,'forge/forget':ForgetSkill,
    'jobs/submit':Job,'jobs/cancel':JobSelect,'jobs/pause':JobSelect,'jobs/resume':JobSelect,'roles/configure':RolePolicy,
    'backup':Empty,'restore':Restore,'releases/snapshot':Empty,'releases/select':Restore,
}


class Learning:
    def __init__(self, config, files, router):
        self.error=None;self.jobs=None
        try:
            self.store=BrainStore(config.data_dir)
            self.memory=MemoryService(self.store);self.forge=Forge(self.store)
            self.jobs=Jobs(self.store,self.memory,self.forge,files,router)
        except (sqlite3.Error,ValueError,OSError):
            self.error='Learning storage unavailable. Existing data was preserved; restore a verified backup into a new data directory.'
        self.router=router
        self.releases=Releases(config.data_dir)

    def require(self):
        if self.error:raise HTTPException(503,self.error)

    def validate(self,path,args):
        if not path.startswith('/api/learning/'):return None
        self.require();key=path.removeprefix('/api/learning/')
        if key not in ACTIONS:raise ValueError('Unknown learning operation')
        value=ACTIONS[key].model_validate(args)
        if isinstance(value,Job):self.jobs.validate(value)
        summary={'backup':'Create an integrity-checked snapshot of learning, procedures and task receipts.',
                 'restore':'Restore the selected backup to a new isolated directory for inspection. Running data is preserved.',
                 'forge/generate':'Ask the configured model for a restricted text skill draft and test it; promotion requires a separate review.',
                 'forge/promote':'Promote this exact tested skill digest as a new immutable version.',
                 'jobs/submit':'Run this exact task plan within its displayed tool/model budgets. File writes create new workspace files only.',
                 'memory/delete':'Forget this memory and its derived summaries. Historical task receipts and separate backups are retained.',
                 'forge/forget':'Delete all versions and candidates of this skill; keep historical operational receipts.'}.get(key,'Apply the displayed '+key+' change to your local learning data.')
        return value.model_dump(),summary

    async def execute(self,path,args):
        self.require();key=path.removeprefix('/api/learning/')
        if key=='memory/save':return self.memory.put(MemoryInput.model_validate(args))
        if key=='memory/edit':
            identifier=args.pop('id');return self.memory.put(MemoryInput.model_validate(args),identifier)
        if key=='memory/delete':return self.memory.delete(args['id'])
        if key=='memory/purge':return self.memory.purge_expired()
        if key=='memory/compact':return self.memory.compact(args['ids'],args['project_id'])
        if key=='forge/stage':return await asyncio.to_thread(self.forge.stage,SkillManifest.model_validate(args))
        if key=='forge/generate':return await self.forge.generate(SkillGenerate.model_validate(args),self.router)
        if key=='forge/promote':return self.forge.promote(**args)
        if key=='forge/rollback':return self.forge.rollback(args['id'],args['version'])
        if key=='forge/archive':return self.forge.archive(args['id'],args['version'])
        if key=='forge/forget':return self.forge.forget(args['id'])
        if key=='jobs/submit':return self.jobs.submit(Job.model_validate(args))
        if key=='jobs/cancel':return self.jobs.cancel(args['id'])
        if key=='jobs/pause':return self.jobs.pause(args['id'])
        if key=='jobs/resume':return self.jobs.resume(args['id'])
        if key=='roles/configure':self.store.set_setting('role.'+args['role'],args);return args
        if key=='releases/snapshot':return self.releases.snapshot()
        if key=='releases/select':return self.releases.select(args['id'])
        if key=='backup':
            identifier=str(uuid.uuid4());return {'id':identifier}|self.store.backup(self.store.root/'backups'/(identifier+'.sqlite3'))
        if key=='restore':
            destination=self.store.root/'restores'/str(uuid.uuid4())
            restored=BrainStore.restore(self.store.root/'backups'/(args['id']+'.sqlite3'),destination)
            return {'restored':True,'directory':str(restored.root),'activated':False,'instruction':'Inspect the restored data, then launch with SIGHT_DATA_DIR set to this directory; configure the local model separately.'}
        raise ValueError('Unknown operation')

    def status(self):
        if self.error:return {'enabled':False,'status':'storage_error','reason':self.error,'growth_proven':False}
        return {'enabled':True,'status':'ready','stores':['profile','episodic_document','procedural','operational'],
                'workers':1,'logical_roles':12,'growth_proven':False,'benchmark':'See the measured build evidence; no automatic personal-growth claim.',
                'forge_scope':'declarative text transformations','external_code_execution':False}

    def mount(self,app):
        @app.get('/api/learning/releases')
        async def releases():self.require();return {'items':self.releases.list(),'activation':'next restart via Phase-4/Start-SIGHT.ps1'}

        @app.get('/api/learning/benchmark')
        async def benchmark():
            path=Path(__file__).resolve().parents[1]/'reports/growth_benchmark.json'
            if not path.is_file():return {'status':'not_run','growth_proven':False}
            return json.loads(path.read_text(encoding='utf-8'))

        @app.get('/api/learning/memory')
        async def memory(project_id:str='default',q:str=''):
            self.require();return {'items':self.memory.search(q,project_id,50) if q else self.memory.export(project_id)}

        @app.get('/api/learning/memory/{identifier}')
        async def record(identifier:str):
            self.require();row=self.memory.get(identifier)
            if not row:raise HTTPException(404,'Memory is absent or expired')
            return row

        @app.get('/api/learning/export')
        async def export(project_id:str='default'):
            self.require();return {'memory':self.memory.export(project_id),'procedural':self.forge.list(project_id),
                                   'operational':[j for j in self.jobs.list() if j['definition']['project_id']==project_id],
                                   'scope':'Current unexpired memory, procedures and last 100 tasks; retained operational receipts may quote earlier inputs.'}

        @app.get('/api/learning/skills')
        async def skills(project_id:str='default'):
            self.require()
            with self.store.connect() as db:
                candidates=[dict(r)|{'manifest':json.loads(r['manifest']),'tests':json.loads(r['tests'])} for r in db.execute("SELECT * FROM candidates WHERE json_extract(manifest,'$.project_id')=? ORDER BY created_at DESC LIMIT 100",(project_id,))]
            return {'items':self.forge.list(project_id),'candidates':candidates,'curator':self.forge.curator()}

        @app.get('/api/learning/jobs')
        async def jobs():self.require();return {'items':self.jobs.list()}

        @app.get('/api/learning/jobs/{identifier}')
        async def job(identifier:str):
            self.require();row=self.jobs.get(identifier)
            if not row:raise HTTPException(404,'Task not found')
            return row

        @app.get('/api/learning/roles')
        async def roles():self.require();return {'items':self.jobs.roles()}

        @app.get('/api/learning/events')
        async def events():self.require();return {'items':self.store.events()}

        @app.get('/api/learning/graph')
        async def graph(project_id:str='default'):
            self.require()
            nodes=[{'id':r['id'],'label':r['key'],'kind':r['store']} for r in self.memory.export(project_id)]
            nodes += [{'id':f'skill:{r["id"]}:{r["version"]}','label':r['id']+' v'+str(r['version']),'kind':'skill'} for r in self.forge.list(project_id)]
            nodes += [{'id':j['id'],'label':j['definition']['title'],'kind':'task'} for j in self.jobs.list() if j['definition']['project_id']==project_id]
            ids={n['id'] for n in nodes}
            with self.store.connect() as db:
                edges=[dict(e) for e in db.execute('SELECT * FROM graph_edges') if e['source'] in ids and e['target'] in ids]
                reviews=[dict(r) for r in db.execute('SELECT * FROM reviews ORDER BY created_at DESC LIMIT 50')]
            return {'nodes':nodes,'edges':edges,'reviews':reviews,'metrics':self.forge.curator()}
