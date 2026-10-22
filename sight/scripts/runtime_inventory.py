"""Record external runtime versions, local notices and unchanged model blob references."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def notices(root):
    rows = []
    for path in sorted(root.rglob('*')):
        if path.is_file() and any(word in path.name.lower() for word in ('license', 'licence', 'notice')):
            rows.append({'path': str(path.relative_to(root)), 'bytes': path.stat().st_size,
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return rows


def main():
    models = Path(r'D:\Ollama Models')
    base = models / 'manifests/hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED/Q4_K_M'
    alias = models / 'manifests-v2/ollama.com/library/sight-gemma4-e4b/uncensored'
    manifests = [json.loads(path.read_text()) for path in (base, alias)]
    selected = lambda value: [{key: layer[key] for key in ('mediaType', 'digest', 'size')} for layer in value['layers'] if layer['mediaType'] in
                             ('application/vnd.ollama.image.model', 'application/vnd.ollama.image.projector')]
    same = selected(manifests[0]) == selected(manifests[1])
    assert same, 'Profile does not reference the original uncensored weight blobs'
    layer = next(row for row in selected(manifests[0]) if row['mediaType'].endswith('.model'))
    with (models / 'blobs' / layer['digest'].replace(':', '-')).open('rb') as handle:
        magic, version, tensors, metadata_count = struct.unpack('<4sIQQ', handle.read(24))
    ollama_dir = Path(os.environ['LOCALAPPDATA']) / 'Programs/Ollama'
    with httpx.Client(base_url='http://127.0.0.1:11434', trust_env=False, timeout=10) as client:
        ollama_version = client.get('/api/version').json()['version']
        tags = [row['name'] for row in client.get('/api/tags').json()['models']]
    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True)
        browser_version = browser.version
        browser.close()
        browser_root = Path(engine.chromium.executable_path).parent
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total',
                          '--format=csv,noheader,nounits'], capture_output=True, text=True,
                         check=True, timeout=10, creationflags=0x08000000).stdout.strip()
    result = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(), 'windows': platform.platform(),
        'ollama': {'version': ollama_version, 'executable_sha256': hashlib.sha256((ollama_dir/'ollama.exe').read_bytes()).hexdigest(),
                   'notices': notices(ollama_dir), 'redistributed': False},
        'chromium': {'version': browser_version, 'notices': notices(browser_root), 'redistributed': False},
        'gpu': gpu, 'windows_speech': 'Installed System.Speech/SAPI; OS component, not redistributed',
        'uncensored_weights': {'source_model': 'hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED:Q4_K_M',
                               'profile_model': 'sight-gemma4-e4b:uncensored',
                               'same_weight_and_projector_blob_references': same,
                               'source_manifest_sha256': hashlib.sha256(base.read_bytes()).hexdigest(),
                               'profile_manifest_sha256': hashlib.sha256(alias.read_bytes()).hexdigest(),
                               'blob_references': selected(manifests[0]), 'gguf_format': magic.decode(),
                               'gguf_version': version, 'tensor_count': tensors, 'metadata_entries': metadata_count,
                               'fresh_blob_rehash_performed': False, 'weights_redistributed': False},
        'official_comparison_tag_absent': 'gemma4:e4b-it-qat' not in tags,
        'external_binary_advisory_coverage': 'NOT_CERTIFIED: PyPI OSV scan does not cover every bundled CUDA/Chromium/Windows component.',
        'limits': ['License-file observations are not legal clearance.', 'No driver, OS or Ollama upgrade was installed.']
    }
    (ROOT/'reports/runtime_inventory.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'ollama': ollama_version, 'chromium': browser_version, 'same_uncensored_weights': same,
                      'tensor_count': tensors, 'official_tag_absent': result['official_comparison_tag_absent']}))


if __name__ == '__main__':
    main()
