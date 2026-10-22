"""Fresh directory/venv installation using local wheels and provisioned Chromium."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]

def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target=ROOT.parent/'test-data'/('offline-install-'+stamp)/'sight';target.mkdir(parents=True)
    evidence=ROOT.parent/'evidence'/('offline-install-'+stamp);evidence.mkdir()
    for folder in ('apps','sight_core','scripts'):
        shutil.copytree(ROOT/folder,target/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('requirements.lock','requirements-bootstrap.lock','pyproject.toml'):shutil.copyfile(ROOT/name,target/name)
    (target/'reports').mkdir();shutil.copyfile(ROOT/'reports/hermes_skill_inventory.json',target/'reports/hermes_skill_inventory.json')
    env=dict(os.environ,SIGHT_DATA_DIR=str(target.parent/'owner-data'),SIGHT_OLLAMA_MODEL='',PIP_NO_INDEX='1',PYTHONIOENCODING='utf-8')
    # Provisioning wheel hashes are checked again by the real installer.
    wheels=ROOT.parent/'offline/wheels';wheel_manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(wheels.glob('*.whl'))}
    (ROOT.parent/'offline/wheel_manifest.json').write_text(json.dumps(wheel_manifest,indent=2))
    command=[str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),'-NoProfile','-NonInteractive','-File',str(target/'scripts/install.ps1'),'-Offline','-Wheelhouse',str(wheels)]
    start=time.monotonic()
    with (evidence/'install.log').open('w',encoding='utf-8') as log:
        installed=subprocess.run(command,cwd=target,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=0x08000000)
    result={'timestamp_utc':stamp,'command':command,'exit_code':installed.returncode,'seconds':round(time.monotonic()-start,3),
            'fresh_virtual_environment':True,'fresh_windows_account':False,'package_network_disabled':True,'browser':'Existing provisioned cache; no download',
            'wheel_count':len(wheel_manifest),'data_outside_install':True,'runtime_check':None,'complete':False}
    if installed.returncode==0:
        script='''import json,os
from fastapi.testclient import TestClient
from sight_core.api import create_app
from sight_core.config import Config
from sight_core.capability_worker import browser
app=create_app(Config.from_env(),local_only=True)
with TestClient(app,base_url="http://127.0.0.1:8080") as client:
    assert client.get("/").status_code==200
    assert client.post("/api/session/claim",json={"token":app.state.bootstrap_token},headers={"origin":"http://127.0.0.1:8080"}).status_code==200
    assert client.get("/api/health").json()["phase"]==4
    assert not client.get("/api/health").json()["cloud_enabled"]
    assert client.get("/api/models").json()["local"]["status"]=="needs_model"
    assert client.get("/api/capability/skills").json()["total"]==212
rendered=browser({"html":"<title>Offline install</title><p>Fresh environment</p>","fields":{}})
assert rendered["title"]=="Offline install" and rendered["screenshot"]
assert not rendered["network_allowed"] and not rendered["scripts_enabled"]
print(json.dumps({"ui":True,"owner_session":True,"local_only":True,"missing_model_explicit":True,"chromium_offline":True,"production_browser_worker":True,"skill_index":212}))
'''
        checked=subprocess.run([str(target/'.venv/Scripts/python.exe'),'-c',script],cwd=target,env=env,capture_output=True,text=True,timeout=60,creationflags=0x08000000)
        (evidence/'runtime.log').write_text(checked.stdout+checked.stderr,encoding='utf-8')
        result['runtime_check']={'exit_code':checked.returncode,'output':checked.stdout.strip()};result['complete']=checked.returncode==0
    (evidence/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (ROOT/'reports/offline_install_latest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(evidence),'complete':result['complete'],'seconds':result['seconds']}))
    return 0 if result['complete'] else 1

if __name__=='__main__':raise SystemExit(main())
