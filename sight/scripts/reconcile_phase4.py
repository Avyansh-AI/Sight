"""Reconcile every original archive entry and per-file license evidence without execution."""
from collections import Counter
import csv
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import shutil
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1];WORKSPACE=ROOT.parents[1];REPORTS=ROOT/'reports'
sys.path.insert(0,str(ROOT))
from audit_inputs import LICENSES,safe_entries,SENSITIVE,SECRET
from sight_core.capabilities import SPECS, BLOCKED

def csv_write(path,rows):
    with path.open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def canonical_matrix(candidates):
    """Separate manual requirement mappings from the actual bounded tool registry."""
    with candidates.open(encoding='utf-8') as handle:
        matrix = [row for row in csv.DictReader(handle) if row['kind'] == 'manual-reference']
    updates = {
        'spec.005': ('PARTIAL', 'store.py; quotas.py; jobs.py', 'Durable events, task call budgets and provider quotas tested; a complete usage analytics UI remains absent.'),
        'spec.025': ('PARTIAL', 'security.py; api.py', 'Credential-shaped values and WebSocket query tickets redacted; free-text personal data is not comprehensively classified.'),
        'spec.026': ('REFERENCE_ONLY', 'none', 'A full opt-in trajectory recorder with export/purge is not implemented. Event journals are a narrower feature.'),
        'spec.054': ('PARTIAL', 'recovery.py; releases.py; config.py', 'Corrupt configuration/snapshots fail safely and verified full-state restore is available; repair is explicit, not automatic.'),
    }
    for row in matrix:
        if row['capability_id'] in updates:
            row['status'], row['active_implementation'], row['reason'] = updates[row['capability_id']]
    fields = list(matrix[0])
    def add(identifier, description, status, scope, implementation, tests, reason, kind='local-implementation'):
        row = dict.fromkeys(fields, '')
        row.update(capability_id='local.' + identifier, archive='independent SIGHT', source_path=implementation,
                   line=0, kind=kind, capability=description, phase=4, status=status,
                   permission_scope=scope, required_tests=tests, active_implementation=implementation,
                   reason=reason, rights='See Phase-4/LICENSE; no reference code imported')
        matrix.append(row)
    for spec in SPECS:
        add(spec.id, spec.description, 'IMPLEMENTED_BOUNDED' if spec.available else 'BLOCKED_PLATFORM',
            spec.permissions, 'capabilities.py; local_adapters.py; capability_worker.py',
            'tests/test_capabilities.py; live_phase4_latest.json',
            'Only the described local operation is enabled; hardware contracts are simulations where stated.')
    for identifier, family, description, status, reason in BLOCKED:
        add(identifier, description, status, 'disabled', 'none', 'No real integration acceptance evidence',
            reason, 'blocked-capability')
    for identifier, description, implementation, tests, reason in [
        ('chat', 'Local Gemma text chat and provider policy routing', 'models.py; routing.py',
         'tests/test_routing.py; tests/test_phase4_hardening.py; soak_latest.json', 'Uncensored E4B only in live tests. Model reasoning quality remains unreliable. Cloud fixtures are not fresh live-provider certification.'),
        ('memory', 'Owner-confirmed local memory, provenance and deletion', 'memory.py',
         'tests/test_learning.py', 'Bounded local FTS storage and explicit source links.'),
        ('jobs', 'Durable typed tasks, budgets, receipts and restart recovery', 'jobs.py',
         'tests/test_learning.py; soak_latest.json', 'No arbitrary shell or code execution; interrupted model calls require review.'),
        ('forge', 'Validated declarative text skills and rollback', 'forge.py; skill_worker.py',
         'tests/test_learning.py; growth_benchmark.json', 'Typed text transformations only; source instructions never grant authority.'),
        ('backup', 'Verified full offline data backup and restore', 'recovery.py',
         'tests/test_recovery.py; soak_latest.json', 'Restore to a new directory; credentials excluded, cloud disabled, unfinished tasks require review.'),
        ('releases', 'Exact-manifest code snapshot selection and rollback', 'releases.py',
         'tests/test_learning.py; tests/test_phase4_hardening.py', 'Owner-writable hashes detect corruption, not malicious same-owner replacement.'),
    ]:
        add(identifier, description, 'PARTIAL' if identifier == 'chat' else 'IMPLEMENTED_BOUNDED',
            'owner session; exact scoped approval for mutations', implementation, tests, reason)
    if len({row['capability_id'] for row in matrix}) != len(matrix):
        raise ValueError('Duplicate canonical capability ID')
    csv_write(REPORTS/'capability_matrix.csv', matrix)
    return matrix


