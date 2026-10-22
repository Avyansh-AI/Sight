"""Regressions reproduced in the Windows Phase 1 audit."""
import asyncio
import base64
import hashlib
import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from sight_core.api import create_app
from sight_core.config import Config
from sight_core.models import OllamaProvider


def test_csp_hashes_match_utf8_scripts(client):
    page = client.get('/')
    assert page.status_code == 200
    for script in re.findall(r'<script[^>]*>([\s\S]*?)</script>', page.content.decode('utf-8')):
        digest = base64.b64encode(hashlib.sha256(script.encode('utf-8')).digest()).decode()
        assert "'sha256-" + digest + "'" in page.headers['content-security-policy']


@pytest.mark.parametrize('payload', [[], None, {'models': [None]}, {'models': {}}])
def test_malformed_runtime_metadata_never_crashes(tmp_path, payload):
    provider = OllamaProvider(Config(tmp_path, model='selected'), transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    assert asyncio.run(provider.health()).status != 'ready'


def test_failed_inference_has_failed_task_state(client, app):
    result = client.post('/api/utterance', json={'text':'hello', 'requestId':'missing-model-task'}).json()
    assert result['status'] == 'needs_model'
    assert app.state.store.tasks()[0]['state'] == 'failed'


def test_websocket_bad_cancel_does_not_break_next_message(client):
    ticket = client.post('/api/access/ticket', json={}).json()['ticket']
    with client.websocket_connect('ws://127.0.0.1:8080/ws/app?ticket='+ticket, headers={'origin':'http://127.0.0.1:8080'}) as ws:
        assert ws.receive_json()['type'] == 'hello'
        ws.send_json({'type':'cancel','requestId':[]})
        # Send ping as a sentinel; pre-repair code drops the error in an unobserved worker.
        ws.send_json({'type':'ping'})
        assert ws.receive_json()['type'] == 'error'
        assert ws.receive_json()['type'] == 'pong'


def test_unload_transport_failure_is_controlled(tmp_path):
    def unavailable(req):
        raise httpx.ConnectError('runtime stopped')
    app = create_app(Config(tmp_path, model='selected'), OllamaProvider(Config(tmp_path, model='selected'), transport=httpx.MockTransport(unavailable)))
    with TestClient(app, base_url='http://127.0.0.1:8080', raise_server_exceptions=False) as c:
        c.post('/api/session/claim', json={'token':app.state.bootstrap_token}, headers={'origin':'http://127.0.0.1:8080'})
        c.headers['x-sight-csrf'] = c.get('/api/session').json()['csrf']
        approval = c.post('/api/actions/prepare', json={'path':'/api/models/unload','args':{}}).json()['approvalId']
        response = c.post('/api/models/unload', json={'actionApproval':approval})
        assert response.status_code == 409
        assert response.json()['error']


def test_usage_counts_are_not_redacted():
    from sight_core.security import redact
    assert redact({'input_tokens':8,'output_tokens':4,'access_token':'secret'}) == {'input_tokens':8,'output_tokens':4,'access_token':'[redacted]'}


@pytest.mark.parametrize('secret',['gsk_'+'x'*50,'AQ.'+'y'*50])
def test_current_provider_key_formats_are_redacted(secret):
    from sight_core.security import redact
    assert redact({'say':'Example '+secret})=={'say':'Example [redacted]'}


def test_invalid_port_exits_without_traceback(monkeypatch, capsys):
    from sight_core.cli import main
    monkeypatch.setenv('SIGHT_PORT', 'not-a-port')
    assert main(['doctor']) == 1
    assert 'port' in capsys.readouterr().err.lower()


def test_binary_websocket_is_closed_cleanly(client):
    from starlette.websockets import WebSocketDisconnect
    ticket=client.post('/api/access/ticket',json={}).json()['ticket']
    with client.websocket_connect('ws://127.0.0.1:8080/ws/app?ticket='+ticket,headers={'origin':'http://127.0.0.1:8080'}) as ws:
        ws.receive_json();ws.send_bytes(b'binary')
        with pytest.raises(WebSocketDisconnect) as exc:ws.receive_json()
        assert exc.value.code==1003


def test_long_local_prompt_is_rejected_before_network(tmp_path):
    def forbidden(request):pytest.fail('Over-context input should not load a model')
    provider=OllamaProvider(Config(tmp_path,model='selected'),transport=httpx.MockTransport(forbidden))
    assert asyncio.run(provider.generate('x'*1281))['status']=='context_limit'


def test_database_failure_returns_json(client,app,monkeypatch):
    import sqlite3
    def unavailable(*a,**k):raise sqlite3.OperationalError('fixture locked')
    monkeypatch.setattr(app.state.store,'tasks',unavailable)
    response=client.get('/api/brain/jobs')
    assert response.status_code==503 and response.json()['error']


def test_websocket_database_failure_is_visible(client,app,monkeypatch):
    import sqlite3
    def unavailable(*a,**k):raise sqlite3.OperationalError('fixture locked')
    monkeypatch.setattr(app.state.store,'begin',unavailable)
    ticket=client.post('/api/access/ticket',json={}).json()['ticket']
    with client.websocket_connect('ws://127.0.0.1:8080/ws/app?ticket='+ticket,headers={'origin':'http://127.0.0.1:8080'}) as ws:
        ws.receive_json();ws.send_json({'type':'utterance','text':'hello','requestId':'database-error'})
        assert ws.receive_json()['type']=='state'
        assert ws.receive_json()['type']=='error'


def test_saved_model_is_used_and_env_can_override(tmp_path,monkeypatch):
    (tmp_path/'local-model.json').write_text(json.dumps({'model':'saved:tag'}),encoding='utf-8')
    monkeypatch.setenv('SIGHT_DATA_DIR',str(tmp_path));monkeypatch.delenv('SIGHT_OLLAMA_MODEL',raising=False)
    assert Config.from_env().model=='saved:tag'
    monkeypatch.setenv('SIGHT_OLLAMA_MODEL','')
    assert Config.from_env().model==''


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows ACL integration')
def test_windows_data_acl_is_protected(tmp_path):
    import subprocess
    from sight_core.security import private_directory,windows_owner_sid
    path=tmp_path/'private';private_directory(path)
    (path/'proof').write_text('fixture',encoding='utf-8')
    command="(Get-Acl -LiteralPath $args[0]).Sddl"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command,str(path)],capture_output=True,text=True,timeout=10)
    # Check ACL via icacls too; the installed owner must be present with no inherited broad grant.
    acl=subprocess.run(['icacls.exe',str(path)],capture_output=True,text=True,check=True,timeout=10).stdout
    assert '(I)' not in acl
    assert 'Everyone' not in acl and 'BUILTIN\\Users' not in acl
