"""Real SQLite failure, crash, concurrency and retrieval regressions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3
import subprocess
import sys
import threading
import uuid

import pytest

from sight_core.brain_store import BrainStore
from sight_core.memory import MemoryInput, MemoryService


@pytest.fixture
def memory(tmp_path):
    return MemoryService(BrainStore(tmp_path / 'memory'))


def test_duplicate_compaction_sources_rejected_without_mutation(memory):
    source = memory.put(MemoryInput(key='note', content='quartz'))
    events = memory.store.events()
    with pytest.raises(ValueError, match='distinct'):
        memory.compact([source['id'], source['id']])
    assert memory.export() == [source]
    assert memory.store.events() == events


def test_compaction_graph_failure_rolls_back_summary_fts_and_event(memory):
    source = memory.put(MemoryInput(key='note', content='quartz'))
    events = memory.store.events()
    with memory.store.connect() as db:
        db.execute("""CREATE TRIGGER reject_graph BEFORE INSERT ON graph_edges
                      BEGIN SELECT RAISE(ABORT, 'injected graph failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='injected graph failure'):
        memory.compact([source['id']])
    assert memory.store.events() == events
    assert memory.export() == memory.search('quartz') == [source]
    memory.delete(source['id'])
    assert memory.export() == memory.search('quartz') == []


def test_process_crash_during_compaction_leaves_no_orphan(memory):
    source = memory.put(MemoryInput(key='note', content='quartz'))
    events = memory.store.events()
    code = '''import os, sys
from contextlib import contextmanager
from sight_core.brain_store import BrainStore
from sight_core.memory import MemoryService
store = BrainStore(sys.argv[1])
original = store.connect
@contextmanager
def fault_connection():
    with original() as db:
        db.create_function('crash_now', 0, lambda: os._exit(88))
        db.execute("CREATE TEMP TRIGGER crash_graph BEFORE INSERT ON graph_edges BEGIN SELECT crash_now(); END")
        yield db
store.connect = fault_connection
MemoryService(store).compact([sys.argv[2]])
'''
    result = subprocess.run([sys.executable, '-c', code, str(memory.store.root), source['id']],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 88, result.stderr
    assert memory.export() == memory.search('quartz') == [source]
    assert memory.store.events() == events
    memory.delete(source['id'])
    assert not memory.export()


def test_compaction_is_not_visible_before_source_links_commit(memory, monkeypatch):
    source = memory.put(MemoryInput(key='note', content='quartz'))
    entered, release = threading.Event(), threading.Event()
    original = memory.store.connect

    def pause():
        entered.set()
        if not release.wait(5):
            raise RuntimeError('test barrier timed out')
        return 0

    @contextmanager
    def connection():
        with original() as db:
            db.create_function('pause_graph', 0, pause)
            db.execute("""CREATE TEMP TRIGGER pause_graph BEFORE INSERT ON graph_edges
                          BEGIN SELECT pause_graph(); END""")
            yield db

    monkeypatch.setattr(memory.store, 'connect', connection)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(memory.compact, [source['id']])
        try:
            assert entered.wait(5)
            with original() as db:
                visible = [r[0] for r in db.execute('SELECT id FROM episodes')]
                indexed = [r[0] for r in db.execute("SELECT id FROM memory_fts WHERE store='episode'")]
        finally:
            release.set()
        summary = pending.result(timeout=10)
    assert visible == indexed == []
    assert memory.get(summary['id'])
    memory.put(MemoryInput(key='note', content='jade'), source['id'])
    assert memory.get(summary['id']) is None


@pytest.mark.parametrize('hidden', ['expired', 'private', 'expired_ancestor'])
def test_hidden_matches_do_not_consume_search_limit(memory, hidden):
    now = 1_000_000
    memory.clock = lambda: now
    source = memory.put(MemoryInput(store='episode', key='hidden', content='quartz ' * 30,
                                   ttl_days=None if hidden == 'private' else 1))
    if hidden == 'expired_ancestor':
        memory.compact([source['id']])
    visible = memory.put(MemoryInput(store='document', key='visible', privacy_scope='cloud_allowed',
                                    content='quartz ' + 'other ' * 100))
    now += 86401
    rows = memory.search('quartz', limit=1, remote=hidden == 'private')
    assert [r['id'] for r in rows] == [visible['id']]
    assert rows[0]['store'] == 'document'


def test_deep_summary_lineage_is_readable_and_forgettable(memory):
    source = memory.put(MemoryInput(key='note', content='quartz'))
    previous = source['id']
    # A restored legitimate long-lived store can exceed Python's recursion limit.
    with memory.store.connect() as db:
        for _ in range(1100):
            identifier = str(uuid.uuid4())
            db.execute("""INSERT INTO episodes SELECT ?,owner_id,project_id,'compaction',content,
                          created_at,last_confirmed_at,source_event_id,'extractive_compaction',
                          confidence,expiry,privacy_scope,revision FROM profiles WHERE id=?""",
                       (identifier, source['id']))
            db.execute('INSERT INTO memory_fts VALUES(?,?,?,?)', (identifier, 'episode', 'default', 'quartz'))
            db.execute('INSERT INTO graph_edges VALUES(?,?,?)', (previous, identifier, 'summarized_into'))
            previous = identifier
    assert memory.get(previous)['content'] == 'quartz'
    assert len(memory.export()) == 1101
    assert memory.delete(source['id'])['derived_removed'] == 1100
    assert memory.export() == memory.search('quartz') == []


def test_cyclic_summary_lineage_is_unavailable_without_recursion_error(memory):
    source = memory.put(MemoryInput(key='note', content='quartz'))
    summary = memory.compact([source['id']])
    with memory.store.connect() as db:
        db.execute('INSERT INTO graph_edges VALUES(?,?,?)', (summary['id'], source['id'], 'summarized_into'))
    assert memory.get(summary['id']) is None
    assert memory.export() == memory.search('quartz') == []


def test_compaction_privacy_and_transitive_expiry(memory):
    now = 1_000_000
    memory.clock = lambda: now
    local = memory.put(MemoryInput(key='local', content='quartz', ttl_days=1))
    public = memory.put(MemoryInput(key='public', content='cobalt', privacy_scope='cloud_allowed'))
    summary = memory.compact([local['id'], public['id']])
    descendant = memory.compact([summary['id']])
    assert summary['privacy_scope'] == descendant['privacy_scope'] == 'local'
    assert not memory.search('quartz', remote=True)
    now += 86401
    assert memory.get(summary['id']) is memory.get(descendant['id']) is None
    assert memory.export() == [public]


def test_compaction_rejects_cross_project_without_mutation(memory):
    source = memory.put(MemoryInput(key='note', content='quartz', project_id='other'))
    events = memory.store.events()
    with pytest.raises(ValueError, match='cross-project'):
        memory.compact([source['id']])
    assert memory.export() == [source]
    assert memory.store.events() == events


def test_legacy_orphan_summary_is_preserved_but_not_retrieved(memory):
    source = memory.put(MemoryInput(key='note', content='quartz'))
    summary = memory.compact([source['id']])
    with memory.store.connect() as db:
        db.execute('DELETE FROM graph_edges')
    assert memory.get(summary['id']) is None
    assert memory.search('quartz') == memory.export() == [source]
    with memory.store.connect() as db:
        assert db.execute('SELECT content FROM episodes WHERE id=?', (summary['id'],)).fetchone()[0] == summary['content']


def test_concurrent_source_privacy_correction_removes_committed_summary(memory, monkeypatch):
    source = memory.put(MemoryInput(key='note', content='quartz', privacy_scope='cloud_allowed'))
    entered, release, editing = threading.Event(), threading.Event(), threading.Event()
    original = memory.store.connect

    def pause():
        entered.set()
        if not release.wait(5):
            raise RuntimeError('test barrier timed out')
        return 0

    @contextmanager
    def connection():
        with original() as db:
            db.create_function('pause_graph', 0, pause)
            db.execute("CREATE TEMP TRIGGER pause_graph BEFORE INSERT ON graph_edges BEGIN SELECT pause_graph(); END")
            yield db

    def correct():
        editing.set()
        return memory.put(MemoryInput(key='note', content='jade', privacy_scope='local'), source['id'])

    monkeypatch.setattr(memory.store, 'connect', connection)
    with ThreadPoolExecutor(max_workers=2) as executor:
        compact = executor.submit(memory.compact, [source['id']])
        try:
            assert entered.wait(5)
            edit = executor.submit(correct)
            assert editing.wait(5)
            assert not edit.done()
        finally:
            release.set()
        summary, corrected = compact.result(timeout=10), edit.result(timeout=10)
    assert memory.get(summary['id']) is None
    assert memory.search('quartz', remote=True) == []
    assert memory.export() == [corrected]


def test_compaction_api_approval_duplicates_and_forgetting(client):
    def invoke(operation, args):
        path = '/api/learning/memory/' + operation
        prepared = client.post('/api/actions/prepare', json={'path': path, 'args': args})
        assert prepared.status_code == 200, prepared.text
        grant = prepared.json()
        return client.post(path, json=grant['args'] | {'actionApproval': grant['approvalId']})

    source = invoke('save', {'key': 'note', 'content': 'quartz'}).json()
    assert client.post('/api/learning/memory/compact', json={'ids': [source['id']]}).status_code == 403
    assert invoke('compact', {'ids': [source['id'], source['id']]}).status_code == 409
    assert client.get('/api/learning/memory').json()['items'] == [source]
    response = invoke('compact', {'ids': [source['id']]})
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary['sources'] == [source['source_link']]
    assert len(client.get('/api/learning/memory', params={'q': 'quartz'}).json()['items']) == 2
    assert invoke('delete', {'id': source['id']}).json()['derived_removed'] == 1
    assert client.get('/api/learning/memory/' + summary['id']).status_code == 404
    assert client.get('/api/learning/export').json()['memory'] == []
