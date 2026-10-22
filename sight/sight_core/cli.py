from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from . import __version__
from .config import Config
from .models import OllamaProvider, cloud_status
from .security import Vault, private_directory, safe_file, atomic_private_write
from .store import Store, restore_backup
from .routing import ModelRouter

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def single_instance(data_dir):
    private_directory(data_dir)
    safe_file(data_dir / 'service.lock')
    with (data_dir / "service.lock").open("a+b") as handle:
        try:
            # Windows rejects reads of a byte locked by another process too.
            # Acquire first; Windows permits locking beyond the current EOF.
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another SIGHT server owns this data directory")
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


async def doctor(config):
    local = OllamaProvider(config)
    model = await local.health()
    class ReadOnlySettings:
        def setting(self, key, default=None):
            database = config.data_dir / "sight.sqlite3"
            if not database.is_file():
                return default
            import sqlite3
            with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
                row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                return json.loads(row[0]) if row else default
    return {"version": __version__, "environment": platform.platform(), "python": platform.python_version(), "data_directory": str(config.data_dir), "api_bind": f"127.0.0.1:{config.port}", "model": asdict(model), "limits": local.limits(), "cloud": await ModelRouter(local, ReadOnlySettings()).statuses(), "vault": Vault().status(), "windows_target_verified": "See audit evidence; doctor does not certify hardware", "voice_enrollment": "PENDING_OWNER_RECORDING", "phase": 4, "release": "PARTIAL"}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sight")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("open")
    start = commands.add_parser("start")
    start.add_argument("--local-only", action="store_true", help="Explicitly require the default local-only policy")
    commands.add_parser("test")
    commands.add_parser("report")
    select = commands.add_parser("configure-model", help="Verify and save an installed Gemma 4 E4B tag; no download")
    select.add_argument("model")
    select.add_argument('--no-thinking', action='store_true', help='Disable reasoning mode; default automatically enables supported thinking')
    credential = commands.add_parser("credential", help="Store a provider key in the OS vault using a hidden prompt")
    credential.add_argument("provider", choices=["groq", "gemini", "openrouter"])
    backup = commands.add_parser("backup")
    backup.add_argument("destination", type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("source", type=Path)
    restore.add_argument("destination", type=Path)
    backup_all = commands.add_parser('backup-all', help='Stop SIGHT first; back up databases, files and artifacts together')
    backup_all.add_argument('destination', type=Path)
    restore_all = commands.add_parser('restore-all', help='Restore a verified data bundle to a new directory; cloud remains disabled')
    restore_all.add_argument('source', type=Path)
    restore_all.add_argument('destination', type=Path)
    args = parser.parse_args(argv)
    try:
        config = Config.from_env()
        if args.command in {"doctor", "report"}:
            print(json.dumps(asyncio.run(doctor(config)), indent=2))
        elif args.command == "credential":
            import getpass
            value = getpass.getpass("API key (hidden): ").strip()
            if not value:
                raise ValueError("No key entered")
            Vault().set(args.provider, value)
            store=Store(config.data_dir)
            policy=store.setting('provider.'+args.provider,{'provider':args.provider})
            policy.update(enabled=False,free_tier_confirmed=False)
            store.set_setting('provider.'+args.provider,policy)
            print("Credential stored in the OS vault. This provider is disabled until its account tier and policy are reviewed again.")
        elif args.command == "configure-model":
            model = asyncio.run(OllamaProvider(replace(config, model=args.model)).health())
            if model.status != "ready":
                raise ValueError(model.message)
            from .security import private_directory
            private_directory(config.data_dir)
            atomic_private_write(config.data_dir / 'local-model.json', json.dumps({'model': args.model, 'thinking':False if args.no_thinking else None}, indent=2).encode('utf-8'))
            print("Installed model verified and saved. Restart SIGHT to use this selection.")
        elif args.command == "open":
            import webbrowser
            token = (config.data_dir / "browser-token").read_text().strip()
            webbrowser.open(f"http://127.0.0.1:{config.port}/#sight-session={token}")
        elif args.command == "start":
            import uvicorn
            from .api import create_app
            if not 1024 <= config.port <= 65535:
                raise ValueError("Use an unprivileged local port between 1024 and 65535")
            with single_instance(config.data_dir):
                uvicorn.run(create_app(config, local_only=args.local_only), host="127.0.0.1", port=config.port, workers=1, access_log=False, ws_max_size=40_000, server_header=False)
        elif args.command == "test":
            return subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"], cwd=ROOT, shell=False).returncode
        elif args.command == "backup":
            store = Store(config.data_dir)
            print(json.dumps({"database_sha256": store.backup(args.destination), "scope": "database only; workspace files, credentials and voice samples are excluded"}))
        elif args.command == "restore":
            restore_backup(args.source, args.destination)
            print("Verified database restored to a new data directory. Set SIGHT_DATA_DIR to that directory before starting SIGHT.")
        elif args.command == 'backup-all':
            from .recovery import backup_all
            print(json.dumps(backup_all(config.data_dir, args.destination)))
        elif args.command == 'restore-all':
            from .recovery import restore_all
            print(json.dumps(restore_all(args.source, args.destination)))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
