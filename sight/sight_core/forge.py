"""Low-risk declarative Forge. Generated Python, packages, network and filesystem APIs are excluded."""
import hashlib
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Literal, Annotated
import uuid

from pydantic import Field
from .security import canonical
from .tools import StrictModel


class Operation(StrictModel):
    op: Literal['trim','lower','upper','normalize_spaces','sort_lines','dedupe_lines','replace_literal','prefix','suffix']
    value: str = Field(default='',max_length=128)
    old: str = Field(default='',max_length=128)
    new: str = Field(default='',max_length=128)


class Example(StrictModel):
    text: str = Field(max_length=4096)
    expected: str = Field(max_length=8192)


class OperationPlan(StrictModel):
    operations: list[Operation] = Field(min_length=1,max_length=12)


class SkillManifest(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_.-]{2,79}$')
    title: str = Field(min_length=1,max_length=100)
    description: str = Field(default='',max_length=500)
    project_id: str = Field(default='default',pattern=r'^[A-Za-z0-9_-]{1,80}$')
    operations: list[Operation] = Field(min_length=1,max_length=12)
    tests: list[Example] = Field(min_length=2,max_length=8)
    license: Literal['owner-generated','MIT'] = 'owner-generated'
    permissions: list[Literal['text.transform']] = Field(default_factory=lambda:['text.transform'],max_length=1)
    network_required: Literal[False] = False
    secrets: list[str] = Field(default_factory=list,max_length=0)
    dependencies: list[Annotated[str,Field(pattern=r'^[A-Za-z0-9_.-]{1,60}(==[A-Za-z0-9_.-]{1,30})?$')]] = Field(default_factory=list,max_length=8)
    timeout_seconds: Literal[2] = 2
    rollback: Literal['immutable_version'] = 'immutable_version'


class SkillGenerate(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_.-]{2,79}$')
    description: str = Field(min_length=5,max_length=300)
    project_id: str = Field(default='default',pattern=r'^[A-Za-z0-9_-]{1,80}$')
    tests: list[Example] = Field(min_length=2,max_length=8)


class SkillPromote(StrictModel):
    candidate_id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    expected_digest: str = Field(pattern=r'^[a-f0-9]{64}$')


class SkillSelect(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_.-]{2,79}$')
    version: int = Field(ge=1,le=10000)


def sandbox(text, operations):
    payload=json.dumps({'text':text,'operations':operations},ensure_ascii=True)
    if len(payload.encode())>65536:raise ValueError('Sandbox payload exceeds limit')
    with tempfile.TemporaryDirectory(prefix='sight-skill-') as directory:
        result=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('skill_worker.py'))],
            input=payload,capture_output=True,text=True,encoding='utf-8',timeout=2,cwd=directory,
            env={'SYSTEMROOT':os.environ.get('SYSTEMROOT','C:/Windows'),'PYTHONUTF8':'1'},shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode or len(result.stdout)>200000:raise ValueError('Declarative sandbox rejected the skill')
    parsed=json.loads(result.stdout)
    if parsed.get('ok') is not True or not isinstance(parsed.get('result'),str):raise ValueError('Invalid sandbox result')
    return parsed['result']


