"""Verify package integrity and exact supplied credential exclusion without logging values."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1];PHASE=ROOT.parent;WORKSPACE=PHASE.parent
ARCHIVE=PHASE/'SIGHT-Phase3-Partial.zip';PREFIX='SIGHT-Phase3-Verification/'

def main():
    supplied=Path(r'C:\Users\Dell\Documents\Cool HTML\Api KEYS.txt').read_text(encoding='utf-8-sig')
    keys={v.encode() for v in re.findall(r'(?:sk-[A-Za-z0-9_-]{18,}|gsk_[A-Za-z0-9_-]{18,}|AIza[A-Za-z0-9_-]{18,}|AQ\.[A-Za-z0-9_.-]{18,})',supplied)}
    assert len(keys)>=10,'Could not recognize supplied key set'
    with zipfile.ZipFile(ARCHIVE) as z:
        assert z.testzip() is None
        manifest=json.loads(z.read(PREFIX+'BUNDLE_MANIFEST.json'))
        assert manifest['status']=='PARTIAL'
        assert manifest['evidence_run']==json.loads((ROOT/'reports/latest_test_run.json').read_text())['run_id']
        for entry in z.infolist():
            content=z.read(entry)
            assert not any(key in content for key in keys),'Credential found; do not distribute'
            assert not any(p in {'.venv','owner-data','test-data','browser-token'} for p in Path(entry.filename).parts)
        for entry in manifest['files']:assert hashlib.sha256(z.read(PREFIX+entry['path'])).hexdigest()==entry['sha256']
        members=len(z.infolist())
    broken=[]
    for path in [PHASE/'README.md',WORKSPACE/'START_HERE.md',*(ROOT/'docs').glob('*.md')]:
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)',path.read_text(encoding='utf-8')):
            if target.startswith(('https://','http://','#')):continue
            if not (path.parent/target).exists():broken.append({'document':path.name,'target':target})
    assert not broken,json.dumps(broken)
    baseline=json.loads((PHASE/'evidence/phase2_baseline.json').read_text());originals={r['path']:r['sha256'] for r in baseline}
    assert all(hashlib.sha256((WORKSPACE/'Phase-2'/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in baseline)
    expected={'Phase-1/SIGHT-Phase1-Repaired.zip':'f0c33426ca314a4b27557aeb00f7b62ff405626bc4bbf547a253ef17382f6f58',
              'Phase-2/SIGHT-Phase2-Verified.zip':'6417bcd2856e947ae0213eba12f1522a6d450a0f36c44a411490debefcdf81ab'}
    assert all(hashlib.sha256((WORKSPACE/name).read_bytes()).hexdigest()==sha for name,sha in expected.items())
    changes=[]
    for folder in ('apps','sight_core','tests','scripts','docs'):
        for path in sorted((ROOT/folder).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix=='.pyc':continue
            name=path.relative_to(PHASE).as_posix();sha=hashlib.sha256(path.read_bytes()).hexdigest()
            if sha!=originals.get(name):changes.append({'path':name,'status':'modified' if name in originals else 'added','original_sha256':originals.get(name),'sha256':sha})
    result={'archive':str(ARCHIVE),'sha256':hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),'bytes':ARCHIVE.stat().st_size,'members':members,
            'crc_valid':True,'all_manifest_hashes_valid':True,'supplied_credential_values_checked':len(keys),'credential_matches':0,'owner_data_included':False,
            'broken_markdown_links':0,'phase1_and_phase2_packages_unchanged':True,'phase2_baseline_files_unchanged':len(baseline),'status':'PARTIAL','evidence_run':manifest['evidence_run']}
    (PHASE/'evidence/package_validation.json').write_text(json.dumps(result,indent=2))
    (PHASE/'evidence/phase3_change_manifest.json').write_text(json.dumps(changes,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
