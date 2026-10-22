import asyncio
import base64
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import httpx
import pytest
from starlette.websockets import WebSocketDisconnect

from sight_core.api import create_app
from sight_core.config import Config
from sight_core.models import OllamaProvider
from sight_core.security import Sessions, Vault, redact
from sight_core.store import Store, restore_backup
from sight_core.tools import LocalFiles


def test_local_first_boot(client, monkeypatch):
    # Outbound transport fails if the app attempts one; no credentials are set.
    def denied(*a, **k):
        raise AssertionError("Unexpected network access")
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)
    health = client.get("/api/health").json()
    assert health["ok"] and not health["cloud_enabled"]
    result = client.post("/api/utterance", json={"text": "Hello", "requestId": "offline-test"})
    assert result.status_code == 200
    assert result.json()["status"] == "needs_model"
    assert "SIGHT_OLLAMA_MODEL" in result.json()["say"]
    assert client.get("/api/ready").status_code == 503


@pytest.mark.parametrize("path", ["/", "/index.html", "/systems.html", "/tasks.html", "/vision.html", "/sw.js", "/api/status", "/api/health", "/api/speech", "/api/weather", "/api/home/devices", "/api/activity?n=8", "/api/settings", "/api/proactive", "/api/capabilities", "/api/models", "/api/brain/jobs", "/api/learning/status"])
def test_html_route_compatibility(client, path):
    result = client.get(path)
    assert result.status_code == 200
    if path.startswith("/api/"):
        assert result.json() is not None


@pytest.mark.parametrize("path,body,expected", [
    ("/api/voiceprint/verify", {}, 409),
    ("/api/schedule/snooze", {"id": "absent", "minutes": 10}, 409),
    ("/api/speech/synthesize", {"text": "hi"}, 503),
    ("/api/speech/transcribe", {"audio": base64.b64encode(b"RIFFtest").decode(), "mimeType": "audio/wav"}, 503),
    ("/api/brain/jobs/abc/verify", {"verifyToken": "untrusted"}, 403),
])
def test_unavailable_routes_degrade_truthfully(client, path, body, expected):
    result = client.post(path, json=body)
    assert result.status_code == expected
    assert result.json()["error"]


def test_voice_consent_toggle(client):
    speech = client.get("/api/speech").json()
    assert not speech["micEnabled"] and not speech["wake"]["enabled"]
    assert "microphone=()" in client.get("/").headers["permissions-policy"]
    assert client.get("/api/voiceprint/challenge").status_code == 409
    assert client.post("/api/settings", json={"micEnabled": True}).status_code == 422


def test_sos_is_local_and_explicit(client):
    alert = client.post("/api/sos", json={}).json()
    assert alert["localOnly"] and alert["contactsNotified"] is False
    assert "No call or message" in alert["message"]
    result = client.post("/api/utterance", json={"text": "cancel the sos", "requestId": "cancel-sos-request"}).json()
    assert result["status"] == "ok"


def test_owner_session_requires_os_launch_proof(app):
    with TestClient(app, base_url="http://127.0.0.1:8080") as c:
        assert c.get("/").status_code == 200
        assert c.get("/api/status").status_code == 401
        assert c.post("/api/session/claim", json={"token": "wrong"}, headers={"origin": "http://127.0.0.1:8080"}).status_code == 403
        assert c.post("/api/session/claim", json={"token": app.state.bootstrap_token}, headers={"origin": "https://untrusted.test"}).status_code == 403
        assert c.post("/api/session/claim", json={"token": app.state.bootstrap_token}, headers={"origin": "http://127.0.0.1:8080"}).status_code == 200
        cookie = c.cookies.get("sight_session")
        assert cookie and "httponly" in c.post("/api/session/claim", json={"token": app.state.bootstrap_token}, headers={"origin": "http://127.0.0.1:8080"}).headers["set-cookie"].lower()


def test_cross_origin_csrf_and_host_denial(client):
    assert client.get("/api/status", headers={"host": "attacker.test"}).status_code == 403
    assert client.get("/api/status", headers={"origin": "http://attacker.test"}).status_code == 403
    assert client.get("/api/status", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.post("/api/utterance", json={"text": "hi"}, headers={"x-sight-csrf": "wrong"}).status_code == 403
    assert client.post("/api/utterance", json={"text": "hi", "user": "other-owner"}).status_code == 422
    assert client.post("/api/utterance", json={"text": "hi", "verifyToken": "fake"}).status_code == 422
    assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]


def test_payload_size_and_audio_validation(client):
    assert client.post("/api/utterance", json={"text": "x" * 120_000}).status_code == 413
    assert client.post("/api/speech/transcribe", json={"audio": "!!!", "mimeType": "audio/wav"}).status_code == 422
    assert client.post("/api/speech/transcribe", json={"audio": "", "mimeType": "application/x-executable"}).status_code == 422
    assert client.post("/api/utterance", content='{"text":"hi"}', headers={"content-type": "text/plain"}).status_code == 415


