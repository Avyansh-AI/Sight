"""Capture final-answer health across fixed seeds, without storing private thinking."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sight_core.models import SYSTEM_PROMPT

MODEL = 'sight-gemma4-e4b:uncensored'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-thinking', action='store_true')
    args = parser.parse_args()
    result = {'started_utc': datetime.now(timezone.utc).isoformat(), 'model': MODEL,
              'thinking': not args.no_thinking, 'cloud_requests': 0, 'rows': [], 'complete': False}
    path = ROOT.parent / 'evidence' / ('gemma-repeat-' + str(int(time.time())) + '.json')
    with httpx.Client(base_url='http://127.0.0.1:11434', trust_env=False, timeout=150) as client:
        for seed in range(8):
            payload = {'model': MODEL, 'stream': False, 'think': not args.no_thinking, 'keep_alive': '5m',
                       'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                                    {'role': 'user', 'content': 'What is 17 plus 25? Reply with the number only.'}],
                       'options': {'num_ctx': 4096, 'num_predict': 512 if args.no_thinking else 1536, 'num_batch': 128,
                                   'use_mmap': True, 'temperature': .7, 'top_p': .9,
                                   'top_k': 40, 'repeat_penalty': 1.1, 'seed': seed}}
            started = time.monotonic()
            response = client.post('/api/chat', json=payload)
            body = response.json()
            message = body.get('message', {})
            row = {'seed': seed, 'status': response.status_code,
                   'seconds': round(time.monotonic() - started, 3),
                   'answer': message.get('content', ''),
                   'thinking_characters': len(message.get('thinking', '')),
                   'done': body.get('done'), 'done_reason': body.get('done_reason'),
                   'generated_tokens': body.get('eval_count'), 'error': body.get('error')}
            result['rows'].append(row)
            path.write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(row), flush=True)
            if response.status_code != 200:
                break
    result['complete'] = len(result['rows']) == 8
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(path)


if __name__ == '__main__':
    main()
