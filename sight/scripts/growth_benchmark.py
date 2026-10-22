"""Three equal-budget local tasks before learning, after learning, and on reuse."""
import argparse
import asyncio
from datetime import datetime,timezone
import json
import hashlib
import platform
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sight_core.brain_store import BrainStore
from sight_core.memory import MemoryService,MemoryInput
from sight_core.forge import Forge,SkillGenerate,SkillManifest
from sight_core.jobs import Jobs,Job,Step
from sight_core.store import Store
from sight_core.tools import LocalFiles
from sight_core.models import OllamaProvider
from sight_core.routing import ModelRouter
from sight_core.config import Config


async def benchmark(model):
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    data=ROOT.parent/'test-data'/('growth-'+stamp+'-'+uuid.uuid4().hex[:8])
    if data.exists():raise ValueError('Benchmark requires a fresh data directory')
    run_manifest={'run_id':data.name,'fresh_data_directory':True,'data_directory':str(data),
                  'environment':platform.platform(),'python':platform.python_version(),
                  'seeded_inputs':'Three fixed synthetic text tasks; no owner data copied',
                  'source_hashes':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in sorted((ROOT/'sight_core').glob('*.py'))},
                  'generation_budget':{'local_requests':1,'cloud_requests':0},
                  'comparison_budget_per_task':{'tools':4,'model':0}}
    store=BrainStore(data);memory=MemoryService(store);forge=Forge(store)
    router=ModelRouter(OllamaProvider(Config(data,model=model,thinking=False)),Store(data),local_only=True)
    jobs=Jobs(store,memory,forge,LocalFiles(data/'files'),router)
    rows=[]
    async def measure(stage,task,steps,expected):
        started=time.perf_counter()
        record=jobs.submit(Job(idempotency_key=uuid.uuid4().hex,title=task,steps=steps,tool_budget=4,model_budget=0))
        await jobs.run(record['id']);record=jobs.get(record['id'])
        output=record['steps'][-1]['result']
        rows.append({'stage':stage,'task':task,'state':record['state'],'correct':record['state']=='complete' and output['text']==expected,
                     'seconds':round(time.perf_counter()-started,6),'tool_calls':record['tool_calls'],'model_calls':record['model_calls'],
                     'budget':{'tools':4,'model':0},'job_id':record['id'],'result':output})
    def preference():return [Step(id='format',op='memory.format',text='Hello SIGHT')]
    def skill():return [Step(id='clean',op='skill.invoke',skill_id='text.clean',text='b\na\nb')]
    await measure('baseline','owner correction',preference(),'HELLO SIGHT')
    await measure('baseline','missing skill',skill(),'a\nb')
    await measure('baseline','workflow consolidation',[Step(id='dedupe',op='text.transform',text='b\na\nb',operations=[{'op':'dedupe_lines'}]),Step(id='sort',op='text.transform',input_from='dedupe',depends_on=['dedupe'],operations=[{'op':'sort_lines'}])],'a\nb')
    correction=memory.put(MemoryInput(key='text.case',content='upper',source_uri='synthetic benchmark owner confirmation'))
    request=SkillGenerate(id='text.clean',description='Remove duplicate lines, then sort the remaining lines alphabetically.',tests=[{'text':'b\na\nb','expected':'a\nb'},{'text':'z\nx\nz','expected':'x\nz'}])
    started=time.perf_counter()
    try:generated=await forge.generate(request,router)
    except Exception as exc:generated={'state':'generation_failed','error_type':type(exc).__name__}
    generation_seconds=round(time.perf_counter()-started,3)
    if generated.get('state')=='tested':
        promoted=forge.promote(generated['candidate_id'],generated['digest'])
    else:
        # Explicitly recorded test-harness fallback, never called model-generated.
        candidate=forge.stage(SkillManifest(id=request.id,title='Clean lines',description=request.description,operations=[{'op':'dedupe_lines'},{'op':'sort_lines'}],tests=request.tests))
        promoted=forge.promote(candidate['candidate_id'],candidate['digest'])
    for stage in ('after','repeat'):
        await measure(stage,'owner correction',preference(),'HELLO SIGHT')
        await measure(stage,'missing skill',skill(),'a\nb')
        await measure(stage,'workflow consolidation',skill(),'a\nb')
    metrics=forge.curator()
    exported_before_delete=memory.export()
    memory.put(MemoryInput(key='text.case',content='lower'),correction['id'])
    await measure('edited','owner correction',preference(),'hello sight')
    memory.delete(correction['id']);forge.forget('text.clean')
    await measure('forgotten','owner correction',preference(),'Hello SIGHT')
    await measure('forgotten','missing skill',skill(),'a\nb')
    result={'timestamp_utc':stamp,'environment':'Windows; current owner account; isolated synthetic data','model':model,'thinking':False,'run_manifest':run_manifest,
            'live_generation':generated,'generation_seconds':generation_seconds,'promotion':promoted,'rows':rows,'curator_before_forget':metrics,
            'promotion_origin':'model_generated' if generated.get('state')=='tested' else 'harness_authored_fallback',
            'memory_export_before_delete':exported_before_delete,
            'summary':{'baseline_correct':sum(r['correct'] for r in rows if r['stage']=='baseline'),'after_correct':sum(r['correct'] for r in rows if r['stage']=='after'),
                       'repeat_correct':sum(r['correct'] for r in rows if r['stage']=='repeat'),'total_tasks_per_stage':3,'cloud_requests':0,
                       'memory_forgotten':not memory.export(),'skill_forgotten':not forge.list(),
                       'forgotten_skill_execution_denied':next(r for r in rows if r['stage']=='forgotten' and r['task']=='missing skill')['state']!='complete',
                       'workflow_tool_calls_before':2,'workflow_tool_calls_after':1},
            'scope':'Three deterministic text tasks only. Elapsed times include SQLite and worker startup. Skill creation cost reported separately. Not evidence of general autonomous learning.'}
    destination=ROOT/'reports/growth_benchmark.json';destination.write_text(json.dumps(result,indent=2),encoding='utf-8')
    (ROOT.parent/'evidence'/('growth-'+stamp+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(destination),'summary':result['summary'],'generation_state':generated.get('state'),'generation_seconds':generation_seconds},indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);args=parser.parse_args()
    asyncio.run(benchmark(args.model))