class Forge:
    def __init__(self,store):self.store=store

    def stage(self,manifest:SkillManifest,method='owner_declarative',source_event_id=None):
        body=manifest.model_dump(); encoded=canonical(body); sha=hashlib.sha256(encoded.encode()).hexdigest()
        results=[]
        for case in ([] if manifest.dependencies else manifest.tests):
            try:
                actual=sandbox(case.text,body['operations'])
                results.append({'passed':actual==case.expected,'actual':actual,'expected':case.expected})
            except (ValueError,subprocess.TimeoutExpired):results.append({'passed':False,'error':'Sandbox rejected or timed out'})
        identifier=str(uuid.uuid4());event=source_event_id or 'owner-'+str(uuid.uuid4())
        state='needs_dependency_review' if manifest.dependencies else 'tested' if all(r['passed'] for r in results) else 'rejected'
        with self.store.connect() as db:
            db.execute('INSERT INTO candidates VALUES(?,?,?,?,?,?,?,?)',(identifier,encoded,sha,canonical(results),state,time.time(),event,method))
            self.store.event('forge.'+state,identifier,{'skill':manifest.id,'digest':sha,'tests_passed':sum(r['passed'] for r in results),'generation_method':method},db)
        return {'candidate_id':identifier,'digest':sha,'state':state,'tests':results,'manifest':body,'generation_method':method,
                'dependency_policy':'Dependency requests pause here. This text-only Forge cannot install packages; revise to an approved built-in operation or leave the candidate paused.' if manifest.dependencies else 'No external dependencies'}

    async def generate(self,request:SkillGenerate,router):
        prompt=('Return JSON only: {"operations":[{"op":"trim"}]}. Build a text transformation for: '+request.description+
                '. Allowed op values: trim, lower, upper, normalize_spaces, sort_lines, dedupe_lines, replace_literal, prefix, suffix. '
                'Only optional literal fields value, old, new; no code, tools, files or network.')
        response=await router.generate(prompt,json_schema=OperationPlan.model_json_schema())
        if response.get('status')!='ok':return {'state':'needs_action','reason':response.get('status'),'message':response.get('say')}
        raw=response['say'].strip()
        if raw.startswith('```'):raw='\n'.join(raw.splitlines()[1:-1])
        try:data=OperationPlan.model_validate_json(raw).model_dump()
        except ValueError:return {'state':'rejected','reason':'Model output did not match the allowed transformation schema; nothing promoted','generation_method':'model:'+response.get('provider','local')}
        manifest=SkillManifest(id=request.id,title=request.description[:100],description=request.description,
                               project_id=request.project_id,operations=data['operations'],tests=request.tests)
        return await asyncio.to_thread(self.stage,manifest,'model:'+response.get('provider','local'),'model-draft-'+str(uuid.uuid4()))

    def promote(self,candidate_id,expected_digest):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM candidates WHERE id=?',(candidate_id,)).fetchone()
            if not row or row['state']!='tested' or row['digest']!=expected_digest or hashlib.sha256(row['manifest'].encode()).hexdigest()!=expected_digest:
                raise ValueError('Only an unchanged, tested candidate may be promoted')
            manifest=SkillManifest.model_validate_json(row['manifest'])
            if manifest.dependencies:raise ValueError('Dependencies remain unresolved; promotion is blocked')
            version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM procedures WHERE id=?',(manifest.id,)).fetchone()[0]
            previous=db.execute('SELECT version FROM procedures WHERE id=? AND active=1',(manifest.id,)).fetchone()
            db.execute('UPDATE procedures SET active=0 WHERE id=?',(manifest.id,))
            now=time.time()
            db.execute('INSERT INTO procedures(id,version,owner_id,project_id,manifest,digest,tests,created_at,last_confirmed_at,source_event_id,confidence,expiry,privacy_scope,active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)',
                (manifest.id,version,self.store.owner_id,manifest.project_id,row['manifest'],row['digest'],row['tests'],now,now,row['source_event_id'],1,None,'local'))
            db.execute("UPDATE candidates SET state='promoted' WHERE id=?",(candidate_id,))
            db.execute('INSERT OR IGNORE INTO graph_edges VALUES(?,?,?)',(candidate_id,f'skill:{manifest.id}:{version}','promoted_to'))
            self.store.event('forge.promoted',manifest.id,{'version':version,'rollback_target':previous[0] if previous else None,'digest':expected_digest},db)
        return {'id':manifest.id,'version':version,'rollback_target':previous[0] if previous else None}

    def list(self,project_id=None,include_archived=True):
        with self.store.connect() as db:
            rows=db.execute('SELECT * FROM procedures WHERE (? IS NULL OR project_id=?) AND (? OR archived=0) ORDER BY id,version',(project_id,project_id,include_archived))
            return [dict(r)|{'manifest':json.loads(r['manifest']),'tests':json.loads(r['tests']),
                             'stale':time.time()-(r['last_used'] or r['created_at'])>14*86400} for r in rows]

    def active(self,identifier,project_id='default'):
        return next((r for r in self.list(project_id,False) if r['id']==identifier and r['active']),None)

    def invoke(self,identifier,text,project_id='default',task='manual'):
        row=self.active(identifier,project_id)
        if not row:raise ValueError('Skill missing or archived; request Forge review')
        if hashlib.sha256(canonical(row['manifest']).encode()).hexdigest()!=row['digest']:raise ValueError('Skill integrity failed')
        invocation=str(uuid.uuid4());success=False
        try:
            output=sandbox(text,row['manifest']['operations']);success=True
            return {'text':output,'skill_invocation_id':invocation,'skill_id':identifier,'version':row['version'],'source_event_id':row['source_event_id']}
        finally:
            with self.store.connect() as db:
                db.execute('UPDATE procedures SET invoked=invoked+1,failed=failed+?,reused=reused+?,last_used=? WHERE id=? AND version=?',
                    (not success,row['invoked']>0,time.time(),identifier,row['version']))
                self.store.event('skill.invoked' if success else 'skill.failed',task,{'skill_id':identifier,'version':row['version'],'skill_invocation_id':invocation,'success':success},db)
                db.execute('INSERT OR IGNORE INTO graph_edges VALUES(?,?,?)',(f'skill:{identifier}:{row["version"]}',task,'used_by'))

    def rollback(self,identifier,version):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM procedures WHERE id=? AND version=?',(identifier,version)).fetchone()
            if not row or not all(t['passed'] for t in json.loads(row['tests'])) or hashlib.sha256(row['manifest'].encode()).hexdigest()!=row['digest']:
                raise ValueError('Rollback target is missing or unverified')
            db.execute('UPDATE procedures SET active=0 WHERE id=?',(identifier,))
            db.execute('UPDATE procedures SET active=1,archived=0 WHERE id=? AND version=?',(identifier,version))
            self.store.event('forge.rolled_back',identifier,{'version':version},db)
        return {'id':identifier,'version':version,'active':True}

    def archive(self,identifier,version):
        with self.store.connect() as db:
            count=db.execute('UPDATE procedures SET active=0,archived=1 WHERE id=? AND version=?',(identifier,version)).rowcount
            self.store.event('skill.archived',identifier,{'version':version},db)
        return {'archived':bool(count),'recoverable':True}

    def forget(self,identifier):
        with self.store.connect() as db:
            count=db.execute('DELETE FROM procedures WHERE id=?',(identifier,)).rowcount
            ids=[r[0] for r in db.execute("SELECT id FROM candidates WHERE json_extract(manifest,'$.id')=?",(identifier,))]
            for candidate in ids:
                db.execute('DELETE FROM candidates WHERE id=?',(candidate,))
                db.execute('DELETE FROM graph_edges WHERE source=? OR target=?',(candidate,candidate))
            db.execute('DELETE FROM graph_edges WHERE source LIKE ? OR target LIKE ?',('skill:'+identifier+':%','skill:'+identifier+':%'))
            self.store.event('skill.forgotten',identifier,{'versions_removed':count},db)
        return {'removed_versions':count}

    def curator(self):
        rows=self.list()
        return {'skills':[{'id':r['id'],'version':r['version'],'invoked':r['invoked'],'failed':r['failed'],'reused':r['reused'],
                          'last_used':r['last_used'],'stale':r['stale'],'archived':bool(r['archived']),
                          'proposal':'archive_review' if r['stale'] and not r['archived'] else None} for r in rows],
                'automatic_deletion':False,'model_calls':0}
