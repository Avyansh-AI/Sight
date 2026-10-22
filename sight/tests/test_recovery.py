import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from sight_core.api import create_app
from sight_core.artifacts import Artifacts
from sight_core.brain_store import BrainStore
from sight_core.cli import single_instance
from sight_core.config import Config
from sight_core.forge import Forge, SkillManifest
from sight_core.jobs import Job, Jobs, Step
from sight_core.memory import MemoryInput, MemoryService
from sight_core.proactive import Proactive, Reminder
from sight_core.recovery import backup_all, restore_all
from sight_core.store import Store
from sight_core.tools import LocalFiles


@pytest.fixture
def seeded(tmp_path):
    data = tmp_path / 'owner'
    core = Store(data)
    brain = BrainStore(data)
    memory, forge = MemoryService(brain), Forge(brain)
    item = memory.put(MemoryInput(key='favorite', content='indigo'))
    candidate = forge.stage(SkillManifest(id='text.upper', title='Uppercase', operations=[{'op':'upper'}], tests=[{'text':'ab','expected':'AB'},{'text':'cd','expected':'CD'}]))
    forge.promote(candidate['candidate_id'], candidate['digest'])
    jobs = Jobs(brain, memory, forge, LocalFiles(data / 'files'), None)
    done = jobs.submit(Job(idempotency_key='backup-complete',title='Completed write',steps=[Step(id='write',op='file.write',name='kept.txt',text='keep this')]))
    asyncio.run(jobs.run(done['id']))
    assert jobs.get(done['id'])['state'] == 'complete'
    pending = jobs.submit(Job(idempotency_key='backup-pending', title='Pending task',steps=[Step(id='later',op='memory.format',text='hello')]))
    artifact = Artifacts(data).put('retained artifact', 'txt')
    proactive = Proactive(core)
    proactive.add(Reminder(id='backup-reminder',title='Retained reminder',due=datetime.now(timezone.utc)))
    proactive.tick()
    core.set_setting('provider.groq', {'enabled':True,'free_only':True})
    core.set_setting('chatgpt.policy', {'enabled':True})
    core.set_setting('usage.synthetic', {'requests':3})
    core.prepare('old-session', '/api/files/write', {'name':'file.txt'})
    (data / 'browser-token').write_text('old synthetic launch proof')
    return data, item, artifact, done['id'], pending['id']


def test_memory_backup_restore_full_data_and_safe_start(seeded, tmp_path):
    data, item, artifact, completed, pending = seeded
    bundle, restored = tmp_path / 'bundle', tmp_path / 'restored'
    assert backup_all(data, bundle)['files'] == 4
    assert not (bundle / 'browser-token').exists()
    restore_all(bundle, restored)
    core, brain = Store(restored), BrainStore(restored)
    assert MemoryService(brain).get(item['id'])['content'] == 'indigo'
    assert Forge(brain).invoke('text.upper', 'hello')['text'] == 'HELLO'
    assert (restored / 'files/kept.txt').read_text() == 'keep this'
    assert hashlib.sha256((restored / 'artifacts' / artifact['id']).read_bytes()).hexdigest() == artifact['sha256']
    assert not core.setting('provider.groq')['enabled'] and not core.setting('chatgpt.policy')['enabled']
    assert core.setting('usage.synthetic')['requests'] == 3
    with core.connect() as db:assert db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0] == 0
    assert len(Proactive(core).notifications()) == 1
    app = create_app(Config(restored), local_only=True)
    with TestClient(app,base_url='http://127.0.0.1:8080') as client:
        assert client.get('/').status_code == 200
        assert app.state.learning.jobs.get(completed)['state'] == 'complete'
        assert app.state.learning.jobs.get(pending)['state'] == 'needs_review'
        assert Proactive(core).tick()['emitted'] == 0
    with pytest.raises(ValueError,match='new directory'):restore_all(bundle, restored)


def test_backup_refuses_running_server_lock(seeded, tmp_path):
    with single_instance(seeded[0]):
        with pytest.raises(RuntimeError, match='Another SIGHT'):
            backup_all(seeded[0], tmp_path / 'bundle')
    assert not (tmp_path / 'bundle').exists()


def test_backup_tampering_rejected_before_destination_created(seeded,tmp_path):
    bundle=tmp_path/'bundle';backup_all(seeded[0],bundle)
    (bundle/'files/kept.txt').write_text('tampered')
    with pytest.raises(ValueError,match='hash'):restore_all(bundle,tmp_path/'restored')
    assert not (tmp_path/'restored').exists()


@pytest.mark.parametrize('name', ['../escape','files/../../escape','files\\escape','C:/escape','files/a:b'])
def test_recovery_traversal_denied(seeded,tmp_path,name):
    bundle=tmp_path/'bundle';backup_all(seeded[0],bundle)
    manifest=json.loads((bundle/'manifest.json').read_text())
    manifest['files'][name]={'sha256':'0'*64,'bytes':0}
    content=json.dumps(manifest).encode();(bundle/'manifest.json').write_bytes(content)
    (bundle/'manifest.sha256').write_text(hashlib.sha256(content).hexdigest())
    with pytest.raises(ValueError,match='entry'):restore_all(bundle,tmp_path/'restored')
    assert not (tmp_path/'restored').exists()


def test_skill_curator_archive_restore_and_owner_delete(seeded):
    brain=BrainStore(seeded[0]);forge=Forge(brain);memory=MemoryService(brain)
    with brain.connect() as db:db.execute('UPDATE procedures SET created_at=0,last_used=NULL')
    assert forge.curator()['skills'][0]['proposal']=='archive_review'
    assert forge.archive('text.upper',1)['archived']
    with pytest.raises(ValueError,match='archived'):forge.invoke('text.upper','a')
    forge.rollback('text.upper',1)
    assert forge.invoke('text.upper','a')['text']=='A'
    assert memory.export()[0]['content']=='indigo'
    memory.delete(seeded[1]['id']);forge.forget('text.upper')
    assert not memory.export() and not memory.search('indigo') and not forge.list()
