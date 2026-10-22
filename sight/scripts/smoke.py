"""Internal loopback readiness check. Never prints the owner launch proof or cookie."""
from pathlib import Path
import json
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sight_core.config import Config


def main():
    config = Config.from_env()
    base = f"http://127.0.0.1:{config.port}"
    with httpx.Client(base_url=base, trust_env=False, timeout=5) as client:
        result = client.post("/api/session/claim", json={"token": (config.data_dir / "browser-token").read_text().strip()}, headers={"origin": base})
        result.raise_for_status()
        health = client.get("/api/health")
        health.raise_for_status()
        status = client.get("/api/status")
        status.raise_for_status()
        if not health.json()["ok"]:
            raise RuntimeError("Database health check failed")
        print(json.dumps({"api": "ok", "model": status.json()["model"]["status"], "release": status.json()["release"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