def test_scoped_approval_replay(client):
    args = {"name": "approved.txt", "content": "hello"}
    review = client.post("/api/actions/prepare", json={"path": "/api/tools/files/write", "args": args})
    assert review.status_code == 200
    token = review.json()["approvalId"]
    assert client.post("/api/tools/files/write", json=args).status_code == 403
    assert client.post("/api/tools/files/write", json=args | {"content": "tampered", "actionApproval": token}).status_code == 403
    assert client.post("/api/tools/files/write", json=args | {"actionApproval": token}).status_code == 200
    assert client.get("/api/tools/files/read", params={"name": "approved.txt"}).json()["content"] == "hello"
    assert client.post("/api/tools/files/write", json=args | {"actionApproval": token}).status_code == 403
    assert client.post("/api/actions/prepare", json={"path": "/api/arbitrary-shell", "args": {}}).status_code == 403


def test_grant_is_bound_to_session(client, app):
    args = {"name": "session.txt", "content": "test"}
    review = client.post("/api/actions/prepare", json={"path": "/api/tools/files/write", "args": args}).json()
    client.cookies.clear()
    client.post("/api/session/claim", json={"token": app.state.bootstrap_token}, headers={"origin": "http://127.0.0.1:8080"})
    client.headers["x-sight-csrf"] = client.get("/api/session").json()["csrf"]
    assert client.post("/api/tools/files/write", json=args | {"actionApproval": review["approvalId"]}).status_code == 403


def test_approval_expiration(client, app):
    args = {"name": "expired.txt", "content": "test"}
    review = client.post("/api/actions/prepare", json={"path": "/api/tools/files/write", "args": args}).json()
    with app.state.store.connect() as db:
        db.execute("UPDATE approvals SET expires=0")
    assert client.post("/api/tools/files/write", json=args | {"actionApproval": review["approvalId"]}).status_code == 403


@pytest.mark.parametrize("name", ["../secrets.txt", "/etc/passwd", "C:\\secrets.txt", ".env", "foo.txt:stream", "CON.txt", "run.ps1", "nested/file.txt", "x;command.txt", "a\u0000.txt"])
def test_file_workspace_boundaries(tmp_path, name):
    files = LocalFiles(tmp_path / "files")
    with pytest.raises(ValueError):
        files.write_new(name, "untrusted")
    assert not files.list()


def test_file_no_overwrite_or_symlink_escape(tmp_path):
    files = LocalFiles(tmp_path / "files")
    files.write_new("safe.txt", "first")
    with pytest.raises(FileExistsError):
        files.write_new("safe.txt", "second")
    assert files.read("safe.txt") == "first"
    secret = tmp_path / "secret.txt"
    secret.write_text("owner data")
    if os.name == "nt":
        # File hard links are available to ordinary Windows users; file symlinks
        # require Developer Mode/privileges which this installer never enables.
        os.link(secret, files.root / "link.txt")
    else:
        (files.root / "link.txt").symlink_to(secret)
    with pytest.raises(ValueError):
        files.read("link.txt")
    assert "link.txt" not in files.list()


def test_desktop_requires_authorization(client):
    assert client.post("/api/tools/desktop", json={"action": "clipboard.read", "application": ""}).status_code == 403
    assert client.post("/api/actions/prepare", json={"path": "/api/tools/desktop", "args": {"action": "app.launch", "application": "powershell -c anything"}}).status_code == 422


def test_idempotent_chat_and_conflicting_key(client, app):
    body = {"text": "help", "requestId": "one-request-only"}
    first = client.post("/api/utterance", json=body).json()
    assert client.post("/api/utterance", json=body).json() == first
    assert client.post("/api/utterance", json=body | {"text": "different"}).status_code == 409
    assert len(app.state.store.tasks()) == 1


def test_restart_never_replays_interrupted_chat(tmp_path):
    root = tmp_path / "data"
    store = Store(root)
    record, created = store.begin("interrupted-key", "original text")
    assert created
    # Opening the DB for backup or doctor must not alter a running request.
    assert Store(root).tasks()[0]["state"] == "running"
    app = create_app(Config(root))
    with TestClient(app, base_url="http://127.0.0.1:8080") as client:
        client.post("/api/session/claim", json={"token": app.state.bootstrap_token}, headers={"origin": "http://127.0.0.1:8080"})
        proof = client.get("/api/session").json()["csrf"]
        result = client.post("/api/utterance", json={"text": "original text", "requestId": "interrupted-key"}, headers={"x-sight-csrf": proof})
        assert result.json()["status"] == "interrupted"
        assert result.json()["taskId"] == record["task"]
        assert len(store.tasks()) == 1


