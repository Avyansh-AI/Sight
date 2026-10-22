import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from sight_core.api import create_app
from sight_core.config import Config
from sight_core.models import ModelStatus


class WaitingProvider:
    def __init__(self):
        self.calls = 0

    async def health(self):
        return ModelStatus("ready", "Test fixture only", configured=True)

    async def generate(self, text):
        self.calls += 1
        await asyncio.sleep(30)  # Test cancels this; it must never finish on its own.
        return {"say": "unexpected completion", "status": "ok"}


def test_cancellation_stays_responsive_and_deduplicates(tmp_path):
    provider = WaitingProvider()
    app = create_app(Config(tmp_path), provider)
    with TestClient(app, base_url="http://127.0.0.1:8080") as client:
        client.post("/api/session/claim", json={"token": app.state.bootstrap_token}, headers={"origin": "http://127.0.0.1:8080"})
        client.headers["x-sight-csrf"] = client.get("/api/session").json()["csrf"]
        ticket = client.post("/api/access/ticket", json={}).json()["ticket"]
        with client.websocket_connect("ws://127.0.0.1:8080/ws/app?ticket="+ticket, headers={"origin": "http://127.0.0.1:8080"}) as ws:
            assert ws.receive_json()["type"] == "hello"
            request = {"type": "utterance", "text": "wait", "requestId": "cancel-request"}
            ws.send_json(request)
            assert ws.receive_json()["type"] == "state"
            ws.send_json(request)
            assert ws.receive_json()["type"] == "state"
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
            ws.send_json({"type": "cancel", "requestId": "cancel-request"})
            replies = [ws.receive_json(), ws.receive_json()]
            assert all(r["status"] == "cancelled" for r in replies)
            assert provider.calls == 1
            assert app.state.store.tasks()[0]["state"] == "cancelled"


def test_single_data_directory_owner(tmp_path):
    from sight_core.cli import single_instance
    with single_instance(tmp_path):
        import subprocess,sys
        result = subprocess.run([sys.executable, "-c", "from sight_core.cli import single_instance;from pathlib import Path;import sys\nwith single_instance(Path(sys.argv[1])):pass", str(tmp_path)], capture_output=True, text=True)
        assert result.returncode != 0 and "Another SIGHT server" in result.stderr