def main():
    if '--matrix-only' in sys.argv:
        matrix = canonical_matrix(REPORTS/'source_symbol_candidates.csv')
        path = REPORTS/'phase4_reconciliation.json'
        result = json.loads(path.read_text(encoding='utf-8'))
        result.update(canonical_capability_rows=len(matrix),
                      capability_status_counts=dict(Counter(row['status'] for row in matrix)),
                      matrix_updated_utc=datetime.now(timezone.utc).isoformat())
        path.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({'matrix_rows': len(matrix), 'kinds': dict(Counter(row['kind'] for row in matrix))}))
        return
    files={ (r['archive'],r['path']):r for r in csv.DictReader((REPORTS/'reference_inventory_current.csv').open(encoding='utf-8')) }
    historical=REPORTS/'file_dispositions_phase1_historical.csv'
    if not historical.exists():shutil.copyfile(REPORTS/'file_dispositions.csv',historical)
    candidates=REPORTS/'source_symbol_candidates.csv'
    if not candidates.exists():shutil.copyfile(REPORTS/'capability_matrix.csv',candidates)
    dispositions=[];licenses=[];archives=[];extracted_matches=0;source_hash_matches=0
    for archive_name,root_license in sorted(LICENSES.items()):
        archive_path=WORKSPACE/'references/archives'/archive_name
        with zipfile.ZipFile(archive_path) as archive:
            entries=safe_entries(archive);terms={};root=PurePosixPath(entries[0].filename).parts[0]
            for entry in entries:
                if entry.is_dir():continue
                relative='/'.join(PurePosixPath(entry.filename).parts[1:])
                if re.fullmatch(r'(?i)(?:licen[sc]e|copying|notice)(?:[._-].*)?',PurePosixPath(relative).name):
                    terms[relative]={'sha256':hashlib.sha256(archive.read(entry)).hexdigest(),'directory':PurePosixPath(relative).parent}
            count=0
            for entry in entries:
                relative='/'.join(PurePosixPath(entry.filename).parts[1:])
                directory=entry.is_dir();content=b'' if directory else archive.read(entry)
                sha=hashlib.sha256(content).hexdigest();sensitive=bool(SENSITIVE.search(relative) or SECRET.search(content))
                disposition='DIRECTORY_ONLY' if directory else 'RESTRICTED_REFERENCE' if sensitive or root_license!='MIT' else 'REFERENCE_ONLY'
                path=WORKSPACE/'references/repos'/root/relative
                matching=path.is_dir() if directory else path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==sha
                if not matching:raise ValueError('Extracted source mismatch: '+archive_name+'/'+relative)
                if not directory:
                    count+=1;extracted_matches+=1
                    if files.get((archive_name,relative),{}).get('sha256')!=sha:raise ValueError('Prior source hash mismatch')
                    source_hash_matches+=1
                dispositions.append({'archive':archive_name,'archive_entry':entry.filename,'relative_path':relative or '.',
                    'entry_type':'directory' if directory else 'file','bytes':entry.file_size,'sha256':sha,'source_license':root_license,
                    'sensitive':sensitive,'chosen_implementation':'none','disposition':disposition,'execution':'never executed',
                    'extracted_matches':matching,'notes':'No source code imported. Directory entry only.' if directory else 'Reference concepts only; complete semantic review and individual reuse rights not established.'})
                if directory:continue
                parent=PurePosixPath(relative).parent
                applicable=[name for name,value in terms.items() if value['directory']==parent or value['directory'] in parent.parents]
                applicable.sort(key=lambda n:(len(PurePosixPath(n).parts),PurePosixPath(n).name.lower().startswith('license')),reverse=True)
                nearest=applicable[0] if applicable else ''
                header='' if sensitive else content[:8192].decode('utf-8',errors='replace')
                match=re.search(r'SPDX-License-Identifier:\s*([A-Za-z0-9(). +:_-]{1,100})',header)
                spdx=match.group(1).strip() if match else ''
                vendor=any(part.lower() in ('node_modules','vendor','vendors','third_party','third-party','external','.venv') for part in PurePosixPath(relative).parts)
                licenses.append({'archive':archive_name,'path':relative,'sha256':sha,'declared_root_terms':root_license,'spdx_header':spdx,
                    'nearest_terms_file':nearest,'terms_sha256':terms[nearest]['sha256'] if nearest else '',
                    'basis':'explicit SPDX header' if spdx else 'nearest license/notice file; applicability requires review' if nearest else 'root classification only; unresolved file terms',
                    'bundled_or_vendor_path':vendor,'sensitive_header_not_read':sensitive,
                    'permission_note':'Personal-use permission is user-reported, not a redistribution grant' if archive_name=='Brahma-Ai-Evo-main.zip' else 'No redistribution/reuse authorization inferred from this inventory',
                    'use':'reference only; not incorporated into executable product'})
            archives.append({'archive':archive_name,'sha256':hashlib.sha256(archive_path.read_bytes()).hexdigest(),'files':count,'directory_entries':sum(e.is_dir() for e in entries),'entries':len(entries),'terms_files':len(terms)})
    csv_write(REPORTS/'file_dispositions.csv',dispositions);csv_write(REPORTS/'source_license_inventory.csv',licenses)
    # Keep the exhaustive symbol candidates, but stop counting functions as product features.
    matrix=canonical_matrix(candidates)
    result={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'archives':archives,'file_entries':len(files),'all_archive_entries':len(dispositions),
            'directory_entries':sum(r['entry_type']=='directory' for r in dispositions),'extracted_file_hash_matches':extracted_matches,'prior_file_hash_matches':source_hash_matches,
            'per_file_license_rows':len(licenses),'canonical_capability_rows':len(matrix),'capability_status_counts':dict(Counter(r['status'] for r in matrix)),
            'reference_code_executed':False,'complete_semantic_feature_coverage':False,
            'limits':['Canonical matrix retains the explicitly mapped manual and local capability rows; it does not certify discovery of every unique feature in all eight repositories.',
                      'All 330340 historical symbol/manual candidates remain in source_symbol_candidates.csv; these include tests, vendors and lexical matches.',
                      'Nearest license and SPDX observations are evidence, not a blanket legal clearance. Restricted and unresolved sources are not imported.',
                      'Historical Phase 1 inventory uses a different Hermes provenance and remains separately named.']}
    (REPORTS/'phase4_reconciliation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('archives','limits')},indent=2))

if __name__=='__main__':main()
