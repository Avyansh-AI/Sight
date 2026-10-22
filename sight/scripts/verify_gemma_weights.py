"""Read-only, full-file verification of the installed uncensored Gemma blobs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'OBLITERATUS/gemma-4-E4B-it-OBLITERATED'
API = 'https://huggingface.co/api/models/' + REPOSITORY
FILES = {
    'application/vnd.ollama.image.model': 'gemma-4-E4B-it-OBLITERATED-Q4_K_M.gguf',
    'application/vnd.ollama.image.projector': 'gemma-4-E4B-it-OBLITERATED-mmproj-f16.gguf',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--models-directory', type=Path, default=Path(r'D:\Ollama Models'))
    args = parser.parse_args()
    started = time.monotonic()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    result = {'timestamp_utc': stamp, 'repository': REPOSITORY, 'metadata_url': API + '?blobs=true',
              'mode': 'Full streaming SHA-256; read-only local files; public publisher metadata',
              'cloud_inference_requests': 0, 'downloaded_weight_bytes': 0, 'files': [], 'passed': False}
    destination = ROOT.parent / 'evidence' / ('gemma-integrity-' + stamp + '.json')
    try:
        with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = client.get(API, params={'blobs': 'true'})
            response.raise_for_status()
            metadata = response.json()
        result['publisher_revision'] = metadata['sha']
        published = {row['rfilename']: row for row in metadata['siblings']}
        paths = [args.models_directory / 'manifests/hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED/Q4_K_M',
                 args.models_directory / 'manifests-v2/ollama.com/library/sight-gemma4-e4b/uncensored']
        manifests = [json.loads(path.read_text()) for path in paths]
        layers = [{row['mediaType']: {k: row[k] for k in ('digest', 'size')} for row in value['layers']
                   if row['mediaType'] in FILES} for value in manifests]
        result['same_uncensored_blob_references'] = layers[0] == layers[1]
        if not result['same_uncensored_blob_references'] or set(layers[0]) != set(FILES):
            raise ValueError('The selected profile must reference both original uncensored blobs')
        for kind, filename in FILES.items():
            layer = layers[0][kind]
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', layer['digest']):
                raise ValueError('Invalid local blob digest')
            path = args.models_directory / 'blobs' / layer['digest'].replace(':', '-')
            expected = published[filename]['lfs']
            digest = hashlib.sha256()
            size = 0
            print(json.dumps({'checking': filename, 'bytes': path.stat().st_size}), flush=True)
            with path.open('rb') as handle:
                while chunk := handle.read(8 * 1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            sha = digest.hexdigest()
            row = {'publisher_file': filename, 'actual_sha256': sha, 'publisher_sha256': expected['sha256'],
                   'manifest_digest': layer['digest'], 'actual_bytes': size, 'publisher_bytes': expected['size'],
                   'passed': sha == expected['sha256'] == layer['digest'][7:] and size == expected['size'] == layer['size']}
            result['files'].append(row)
            if not row['passed']:
                raise ValueError('Installed blob differs from publisher or manifest: ' + filename)
        result['passed'] = True
    except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
        result['error'] = str(exc)
    result['seconds'] = round(time.monotonic() - started, 3)
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    (ROOT / 'reports/gemma_weight_integrity.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(destination), 'passed': result['passed'], 'seconds': result['seconds']}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
