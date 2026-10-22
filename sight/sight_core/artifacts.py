"""Owner-private, immutable generated artifacts. No caller-controlled paths."""
import hashlib
import os
from pathlib import Path
import re
import uuid
from .security import private_directory
from .tools import LocalFiles

TYPES={'txt':'text/plain','md':'text/markdown','html':'text/html','ics':'text/calendar',
       'stl':'model/stl','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
       'png':'image/png','wav':'audio/wav','json':'application/json','diff':'text/plain'}

class Artifacts:
    def __init__(self,root):
        self.root=Path(root)/'artifacts'
        if LocalFiles.is_link(self.root):raise ValueError('Artifact directory cannot be a link')
        private_directory(self.root)

    def path(self,identifier):
        if not re.fullmatch(r'[a-f0-9]{32}\.(?:'+ '|'.join(TYPES)+')',identifier):raise ValueError('Invalid artifact ID')
        path=self.root/identifier
        if LocalFiles.is_link(self.root) or LocalFiles.is_link(path):raise ValueError('Linked artifacts prohibited')
        if path.exists() and path.stat().st_nlink!=1:raise ValueError('Hard-linked artifacts prohibited')
        return path

    def put(self,data,extension):
        if extension not in TYPES:raise ValueError('Unsupported artifact type')
        if isinstance(data,str):data=data.encode('utf-8')
        if not isinstance(data,bytes) or len(data)>8*1024**2:raise ValueError('Artifact exceeds limit')
        existing=[p for p in self.root.iterdir() if p.is_file() and not LocalFiles.is_link(p)]
        if len(existing)>=200 or sum(p.stat().st_size for p in existing)+len(data)>128*1024**2:
            raise ValueError('Artifact storage limit reached; export and remove unneeded files locally')
        identifier=uuid.uuid4().hex+'.'+extension;path=self.path(identifier)
        with path.open('xb') as f:f.write(data)
        if os.name!='nt':path.chmod(0o600)
        return {'id':identifier,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                'download':'/api/capability/artifacts/'+identifier,'mime':TYPES[extension]}

    def list(self):
        return [{'id':p.name,'bytes':p.stat().st_size} for p in sorted(self.root.iterdir(),key=lambda p:p.name)
                if p.is_file() and not LocalFiles.is_link(p) and p.stat().st_nlink==1][:200]
