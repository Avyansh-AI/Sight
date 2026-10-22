from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid

from .security import canonical, digest, redact, private_directory, safe_database, safe_file, reject_links, atomic_private_write


class Store:
    def __init__(self, root: Path):
        private_directory(root)
        self.path = root / "sight.sqlite3"
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Database is newer than this SIGHT version; refusing downgrade")
            if version == 0:
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, task TEXT NOT NULL, state TEXT NOT NULL, response TEXT);
                    CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, type TEXT NOT NULL, task TEXT, payload TEXT NOT NULL);
                    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE approvals (token_hash TEXT PRIMARY KEY, session TEXT NOT NULL, path TEXT NOT NULL, args TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                    PRAGMA user_version=1;
                    COMMIT;
                """)
        if os.name != "nt":
            self.path.chmod(0o600)

    def recover_interrupted(self):
        # Called by the sole server at startup, never by doctor or backup commands.
        with self.connect() as db:
            db.execute("UPDATE requests SET state='interrupted' WHERE state='running'")

    @contextmanager
    def connect(self):
        safe_database(self.path)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, kind, payload=None, task=None):
        with self.connect() as db:
            cursor = db.execute("INSERT INTO events(ts,type,task,payload) VALUES(?,?,?,?)", (time.time()*1000, kind, task, canonical(redact(payload or {}))))
            return cursor.lastrowid

    def events(self, count=50):
        with self.connect() as db:
            return [dict(r) | {"payload": json.loads(r["payload"])} for r in db.execute("SELECT * FROM events ORDER BY seq DESC LIMIT ?", (min(count, 100),))]

    def begin(self, request_id, text):
        fingerprint = digest(text)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("requestId already used for different input")
                return dict(existing), False
            task = str(uuid.uuid4())
            db.execute("INSERT INTO requests VALUES(?,?,?,'running',NULL)", (request_id, fingerprint, task))
            return {"id": request_id, "task": task, "state": "running"}, True

    def finish(self, request_id, response, state="complete"):
        # Store redacted outputs; never preserve raw request text or credentials in the journal.
        with self.connect() as db:
            db.execute("UPDATE requests SET response=?,state=? WHERE id=?", (canonical(redact(response)), state, request_id))

    def tasks(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,task,state FROM requests ORDER BY rowid DESC LIMIT 100")]

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, canonical(value)))

    def reserve_cloud(self, provider, day, amount, request_limit, budget):
        """Atomic, durable reservations. Failed/ambiguous requests still consume the cap."""
        key = "usage." + provider + "." + day
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            usage = json.loads(row[0]) if row else {"requests": 0, "reserved_usd": 0}
            if usage["requests"] >= request_limit or usage["reserved_usd"] + amount > budget + 1e-12:
                return False
            usage["requests"] += 1
            usage["reserved_usd"] += amount
            db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, canonical(usage)))
            return True

    def prepare(self, session, path, args):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM approvals WHERE expires < ?", (time.time(),))
            db.execute("INSERT INTO approvals VALUES(?,?,?,?,?,0)", (digest(token), digest(session), path, canonical(args), time.time()+60))
        return token

    def consume(self, token, session, path, args):
        with self.connect() as db:
            cursor = db.execute("UPDATE approvals SET used=1 WHERE token_hash=? AND session=? AND path=? AND args=? AND used=0 AND expires>?", (digest(token), digest(session), path, canonical(args), time.time()))
            return cursor.rowcount == 1

    def backup(self, destination: Path):
        destination=safe_file(destination)
        private_directory(destination.parent)
        safe_file(destination.with_suffix(destination.suffix+'.sha256'))
        if destination.exists():
            raise ValueError("Backup destination already exists")
        with self.connect() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup integrity check failed")
            finally:
                target.close()
        destination.chmod(0o600)
        checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
        atomic_private_write(destination.with_suffix(destination.suffix + '.sha256'), (checksum+'\n').encode('ascii'))
        return checksum


def restore_backup(source: Path, destination_dir: Path):
    """Restore to a NEW data directory; never overwrite existing owner data."""
    source=safe_file(source);destination_dir=reject_links(destination_dir)
    checksum = safe_file(source.with_suffix(source.suffix + '.sha256')).read_text().strip()
    if hashlib.sha256(source.read_bytes()).hexdigest() != checksum:
        raise ValueError("Backup hash mismatch")
    if destination_dir.exists():
        raise ValueError("Restore requires a new directory; stop server and preserve current data")
    with sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("Unsupported or corrupt backup")
        private_directory(destination_dir)
        with sqlite3.connect(destination_dir / "sight.sqlite3") as target:
            db.backup(target)
    (destination_dir / "sight.sqlite3").chmod(0o600)
