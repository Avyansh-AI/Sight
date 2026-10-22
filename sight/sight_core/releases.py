"""Verified code snapshots selected for the next restart; data is never rolled back."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from .security import private_directory,canonical,safe_file,reject_links
from .tools import LocalFiles


class Releases:
    def __init__(self, data_dir, source=None):
        self.data=Path(data_dir)
        self.source=Path(source or Path(__file__).resolve().parents[1])
        self.root=self.data/'releases'

    def snapshot(self):
        identifier=str(uuid.uuid4());destination=self.root/identifier
        private_directory(destination)
        members={}
        paths=[p for folder in ('sight_core','apps') for p in (self.source/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
        paths += [self.source/'requirements.lock',self.source/'pyproject.toml']
        inventory=self.source/'reports/hermes_skill_inventory.json'
        if inventory.is_file():paths.append(inventory)
        for source in paths:
            if LocalFiles.is_link(source):raise ValueError('Release source cannot contain links')
            name=source.relative_to(self.source).as_posix();content=source.read_bytes()
            target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
            members[name]=hashlib.sha256(content).hexdigest()
        manifest={'id':identifier,'files':members,'dependency_lock':members['requirements.lock'],'scope':'code/UI only; credentials, model weights and operational data remain separate'}
        (destination/'manifest.json').write_text(canonical(manifest),encoding='utf-8')
        return {'id':identifier,'files':len(members),'manifest_sha256':hashlib.sha256(canonical(manifest).encode()).hexdigest()}

    def verify(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9-]{36}',identifier):raise ValueError('Invalid release id')
        root=self.root/identifier
        if LocalFiles.is_link(self.root) or LocalFiles.is_link(root):raise ValueError('Release path is a link')
        reject_links(root)
        manifest_file=safe_file(root/'manifest.json')
        if manifest_file.stat().st_size>1_000_000:raise ValueError('Release manifest is too large')
        manifest=json.loads(manifest_file.read_text(encoding='utf-8'))
        if not isinstance(manifest,dict) or manifest.get('id')!=identifier or not isinstance(manifest.get('files'),dict):raise ValueError('Invalid release manifest')
        if not isinstance(manifest.get('dependency_lock'),str):raise ValueError('Invalid dependency lock')
        required={'sight_core/cli.py','sight_core/api.py','apps/ui/index.html','requirements.lock','pyproject.toml'}
        if not required<=manifest['files'].keys():raise ValueError('Incomplete release')
        actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
        if actual!=set(manifest['files'])|{'manifest.json'}:raise ValueError('Release contains unmanifested files')
        for name,expected in manifest['files'].items():
            if not isinstance(expected,str) or not re.fullmatch(r'[a-f0-9]{64}',expected):raise ValueError('Invalid release hash')
            if '__pycache__' in name.split('/') or name.endswith(('.pyc','.pyo')):raise ValueError('Release contains executable bytecode')
            if '\\' in name or name.startswith('/') or '..' in name.split('/') or ':' in name:raise ValueError('Invalid release path')
            target=root/name
            if not target.resolve().is_relative_to(root.resolve()) or LocalFiles.is_link(target) or any(LocalFiles.is_link(p) for p in target.parents if p!=root.parent and p.is_relative_to(root)):
                raise ValueError('Invalid release link')
            if hashlib.sha256(target.read_bytes()).hexdigest()!=expected:raise ValueError('Release file hash mismatch')
        if hashlib.sha256((self.source/'requirements.lock').read_bytes()).hexdigest()!=manifest['dependency_lock']:
            raise ValueError('Release requires a different dependency environment; install and verify it separately')
        return root,manifest

    def select(self,identifier):
        root,manifest=self.verify(identifier)
        pointer=self.data/'active-release.json';temporary=self.data/('release-'+uuid.uuid4().hex+'.tmp')
        previous=json.loads(pointer.read_text()) if pointer.exists() else {'id':None}
        body={'id':identifier,'manifest_sha256':hashlib.sha256(canonical(manifest).encode()).hexdigest(),'previous':previous.get('id')}
        with temporary.open('x',encoding='utf-8') as handle:
            handle.write(canonical(body));handle.flush();os.fsync(handle.fileno())
        temporary.replace(pointer)
        return body|{'restart_required':True,'data_rolled_back':False}

    def selected(self):
        pointer=self.data/'active-release.json'
        if not pointer.exists():return self.source
        safe_file(pointer)
        if pointer.stat().st_size>4096:raise ValueError('Invalid release pointer')
        value=json.loads(pointer.read_text())
        if not isinstance(value,dict):raise ValueError('Invalid release pointer')
        root,manifest=self.verify(value['id'])
        if hashlib.sha256(canonical(manifest).encode()).hexdigest()!=value['manifest_sha256']:raise ValueError('Release manifest was changed')
        return root

    def list(self):
        if not self.root.exists():return []
        rows=[]
        for path in self.root.iterdir():
            if not path.is_dir():continue
            try:self.verify(path.name);valid=True
            except (ValueError,OSError,KeyError):valid=False
            rows.append({'id':path.name,'verified':valid})
        return rows

