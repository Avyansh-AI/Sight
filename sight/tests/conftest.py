from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sight_core.api import create_app
from sight_core.config import Config


@pytest.fixture
def app(tmp_path):
    return create_app(Config(tmp_path / "data"))


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1:8080") as client:
        claim = client.post("/api/session/claim", json={"token": app.state.bootstrap_token}, headers={"origin": "http://127.0.0.1:8080"})
        assert claim.status_code == 200
        client.headers["x-sight-csrf"] = client.get("/api/session").json()["csrf"]
        yield client
