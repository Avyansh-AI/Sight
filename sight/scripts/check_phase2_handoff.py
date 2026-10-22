"""Validate the portable bundle without recording any supplied credential value."""
import hashlib,json,re,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PHASE=ROOT.parent
WORKSPACE=PHASE.parent
ARCHIVE=PHASE/'SIGHT-Phase2-Verified.zip'
PREFIX='SIGHT-Phase2-Verification/'
secret_text=Path(r'C:\Users\Dell\Documents\Cool HTML\Api KEYS.txt').read_text(encoding='utf-8-sig')
keys={m.encode() for m in re.findall(r'(?:sk-[A-Za-z0-9_-]{18,}|gsk_[A-Za-z0-9_-]{18,}|AIza[A-Za-z0-9_-]{18,}|AQ\.[A-Za-z0-9_.-]{18,})',secret_text)}
assert len(keys)>=10,'Credential scanner did not recognize the supplied key set'
with zipfile.ZipFile(ARCHIVE) as z:
    assert z.testzip() is None
    manifest=json.loads(z.read(PREFIX+'BUNDLE_MANIFEST.json'))
    assert manifest['evidence_run']==json.loads((ROOT/'reports/latest_test_run.json').read_text())['run_id']
    for item in z.infolist():
        data=z.read(item)
        assert not any(key in data for key in keys),'Credential found in package'
        assert not any(p in {'.venv','owner-data','test-data','browser-token'} for p in Path(item.filename).parts)
    for item in manifest['files']:
        assert hashlib.sha256(z.read(PREFIX+item['path'])).hexdigest()==item['sha256']
    members=len(z.infolist())
broken=[]
for path in [PHASE/'README.md',WORKSPACE/'START_HERE.md',*list((ROOT/'docs').glob('*.md'))]:
    for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)',path.read_text(encoding='utf-8')):
        if target.startswith(('https://','http://','#')):continue
        if not (path.parent/target).exists():broken.append({'document':path.name,'target':target})
assert not broken,json.dumps(broken)
originals={r['path']:r['sha256'] for r in json.loads((PHASE/'evidence/phase1_baseline_manifest.json').read_text())}
changes=[]
selected=[p for folder in ('apps','sight_core','tests','scripts','docs') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
selected += [p for p in ROOT.iterdir() if p.is_file()]
selected += [p for p in PHASE.iterdir() if p.is_file() and p.suffix in {'.md','.ps1'}]
for path in selected:
    name=path.relative_to(PHASE).as_posix();sha=hashlib.sha256(path.read_bytes()).hexdigest()
    if sha!=originals.get(name):changes.append({'path':name,'status':'modified' if name in originals else 'added','original_sha256':originals.get(name),'sha256':sha})
result={'archive':str(ARCHIVE),'sha256':hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),'bytes':ARCHIVE.stat().st_size,
        'members':members,'manifest_hashes_valid':True,'crc_valid':True,'credential_values_checked':len(keys),'credential_matches':0,
        'owner_data_included':False,'broken_markdown_links':0,'evidence_run':manifest['evidence_run']}
(PHASE/'evidence/package_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
(PHASE/'evidence/phase2_change_manifest.json').write_text(json.dumps(changes,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))