def test_websocket_ticket_replay_and_messages(client):
    ticket = client.post("/api/access/ticket", json={"user": "default"}).json()["ticket"]
    with client.websocket_connect("ws://127.0.0.1:8080/ws/app?ticket=" + ticket, headers={"origin": "http://127.0.0.1:8080"}) as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_json({"type": "utterance", "text": "help", "requestId": "ws-chat-request"})
        assert ws.receive_json()["state"] == "thinking"
        reply = ws.receive_json()
        assert reply["type"] == "response" and reply["requestId"] == "ws-chat-request"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.send_json({"type": "utterance", "text": "help", "requestId": "other-user-request", "user": "other"})
        assert ws.receive_json()["type"] == "error"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1:8080/ws/app?ticket=" + ticket, headers={"origin": "http://127.0.0.1:8080"}):
            pass


def test_ticket_expiration_and_wrong_session():
    now = [0]
    sessions = Sessions(clock=lambda: now[0])
    first, second = sessions.create(), sessions.create()
    ticket = sessions.ticket(first)
    assert not sessions.consume(ticket, second)
    ticket = sessions.ticket(first)
    now[0] = 31
    assert not sessions.consume(ticket, first)


def test_secrets_do_not_leak_in_journal_or_validation(client, app):
    secret = "sk-" + "t"*30
    client.post("/api/utterance", json={"text": secret, "requestId": "redaction-test"})
    response = client.post("/api/utterance", json={"text": "help", "requestId": secret, "password": secret})
    assert secret not in response.text
    all_events = json.dumps(app.state.store.events(100))
    assert secret not in all_events
    assert secret not in (app.state.config.data_dir / "events.log").read_text()
    assert redact({"api_key": secret, "message": secret}) == {"api_key": "[redacted]", "message": "[redacted]"}


def test_database_backup_restore_and_hash_rejection(tmp_path):
    store = Store(tmp_path / "source")
    store.set_setting("preferences", {"tone": "concise"})
    backup = tmp_path / "backup.sqlite3"
    checksum = store.backup(backup)
    assert checksum == hashlib.sha256(backup.read_bytes()).hexdigest()
    restored = tmp_path / "restored"
    restore_backup(backup, restored)
    assert Store(restored).setting("preferences") == {"tone": "concise"}
    with pytest.raises(ValueError, match="new directory"):
        restore_backup(backup, restored)
    backup.write_bytes(backup.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="hash"):
        restore_backup(backup, tmp_path / "bad")


def test_unsupported_database_version_is_not_modified(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    with sqlite3.connect(tmp_path / "sight.sqlite3") as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(RuntimeError, match="newer"):
        Store(tmp_path)


def test_no_plaintext_vault_fallback(monkeypatch):
    monkeypatch.setattr(Vault, "status", lambda self: {"available": False})
    with pytest.raises(ValueError, match="OS credential"):
        Vault().set("groq", "never-write-this")


def test_local_model_diagnostics_and_no_remote_endpoint(tmp_path):
    config = Config(tmp_path, model="gemma4:e4b")
    calls = []
    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma4:e4b", "size": 4*1024**3, "details": {"family": "gemma4", "quantization_level": "Q4_K_M"}}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"general.name": "Gemma 4 E4B"}, "capabilities": ["completion"]})
        data = json.loads(request.content)
        assert data["options"]["num_ctx"] == 4096 and data["options"]["num_predict"] == 512
        return httpx.Response(200, json={"message": {"content": "Fixture model response"}, "eval_count": 3})
    provider = OllamaProvider(config, transport=httpx.MockTransport(respond))
    result = asyncio.run(provider.generate("hello"))
    assert result["status"] == "ok" and result["say"] == "Fixture model response"
    assert calls == ["/api/tags", "/api/show", "/api/chat"]
    assert provider.limits()["concurrent_inference"] == 1
    with pytest.raises(ValueError, match="loopback"):
        OllamaProvider(replace(config, ollama_url="http://169.254.169.254"))


@pytest.mark.parametrize("metadata,expected", [
    ({"models": []}, "model_missing"),
    ({"models": [{"name": "selected", "size": 100, "details": {"family": "qwen", "quantization_level": "Q4"}}]}, "unsupported_model"),
    ({"models": [{"name": "selected", "size": 9*1024**3, "details": {"family": "gemma4", "quantization_level": "Q4"}}]}, "resource_limit"),
])
def test_model_metadata_failure_never_loads(tmp_path, metadata, expected):
    calls = []
    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=metadata)
    provider = OllamaProvider(Config(tmp_path, model="selected"), transport=httpx.MockTransport(respond))
    assert asyncio.run(provider.generate("hi"))["status"] == expected
    assert calls == ["/api/tags"]
