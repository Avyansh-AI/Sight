"""Phase 2 storage, separate from the existing authenticated request journal."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .security import private_directory, canonical, safe_database, safe_file, reject_links, atomic_private_write

VERSION = 2


class BrainStore:
    def __init__(self, root):
        self.root = Path(root)
        private_directory(self.root)
        self.path = self.root / 'brain.sqlite3'
        with self.connect() as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Learning database integrity failed; preserve it and restore a verified backup')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > VERSION:
                raise ValueError('Learning database is newer than this build')
            if version == 0:
                db.executescript('''BEGIN IMMEDIATE;
                    CREATE TABLE brain_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    CREATE TABLE profiles(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,project_id TEXT NOT NULL,key TEXT NOT NULL,
                        content TEXT NOT NULL,created_at REAL NOT NULL,last_confirmed_at REAL NOT NULL,source_event_id TEXT NOT NULL,
                        source_uri TEXT NOT NULL,confidence REAL NOT NULL,expiry REAL,privacy_scope TEXT NOT NULL,revision INTEGER NOT NULL,
                        UNIQUE(owner_id,project_id,key));
                    CREATE TABLE episodes(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,project_id TEXT NOT NULL,key TEXT NOT NULL,
                        content TEXT NOT NULL,created_at REAL NOT NULL,last_confirmed_at REAL NOT NULL,source_event_id TEXT NOT NULL,
                        source_uri TEXT NOT NULL,confidence REAL NOT NULL,expiry REAL,privacy_scope TEXT NOT NULL,revision INTEGER NOT NULL);
                    PRAGMA user_version=1; COMMIT;''')
                version = 1
            if version == 1:
                db.executescript('''BEGIN IMMEDIATE;
                    CREATE VIRTUAL TABLE memory_fts USING fts5(id UNINDEXED,store UNINDEXED,project_id UNINDEXED,content);
                    INSERT INTO memory_fts SELECT id,'profile',project_id,content FROM profiles;
                    INSERT INTO memory_fts SELECT id,'episode',project_id,content FROM episodes;
                    CREATE TABLE graph_edges(source TEXT NOT NULL,target TEXT NOT NULL,relation TEXT NOT NULL,PRIMARY KEY(source,target,relation));
                    CREATE TABLE procedures(id TEXT NOT NULL,version INTEGER NOT NULL,owner_id TEXT NOT NULL,project_id TEXT NOT NULL,
                        manifest TEXT NOT NULL,digest TEXT NOT NULL,tests TEXT NOT NULL,created_at REAL NOT NULL,last_confirmed_at REAL NOT NULL,
                        source_event_id TEXT NOT NULL,confidence REAL NOT NULL,expiry REAL,privacy_scope TEXT NOT NULL,
                        active INTEGER NOT NULL DEFAULT 0,archived INTEGER NOT NULL DEFAULT 0,invoked INTEGER NOT NULL DEFAULT 0,
                        failed INTEGER NOT NULL DEFAULT 0,reused INTEGER NOT NULL DEFAULT 0,last_used REAL,PRIMARY KEY(id,version));
                    CREATE TABLE candidates(id TEXT PRIMARY KEY,manifest TEXT NOT NULL,digest TEXT NOT NULL,tests TEXT NOT NULL,
                        state TEXT NOT NULL,created_at REAL NOT NULL,source_event_id TEXT NOT NULL,method TEXT NOT NULL);
                    CREATE TABLE jobs(id TEXT PRIMARY KEY,idempotency_key TEXT UNIQUE NOT NULL,fingerprint TEXT NOT NULL,
                        definition TEXT NOT NULL,state TEXT NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,
                        deadline REAL NOT NULL,tool_calls INTEGER NOT NULL DEFAULT 0,model_calls INTEGER NOT NULL DEFAULT 0,
                        cancel_requested INTEGER NOT NULL DEFAULT 0,error TEXT);
                    CREATE TABLE steps(job TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,id TEXT NOT NULL,definition TEXT NOT NULL,
                        state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,result TEXT,error TEXT,PRIMARY KEY(job,id));
                    CREATE TABLE receipts(id TEXT PRIMARY KEY,job TEXT NOT NULL,step TEXT NOT NULL,name TEXT NOT NULL,
                        content_hash TEXT NOT NULL,device INTEGER,inode INTEGER,state TEXT NOT NULL,UNIQUE(job,step));
                    CREATE TABLE brain_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,ts REAL NOT NULL,kind TEXT NOT NULL,subject TEXT NOT NULL,payload TEXT NOT NULL);
                    CREATE TABLE reviews(task TEXT PRIMARY KEY,created_at REAL NOT NULL,lesson TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'proposed');
                    PRAGMA user_version=2; COMMIT;''')
            row = db.execute("SELECT value FROM brain_settings WHERE key='owner_id'").fetchone()
            if not row:
                db.execute('INSERT INTO brain_settings VALUES(?,?)', ('owner_id', json.dumps(str(uuid.uuid4()))))
        self.owner_id = self.setting('owner_id')

    @contextmanager
    def connect(self):
        safe_database(self.path)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA secure_delete=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT value FROM brain_settings WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute('INSERT INTO brain_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, canonical(value)))

    def event(self, kind, subject, payload=None, db=None):
        if db is None:
            with self.connect() as connection:
                return self.event(kind, subject, payload, connection)
        return db.execute('INSERT INTO brain_events(ts,kind,subject,payload) VALUES(?,?,?,?)', (time.time(),kind,subject,canonical(payload or {}))).lastrowid

    def events(self, subject=None):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM brain_events WHERE (? IS NULL OR subject=?) ORDER BY seq DESC LIMIT 200', (subject,subject))
            return [dict(r) | {'payload':json.loads(r['payload'])} for r in rows]

    def backup(self, destination):
        destination = safe_file(destination)
        if destination.exists(): raise ValueError('Backup destination already exists')
        private_directory(destination.parent)
        safe_file(destination.with_suffix(destination.suffix+'.sha256'))
        with self.connect() as src, sqlite3.connect(destination) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('Backup integrity failed')
        sha = hashlib.sha256(destination.read_bytes()).hexdigest()
        atomic_private_write(destination.with_suffix(destination.suffix+'.sha256'), (sha+'\n').encode('ascii'))
        return {'sha256':sha,'scope':'four Phase 2 logical stores, tasks and receipts; excludes workspace files, credentials and code'}

    @staticmethod
    def restore(source, directory):
        source, directory = safe_file(source), reject_links(directory)
        if directory.exists(): raise ValueError('Restore requires a new directory')
        expected = safe_file(source.with_suffix(source.suffix+'.sha256')).read_text().strip()
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected: raise ValueError('Backup hash mismatch')
        with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as src:
            if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or src.execute('PRAGMA user_version').fetchone()[0] not in (1,2):
                raise ValueError('Unsupported or corrupt learning backup')
            private_directory(directory)
            with sqlite3.connect(directory/'brain.sqlite3') as dst: src.backup(dst)
        return BrainStore(directory)
