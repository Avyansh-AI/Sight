"""One bounded synthetic inference, replay check and no-network throttle check.

Real external calls are opt-in through this command, never part of pytest.
The persistent test ledger must not be deleted to reset provider limits.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from fastapi.testclient import TestClient
from sight_core.api import create_app
from sight_core.config import Config
from sight_core.routing import CloudProvider, ProviderPolicy
from sight_core.store import Store
from sight_core.security import redact

MODELS = {'openrouter': 'liquid/lfm-2.5-2.6b:free', 'groq': 'openai/gpt-oss-20b', 'gemini': 'gemini-3.1-flash-lite'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider', choices=MODELS)
    parser.add_argument('--confirm-free-tier', action='store_true', help='Owner has verified this exact account/project is Free tier and paid billing is disabled')
    args = parser.parse_args()
    if args.provider in {'gemini', 'groq'} and not args.confirm_free_tier:
        parser.error('Free account status must be confirmed before a $0 inference test; model-list access is not billing evidence.')
    out = ROOT.parent / 'evidence'
    out.mkdir(exist_ok=True)
    if args.provider == 'openrouter':
        with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as c:
            catalog = c.get('https://openrouter.ai/api/v1/models')
            catalog.raise_for_status()
            selected = next(m for m in catalog.json()['data'] if m['id'] == MODELS[args.provider])
            assert float(selected['pricing']['prompt']) == float(selected['pricing']['completion']) == 0
            (out / 'openrouter_test_model.json').write_text(json.dumps({'id': selected['id'], 'pricing': selected['pricing']}, indent=2), encoding='utf-8')
    data = ROOT.parent / 'test-data/provider-smoke'
    store = Store(data)
    for name in MODELS:
        store.set_setting('provider.' + name, ProviderPolicy(provider=name).model_dump())
    policy = ProviderPolicy(provider=args.provider, model=MODELS[args.provider], enabled=True,
                            allow_remote_text=True, free_tier_confirmed=args.confirm_free_tier,
                            daily_request_limit=3, requests_per_minute=1, daily_token_limit=2000,
                            minute_token_limit=1000, max_output_tokens=128)
    app = create_app(Config(data, model=''))
    calls = []
    original = CloudProvider._read_response
    async def trace(self, client, method, url, **kwargs):
        start = time.perf_counter()
        record = {'method': method, 'url': url}
        if method == 'POST':
            record['max_output_tokens'] = kwargs['json']['max_tokens']
        calls.append(record)
        try:
            response = await original(self, client, method, url, **kwargs)
            record['http_status'] = response.status_code
            if method == 'POST' and response.status_code >= 400:
                try:
                    error = response.json().get('error', {})
                    record['error_summary'] = redact({k: str(error.get(k, ''))[:400] for k in ('code', 'status', 'message')})
                except (ValueError, AttributeError):
                    record['error_summary'] = 'non-JSON error'
            if method == 'POST' and response.status_code == 200:
                try:
                    body = response.json()
                    record['completion_diagnostics'] = {'finish_reasons': [c.get('finish_reason') for c in body.get('choices', [])],
                        'content_present': [bool(c.get('message', {}).get('content')) for c in body.get('choices', [])],
                        'usage': {k: v for k, v in body.get('usage', {}).items() if isinstance(v, (int, float))}}
                except (ValueError, AttributeError, TypeError):
                    record['completion_diagnostics'] = 'malformed'
            return response
        except Exception as exc:
            record['error_type'] = type(exc).__name__
            raise
        finally:
            record['seconds'] = round(time.perf_counter()-start, 4)
    CloudProvider._read_response = trace
    report = {'provider': args.provider, 'model': policy.model, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'spending_authorization_usd': 0, 'account_free_tier_owner_confirmed': args.confirm_free_tier,
              'limits': policy.model_dump(), 'network_calls': calls, 'metadata_calls_before_application': 1 if args.provider == 'openrouter' else 0,
              'paid_fallback': False, 'automatic_retries': 0}
    try:
        with TestClient(app, base_url='http://127.0.0.1:8080') as c:
            assert c.post('/api/session/claim', json={'token': app.state.bootstrap_token}, headers={'origin': 'http://127.0.0.1:8080'}).status_code == 200
            c.headers['x-sight-csrf'] = c.get('/api/session').json()['csrf']
            prepared = c.post('/api/actions/prepare', json={'path': '/api/models/configure', 'args': policy.model_dump()})
            assert prepared.status_code == 200
            action = prepared.json()
            assert c.post('/api/models/configure', json=action['args'] | {'actionApproval': action['approvalId']}).status_code == 200
            prompt = {'text': 'Reply with only the number: 2 plus 2?', 'requestId': 'smoke-' + uuid.uuid4().hex}
            start = time.perf_counter()
            response = c.post('/api/utterance', json=prompt)
            report['reply_seconds'] = round(time.perf_counter()-start, 4)
            report['http_status'] = response.status_code
            report['response'] = response.json()
            count = len(calls)
            replay = c.post('/api/utterance', json=prompt)
            report['replay_equal'] = replay.json() == response.json()
            report['replay_added_network_calls'] = len(calls) - count
            if response.json().get('status') == 'ok':
                blocked = c.post('/api/utterance', json={'text': 'Synthetic throttle check', 'requestId': 'throttle-' + uuid.uuid4().hex})
                report['throttle_status'] = blocked.json()['status']
                report['throttle_added_network_calls'] = len(calls) - count
                assert report['throttle_status'] == 'rate_limited' and report['throttle_added_network_calls'] == 0
            report['quota_after'] = app.state.router.provider(args.provider).quota.status(policy)
            report['generation_requests'] = sum(call['method'] == 'POST' for call in calls)
            report['passed'] = (response.status_code == 200 and response.json().get('status') == 'ok'
                                and response.json().get('say', '').strip().strip('.') == '4'
                                and report['replay_equal'] and report['replay_added_network_calls'] == 0)
    finally:
        CloudProvider._read_response = original
        for name in MODELS:
            store.set_setting('provider.' + name, ProviderPolicy(provider=name).model_dump())
        report['test_provider_policies_disabled_after_run'] = True
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        (out / f'live_{args.provider}_{stamp}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        (out / f'live_{args.provider}_latest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('provider', 'model', 'passed', 'generation_requests', 'reply_seconds', 'response', 'quota_after') if k in report}, indent=2))
    return 0 if report.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
