"""Verify preserved phases, final source bundle, local links and credential exclusion."""
import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parent
WORKSPACE = PHASE.parent
ARCHIVE = PHASE/'SIGHT-Phase4-Partial.zip'
PREFIX = 'SIGHT-Phase4-Verification/'


def preserve():
    baseline = json.loads((PHASE/'evidence/phase3_baseline.json').read_text())
    originals = {row['path']: row['sha256'] for row in baseline}
    for row in baseline:
        assert hashlib.sha256((WORKSPACE/'Phase-3'/row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']
    expected = {
        'Phase-1/SIGHT-Phase1-Repaired.zip': 'f0c33426ca314a4b27557aeb00f7b62ff405626bc4bbf547a253ef17382f6f58',
        'Phase-2/SIGHT-Phase2-Verified.zip': '6417bcd2856e947ae0213eba12f1522a6d450a0f36c44a411490debefcdf81ab',
        'Phase-3/SIGHT-Phase3-Partial.zip': 'ba6c6d8862d5622975e6541348cdf85723ce895fd72e5d100a004597cdf8f483',
    }
    for name, sha in expected.items():
        assert hashlib.sha256((WORKSPACE/name).read_bytes()).hexdigest() == sha, name
    changes = []
    for folder in ('apps', 'sight_core', 'tests', 'scripts', 'docs'):
        for path in sorted((ROOT/folder).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            name = path.relative_to(PHASE).as_posix()
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if sha != originals.get(name):
                changes.append({'path': name, 'status': 'modified' if name in originals else 'added',
                                'original_sha256': originals.get(name), 'sha256': sha})
    for name in ('README.md', 'PLAN.md', 'Start-SIGHT.ps1', 'Open-SIGHT.ps1',
                 'Start-Local-Runtime.ps1', 'Run-Gemma.ps1', 'Verify-SIGHT.ps1',
                 'sight/requirements.in', 'sight/requirements.lock', 'sight/pyproject.toml'):
        path = PHASE/name
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != originals.get(name):
            changes.append({'path': name, 'status': 'modified' if name in originals else 'added',
                            'original_sha256': originals.get(name), 'sha256': sha})
    ui = list((ROOT/'apps/ui').glob('*.html'))
    assert all(path.read_bytes() == (WORKSPACE/'Phase-3/sight/apps/ui'/path.name).read_bytes() for path in ui)
    result = {'phase3_baseline_files_unchanged': len(baseline), 'earlier_packages': expected,
              'all_package_hashes_unchanged': True, 'phase4_ui_files_unchanged_from_phase3': len(ui)}
    (PHASE/'evidence/phase3_preservation.json').write_text(json.dumps(result, indent=2))
    (PHASE/'evidence/phase4_change_manifest.json').write_text(json.dumps(changes, indent=2))
    return result


def check_links():
    broken = []
    paths = [PHASE/'README.md', WORKSPACE/'START_HERE.md', *(ROOT/'docs').glob('*.md'),
             REPORTS/'final_verification.md', REPORTS/'BUILD_PROGRESS.md']
    for path in paths:
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            if target.startswith(('https://', 'http://', '#')):
                continue
            target = target.removeprefix('<').removesuffix('>').split('#')[0]
            if not (path.parent/target).exists():
                broken.append({'document': str(path.relative_to(WORKSPACE)), 'target': target})
    assert not broken, json.dumps(broken)
    return len(paths)


REPORTS = ROOT/'reports'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    preservation = preserve()
    checked_documents = check_links()
    if args.prepare:
        print(json.dumps({'preservation': preservation, 'documents_checked': checked_documents}))
        return
    supplied = Path(r'C:\Users\Dell\Documents\Cool HTML\Api KEYS.txt').read_text(encoding='utf-8-sig')
    keys = {value.encode() for value in re.findall(
        r'(?:sk-[A-Za-z0-9_-]{18,}|gsk_[A-Za-z0-9_-]{18,}|AIza[A-Za-z0-9_-]{18,}|AQ\.[A-Za-z0-9_.-]{18,})', supplied)}
    assert len(keys) >= 10, 'Could not recognize supplied key set; values are not logged'
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read(PREFIX+'BUNDLE_MANIFEST.json'))
        assert manifest['status'] == 'PARTIAL'
        assert manifest['evidence_run'] == json.loads((REPORTS/'latest_test_run.json').read_text())['run_id']
        expected_members = {PREFIX + row['path'] for row in manifest['files']} | {PREFIX+'BUNDLE_MANIFEST.json'}
        assert set(archive.namelist()) == expected_members
        # Verify links against ZIP members too, not only the richer workspace.
        packaged_documents = 0
        for name in expected_members:
            if not name.endswith('.md') or ('/docs/' not in name and not name.endswith(('/README.md', '/final_verification.md', '/BUILD_PROGRESS.md'))):
                continue
            packaged_documents += 1
            for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', archive.read(name).decode('utf-8')):
                if target.startswith(('https://', 'http://', '#')):
                    continue
                target = target.strip('<>').split('#')[0]
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                assert resolved in expected_members or any(item.startswith(resolved.rstrip('/')+'/') for item in expected_members), (name, target)
        for entry in archive.infolist():
            content = archive.read(entry)
            assert not any(key in content for key in keys), 'Credential match; do not distribute'
            assert not any(part in {'.venv', 'owner-data', 'test-data', 'browser-token', 'backup'} for part in Path(entry.filename).parts)
            assert entry.create_system == 0 and entry.external_attr == 0x20 and not entry.flag_bits & 1
        for entry in manifest['files']:
            content = archive.read(PREFIX+entry['path'])
            assert hashlib.sha256(content).hexdigest() == entry['sha256']
            path = PHASE/entry['path']
            assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], entry['path']
        members = len(archive.infolist())
    result = {'archive': str(ARCHIVE), 'sha256': hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
              'bytes': ARCHIVE.stat().st_size, 'members': members, 'crc_valid': True,
              'all_manifest_hashes_valid': True, 'all_packaged_files_match_workspace': True,
              'supplied_credential_values_checked': len(keys), 'credential_matches': 0,
              'owner_data_included': False, 'broken_markdown_links': 0,
              'documents_checked': checked_documents, 'packaged_documents_checked': packaged_documents, 'preservation': preservation,
              'status': 'PARTIAL', 'evidence_run': manifest['evidence_run']}
    (PHASE/'evidence/package_validation.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
