"""Offline, integrity-checked owner-data bundles; credentials and code excluded."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3

from .security import canonical, private_directory, reject_links, safe_database, safe_file

MAX_BYTES = 2 * 1024**3
MAX_FILES = 10000
DATABASES = {'sight.sqlite3': {1}, 'brain.sqlite3': {2}}


def checksum(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def validate_database(path, versions):
    safe_database(path)
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA user_version').fetchone()[0] not in versions:
            raise ValueError('Unsupported or corrupt recovery database')


def allowed(name):
    if not isinstance(name, str) or '\\' in name or ':' in name:
        return False
    parts = PurePosixPath(name).parts
    return bool(parts) and PurePosixPath(name).as_posix() == name and all(p not in ('.', '..', '/') for p in parts) and (
        name in {*DATABASES, 'local-model.json'} or len(parts) == 2 and parts[0] in ('files', 'artifacts'))


def exclusive_copy(source, target):
    safe_file(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as src, target.open('xb') as dst:
        while block := src.read(1024 * 1024):
            dst.write(block)


def backup_all(source, destination):
    from .cli import single_instance
    source, destination = reject_links(source), reject_links(destination)
    if not source.is_dir():raise ValueError('Data directory does not exist')
    if destination.exists():raise ValueError('Backup requires a new directory')
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Backup must be outside the data directory')
    with single_instance(source):
        for name, versions in DATABASES.items():validate_database(source / name, versions)
        with sqlite3.connect((source / 'brain.sqlite3').resolve().as_uri() + '?mode=ro', uri=True) as db:
            if db.execute("SELECT COUNT(*) FROM receipts WHERE state!='complete'").fetchone()[0]:
                raise ValueError('Unresolved file receipts require recovery before backup')
        files = [source / name for name in DATABASES]
        if (source / 'local-model.json').exists():files.append(source / 'local-model.json')
        for folder in ('files', 'artifacts'):
            root = reject_links(source / folder)
            if root.exists():
                for path in root.iterdir():
                    safe_file(path)
                    if not allowed(path.relative_to(source).as_posix()):raise ValueError('Unsupported recovery file')
                    files.append(path)
        if len(files) > MAX_FILES or sum(p.stat().st_size for p in files) > MAX_BYTES:
            raise ValueError('Recovery bundle exceeds limit')
        private_directory(destination)
        rows = {}
        for path in files:
            name = path.relative_to(source).as_posix()
            target = destination / name
            if name in DATABASES:
                with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
                    src.backup(dst)
                validate_database(target, DATABASES[name])
            else:
                exclusive_copy(path, target)
            rows[name] = {'sha256': checksum(target), 'bytes': target.stat().st_size}
        manifest = {'format': 'sight-owner-data-v1', 'created_utc': datetime.now(timezone.utc).isoformat(), 'files': rows,
                    'scope': 'Core and learning databases, workspace files, generated artifacts, local model selection',
                    'excluded': ['credentials', 'model weights', 'code snapshots', 'sessions', 'logs', 'voice recordings'],
                    'restore_policy': 'Cloud and monitoring disabled; unfinished tasks need review; completed receipt identity rebound to copied file'}
        encoded = canonical(manifest).encode()
        (destination / 'manifest.json').write_bytes(encoded)
        (destination / 'manifest.sha256').write_text(hashlib.sha256(encoded).hexdigest() + '\n', encoding='ascii')
        return {'directory': str(destination), 'files': len(rows), 'bytes': sum(r['bytes'] for r in rows.values()), 'scope': manifest['scope']}


def verify_bundle(source):
    source = reject_links(source)
    manifest_file = safe_file(source / 'manifest.json')
    safe_file(source / 'manifest.sha256')
    if manifest_file.stat().st_size > 2_000_000 or (source / 'manifest.sha256').stat().st_size > 100:
        raise ValueError('Invalid recovery manifest size')
    if checksum(manifest_file) != (source / 'manifest.sha256').read_text().strip():raise ValueError('Recovery manifest hash mismatch')
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('format') != 'sight-owner-data-v1' or not isinstance(manifest.get('files'), dict):
        raise ValueError('Invalid recovery manifest')
    rows = manifest['files']
    if not DATABASES.keys() <= rows.keys() or len(rows) > MAX_FILES:raise ValueError('Incomplete recovery bundle')
    total = 0
    for name, row in rows.items():
        if not allowed(name) or not isinstance(row, dict) or type(row.get('bytes')) is not int or row['bytes'] < 0:
            raise ValueError('Invalid recovery entry')
        path = safe_file(source / name)
        total += row['bytes']
        if total > MAX_BYTES or path.stat().st_size != row['bytes'] or checksum(path) != row.get('sha256'):
            raise ValueError('Recovery file size or hash mismatch')
    actual = set()
    for path in source.rglob('*'):
        reject_links(path)
        if path.is_file():actual.add(path.relative_to(source).as_posix())
    if actual != rows.keys() | {'manifest.json', 'manifest.sha256'}:raise ValueError('Unmanifested recovery file')
    for name, versions in DATABASES.items():validate_database(source / name, versions)
    return source, manifest


def restore_all(source, destination):
    destination = reject_links(destination)
    if destination.exists():raise ValueError('Restore requires a new directory; existing owner data is preserved')
    source, manifest = verify_bundle(source)
    if destination.is_relative_to(source) or source.is_relative_to(destination):raise ValueError('Restore must be outside the backup directory')
    private_directory(destination)
    for name in manifest['files']:exclusive_copy(source / name, destination / name)
    # No restored approval or cloud policy may authorize a new external action.
    with sqlite3.connect(destination / 'sight.sqlite3') as db:
        db.execute('DELETE FROM approvals')
        for key, value in db.execute("SELECT key,value FROM settings WHERE key LIKE 'provider.%' OR key IN ('chatgpt.policy','phase3.monitor')").fetchall():
            policy = json.loads(value)
            if isinstance(policy, dict):
                policy['enabled'] = False
                db.execute('UPDATE settings SET value=? WHERE key=?', (canonical(policy), key))
        db.execute("UPDATE requests SET state='interrupted' WHERE state='running'")
    with sqlite3.connect(destination / 'brain.sqlite3') as db:
        db.execute("UPDATE jobs SET state='needs_review',error='Restored task requires owner review; no automatic replay' WHERE state IN ('queued','running','paused')")
        db.execute("UPDATE steps SET state='needs_review' WHERE state='running'")
        for identifier, name, expected in db.execute("SELECT id,name,content_hash FROM receipts WHERE state='complete'").fetchall():
            # Only a receipt whose exported file matches can be rebound.
            if not allowed('files/' + name):raise ValueError('Invalid restored receipt path')
            path = destination / 'files' / name
            if path.is_file() and checksum(path) == expected:
                info = path.stat()
                db.execute('UPDATE receipts SET device=?,inode=? WHERE id=?', (info.st_dev, info.st_ino, identifier))
    (destination / 'restore-record.json').write_text(canonical({'restored_utc': datetime.now(timezone.utc).isoformat(), 'source_manifest_sha256': checksum(source / 'manifest.json'), 'policy': manifest['restore_policy']}), encoding='utf-8')
    return {'directory': str(destination), 'files': len(manifest['files']), 'cloud_enabled': False, 'pending_tasks': 'needs_review'}
