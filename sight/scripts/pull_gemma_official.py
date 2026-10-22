"""Download the official local E4B QAT tag; never activate cloud inference."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'gemma4:e4b-it-qat'


def main():
    started = time.monotonic()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = ROOT.parent/'evidence'/('gemma-official-pull-'+stamp+'.json')
    result = {'started_utc': stamp, 'model': MODEL, 'complete': False,
              'owner_direction': 'ok use normal gemma then', 'cloud_inference_requests': 0,
              'source': 'https://ollama.com/library/gemma4:e4b-it-qat'}
    def save():
        result['elapsed_seconds'] = round(time.monotonic()-started, 3)
        path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    save()
    try:
        with httpx.Client(base_url='http://127.0.0.1:11434', trust_env=False,
                          timeout=httpx.Timeout(120, connect=5)) as client:
            last_print = 0
            with client.stream('POST', '/api/pull', json={'model': MODEL, 'stream': True}) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:continue
                    progress = json.loads(line)
                    if progress.get('error'):raise RuntimeError(progress['error'])
                    result['progress'] = progress
                    if time.monotonic()-last_print >= 15 or progress.get('status') == 'success':
                        save();print(json.dumps(progress), flush=True);last_print=time.monotonic()
                    if time.monotonic()-started > 1800:raise TimeoutError('Model download exceeded 30 minutes')
            if result.get('progress', {}).get('status') != 'success':raise RuntimeError('Download did not finish')
            response=client.get('/api/tags');response.raise_for_status()
            result['tag']=next(m for m in response.json()['models'] if m['name']==MODEL)
            response=client.post('/api/show',json={'model':MODEL});response.raise_for_status()
            result['metadata']={k:response.json().get(k) for k in ('details','capabilities','thinking','parameters','model_info','modelfile')}
            result['complete']=True
    except Exception as exc:
        result['error_type']=type(exc).__name__
        raise
    finally:
        save()
        if result['complete']:
            (ROOT/'reports/gemma_official_install.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({'evidence':str(path),'complete':result['complete']}),flush=True)


if __name__ == '__main__':main()
