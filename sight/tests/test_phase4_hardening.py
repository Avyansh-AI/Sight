"""Phase 4 regressions: disposable paths and synthetic loopback responses only."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import httpx
import pytest

from sight_core.api import create_app
from sight_core.brain_store import BrainStore
from sight_core.config import Config
from sight_core.models import OllamaProvider
from sight_core.releases import Releases
from sight_core.store import Store


def test_launch_token_hardlink_does_not_truncate_other_file(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    sentinel = tmp_path / 'owner-file.txt'
    sentinel.write_text('preserve owner data')
    os.link(sentinel, data / 'browser-token')
    try:
        with pytest.raises(ValueError, match='link'):
            create_app(Config(data))
    finally:
        assert sentinel.read_text() == 'preserve owner data'


@pytest.mark.parametrize('factory,name', [(Store, 'sight.sqlite3'), (BrainStore, 'brain.sqlite3')])
def test_database_hardlink_rejected_before_migration(tmp_path, factory, name):
    data = tmp_path / 'data'
    data.mkdir()
    sentinel = tmp_path / 'owner.sqlite3'
    with sqlite3.connect(sentinel) as db:
        db.execute('CREATE TABLE owner_data(value TEXT)')
    before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    os.link(sentinel, data / name)
    try:
        with pytest.raises(ValueError, match='link'):
            factory(data)
    finally:
        assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == before


def test_release_rejects_unmanifested_bytecode(tmp_path):
    releases = Releases(tmp_path / 'data')
    snapshot = releases.snapshot()
    cache = releases.root / snapshot['id'] / 'sight_core/__pycache__'
    cache.mkdir()
    (cache / 'api.cpython-312.pyc').write_bytes(b'unverified executable bytecode')
    with pytest.raises(ValueError, match='unmanifested|bytecode'):
        releases.verify(snapshot['id'])


@pytest.mark.parametrize('payload', [[], None, {'id': 'bad'}, {'files': []}])
def test_release_invalid_manifest_is_controlled(tmp_path, payload):
    releases = Releases(tmp_path / 'data')
    snapshot = releases.snapshot()
    (releases.root / snapshot['id'] / 'manifest.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        releases.verify(snapshot['id'])


@pytest.mark.parametrize('endpoint', ['/api/tags', '/api/show', '/api/chat'])
def test_local_runtime_response_read_is_bounded(tmp_path, endpoint):
    consumed = []
    class Oversized(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index in range(40):
                consumed.append(index)
                yield b' ' * 65536
    def respond(request):
        if request.url.path == endpoint:
            return httpx.Response(200, stream=Oversized())
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'test', 'size': 100, 'details': {'family': 'gemma4', 'quantization_level': 'Q4_K_M'}}]})
        return httpx.Response(200, json={'model_info': {'name': 'gemma4 e4b'}})
    provider = OllamaProvider(Config(tmp_path, model='test'), transport=httpx.MockTransport(respond))
    result = asyncio.run(provider.generate('Synthetic test'))
    assert result['status'] != 'ok'
    assert len(consumed) <= 17, 'Read continued beyond the 1 MiB response bound'


@pytest.mark.parametrize('suffix', ['-journal','-wal','-shm'])
def test_sqlite_sidecar_hardlinks_rejected(tmp_path, suffix):
    data=tmp_path/'data';Store(data)
    sentinel=tmp_path/'owner.txt';sentinel.write_text('preserve')
    os.link(sentinel,data/('sight.sqlite3'+suffix))
    with pytest.raises(ValueError,match='link'):Store(data)
    assert sentinel.read_text()=='preserve'


def test_windows_junction_ancestor_rejected_before_resolution(tmp_path,monkeypatch):
    if os.name != 'nt':pytest.skip('Windows junction regression')
    import _winapi
    from sight_core.security import private_directory
    real=tmp_path/'real';real.mkdir();junction=tmp_path/'redirect'
    _winapi.CreateJunction(str(real),str(junction))
    try:
        with pytest.raises(ValueError,match='link'):private_directory(junction/'child')
        monkeypatch.setenv('SIGHT_DATA_DIR',str(junction/'data'))
        with pytest.raises(ValueError,match='link'):Config.from_env()
        assert not list(real.iterdir())
    finally:
        # Remove only this junction entry, never recursively delete its target.
        assert junction.is_junction() and junction.parent==tmp_path
        os.rmdir(junction)


def test_corrupt_core_database_is_preserved(tmp_path):
    data=tmp_path/'data';data.mkdir();path=data/'sight.sqlite3'
    path.write_bytes(b'corrupt but preserve me')
    with pytest.raises(sqlite3.DatabaseError):Store(data)
    assert path.read_bytes()==b'corrupt but preserve me'


@pytest.mark.parametrize('supported,owner_setting,expected', [(True,None,True),(True,False,False),(False,None,False)])
def test_gemma_reasoning_mode_has_context_and_output_budget(tmp_path,supported,owner_setting,expected):
    from sight_core.models import ModelStatus
    requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'message':{'thinking':'synthetic private trace','content':'42'},'done':True,'done_reason':'stop'})
    provider=OllamaProvider(Config(tmp_path,model='test',thinking=owner_setting),transport=httpx.MockTransport(respond))
    async def health():return ModelStatus('ready','fixture',supports_thinking=supported)
    provider._metadata_health=health
    result=asyncio.run(provider.generate('What is 17 plus 25?'))
    assert result['status']=='ok' and result['say']=='42'
    assert 'synthetic private trace' not in json.dumps(result)
    payload=requests[0]
    assert payload['think'] is expected and payload['options']['num_ctx']==4096 and payload['options']['use_mmap'] is True
    assert payload['options']['num_predict']==(1536 if expected else 512)
    assert payload['options']['temperature']==.7 and payload['options']['repeat_penalty']==1.1
    assert 'professional language' in payload['messages'][0]['content']


@pytest.mark.parametrize('body,status', [
    ({'message':{'content':'partly answered'},'done_reason':'length'},'output_limit'),
    ({'message':{'thinking':'unfinished'},'done_reason':'length'},'output_limit'),
    ({'message':{'content':'<|channel>thought\nprivate'}},'model_error')])
def test_gemma_incomplete_or_unparsed_output_is_not_success(tmp_path,body,status):
    from sight_core.models import ModelStatus
    provider=OllamaProvider(Config(tmp_path,model='test'),transport=httpx.MockTransport(lambda r:httpx.Response(200,json=body)))
    async def health():return ModelStatus('ready','fixture',supports_thinking=True)
    provider._metadata_health=health
    result=asyncio.run(provider.generate('synthetic'))
    assert result['status']==status and 'partly answered' not in result['say'] and 'private' not in result['say']


def test_expired_mcp_sessions_do_not_exhaust_capacity(client,app):
    bridge=app.state.capabilities.mcp
    bridge.sessions={f'expired-{i}':'ready' for i in range(256)}
    response=client.post('/api/mcp',json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}})
    assert 'result' in response.json() and len(bridge.sessions)==1


@pytest.mark.parametrize('factory',[Store,BrainStore])
def test_legacy_backup_checksum_link_cannot_overwrite_owner_file(tmp_path,factory):
    store=factory(tmp_path/'data');sentinel=tmp_path/'owner.txt';sentinel.write_text('preserve')
    os.link(sentinel,tmp_path/'backup.db.sha256')
    with pytest.raises(ValueError,match='link'):store.backup(tmp_path/'backup.db')
    assert sentinel.read_text()=='preserve' and not (tmp_path/'backup.db').exists()


def test_uvicorn_websocket_log_redacts_ticket_even_without_access_log(app):
    import logging
    logger = logging.getLogger('uvicorn.error')
    record = logging.LogRecord(logger.name, logging.INFO, __file__, 1,
                               '%s - "WebSocket %s" [accepted]',
                               ('127.0.0.1:1234', '/ws/app?ticket=synthetic-private-ticket&state=ok'), None)
    assert logger.filter(record)
    assert 'synthetic-private-ticket' not in record.getMessage()
    assert 'state=ok' in record.getMessage()


@pytest.mark.parametrize('second_answer,expected', [('42', 'ok'), ('', 'model_error')])
def test_gemma_thinking_only_stop_gets_one_bounded_same_model_retry(tmp_path, second_answer, expected):
    from sight_core.models import ModelStatus
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'message': {
            'content': '' if len(requests) == 1 else second_answer,
            'thinking': 'private synthetic reasoning' if len(requests) == 1 else ''},
            'done': True, 'done_reason': 'stop', 'prompt_eval_count': 20, 'eval_count': 10})
    provider = OllamaProvider(Config(tmp_path, model='uncensored'), transport=httpx.MockTransport(respond))
    async def health(): return ModelStatus('ready', 'fixture', supports_thinking=True)
    provider._metadata_health = health
    result = asyncio.run(provider.generate_chat('17 plus 25'))
    assert result['status'] == expected and len(requests) == 2
    assert requests[0]['think'] is True and requests[1]['think'] is False
    assert requests[0]['model'] == requests[1]['model'] == 'uncensored'
    assert requests[1]['options']['num_predict'] == 512
    assert 'private synthetic reasoning' not in json.dumps(result)
    if expected == 'ok':
        assert result['recovery'] == 'empty_thinking_answer'
        assert result['usage'] == {'input_tokens': 40, 'output_tokens': 20}


@pytest.mark.parametrize('body', [
    {'message': {'thinking': 'private'}, 'done': True, 'done_reason': 'length'},
    {'message': {'content': 'valid answer'}, 'done': True, 'done_reason': 'stop'},
    {'message': {}, 'done': True, 'done_reason': 'stop'},
])
def test_gemma_other_responses_do_not_trigger_blank_answer_retry(tmp_path, body):
    from sight_core.models import ModelStatus
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=body)
    provider = OllamaProvider(Config(tmp_path, model='test'), transport=httpx.MockTransport(respond))
    async def health(): return ModelStatus('ready', 'fixture', supports_thinking=True)
    provider._metadata_health = health
    asyncio.run(provider.generate_chat('synthetic'))
    assert len(calls) == 1


def test_durable_model_and_structured_calls_never_retry_empty_thinking(tmp_path):
    from sight_core.models import ModelStatus
    from sight_core.routing import ModelRouter
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={'message': {'thinking': 'synthetic', 'content': ''},
                                        'done': True, 'done_reason': 'stop'})
    provider = OllamaProvider(Config(tmp_path, model='test'), transport=httpx.MockTransport(respond))
    async def health(): return ModelStatus('ready', 'fixture', supports_thinking=True)
    provider._metadata_health = health
    router = ModelRouter(provider, Store(tmp_path), local_only=True)
    async def run():
        first = await router.generate('ordinary budgeted invocation')
        second = await router.generate('structured invocation', json_schema={'type': 'object'}, recover_empty=True)
        return first, second
    result = asyncio.run(run())
    assert all(row['status'] == 'model_error' for row in result) and len(calls) == 2


def test_sqlite_journal_creation_deletion_is_safe_during_path_validation(tmp_path):
    import threading
    from sight_core.security import safe_database
    database = tmp_path/'sight.sqlite3'
    database.write_bytes(b'synthetic main file')
    journal = tmp_path/'sight.sqlite3-journal'
    stop = threading.Event()
    errors = []
    def rotate():
        while not stop.is_set():
            journal.write_bytes(b'transient rollback journal')
            journal.unlink()
    worker = threading.Thread(target=rotate)
    worker.start()
    try:
        for _ in range(500):
            try:
                safe_database(database)
            except (OSError, ValueError) as exc:
                errors.append(type(exc).__name__)
    finally:
        stop.set()
        worker.join(3)
    assert not worker.is_alive()
    assert not errors, errors[:10]
    assert database.read_bytes() == b'synthetic main file'
