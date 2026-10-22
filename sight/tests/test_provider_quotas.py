import asyncio
from concurrent.futures import ThreadPoolExecutor
import json

import httpx
import pytest
from pydantic import ValidationError

from sight_core.quotas import QuotaLedger, duration_seconds
from sight_core.routing import CloudProvider, ProviderPolicy
from sight_core.store import Store


class Vault:
    def get(self, provider): return 'synthetic-not-a-real-key'


def policy(**changes):
    return ProviderPolicy(**({'provider':'openrouter', 'model':'fixture:free', 'enabled':True, 'allow_remote_text':True} | changes))


def test_groq_and_gemini_free_policy_requires_owner_tier_confirmation():
    for name in ('groq', 'gemini'):
        with pytest.raises(ValidationError): policy(provider=name, model='test-model')
        p=policy(provider=name, model='test-model', free_tier_confirmed=True)
        assert p.daily_budget_usd == 0 and p.billing_enabled is False
        with pytest.raises(ValidationError): policy(provider=name, model='test-model', free_tier_confirmed=True, billing_enabled=True)


def test_rolling_daily_cap_survives_restart_and_midnight(tmp_path):
    now=[1792367990.0]
    p=policy(daily_request_limit=1)
    ledger=QuotaLedger(Store(tmp_path),'openrouter',lambda:now[0])
    assert ledger.reserve(p,100,0)['allowed']
    now[0]+=20  # Cross UTC midnight without resetting provider usage.
    restarted=QuotaLedger(Store(tmp_path),'openrouter',lambda:now[0])
    assert restarted.reserve(p,100,0)['reason']=='rolling_24h_requests'
    now[0]+=86400
    assert restarted.reserve(p,100,0)['allowed']


def test_rolling_caps_atomic_across_clients(tmp_path):
    store=Store(tmp_path);p=policy(daily_request_limit=3,requests_per_minute=10)
    with ThreadPoolExecutor(max_workers=8) as pool:
        verdicts=list(pool.map(lambda _:QuotaLedger(store,'groq').reserve(p,100,0),range(20)))
    assert sum(x['allowed'] for x in verdicts)==3


def test_minute_and_token_limits_are_durable(tmp_path):
    now=[100000.0];ledger=QuotaLedger(Store(tmp_path),'gemini',lambda:now[0])
    p=policy(requests_per_minute=1,daily_token_limit=180,minute_token_limit=150)
    assert ledger.reserve(p,100,0)['allowed']
    assert ledger.reserve(p,50,0)['reason']=='requests_per_minute'
    now[0]+=61
    assert ledger.reserve(p,81,0)['reason']=='rolling_24h_tokens'
    assert ledger.reserve(p,80,0)['allowed']


def test_provider_wait_longer_than_five_minutes_survives_restart(tmp_path):
    now=[100000.0];store=Store(tmp_path);ledger=QuotaLedger(store,'groq',lambda:now[0])
    ledger.observe({'remaining_requests':0},3600)
    now[0]+=301
    state=QuotaLedger(Store(tmp_path),'groq',lambda:now[0]).status(policy())
    assert state['status']=='rate_limited' and state['retry_after_seconds']==3299


def test_corrupt_ledger_fails_closed(tmp_path):
    store=Store(tmp_path);store.set_setting('provider_quota.gemini',{'attempts':'broken'})
    assert QuotaLedger(store,'gemini').reserve(policy(),10,0)['status']=='quota_state_invalid'


@pytest.mark.parametrize('raw,expected',[('120',120),('1h2m3.5s',3723.5),('500ms',.5),('inf',None),('NaN',None),('broken',None)])
def test_retry_duration_formats(raw,expected):
    assert duration_seconds(raw,0)==expected


def test_no_network_after_failed_attempt_consumes_cap(tmp_path):
    calls=[]
    def response(req):
        calls.append(req)
        return httpx.Response(500,json={})
    p=policy(provider='groq',model='fixture',free_tier_confirmed=True,daily_request_limit=1)
    store=Store(tmp_path)
    first=CloudProvider(p,store,Vault(),httpx.MockTransport(response))
    assert asyncio.run(first.generate('test'))['status']=='provider_error'
    second=CloudProvider(p,Store(tmp_path),Vault(),httpx.MockTransport(response))
    assert asyncio.run(second.generate('test'))['status']=='API_billing_blocked'
    assert len(calls)==1


def test_real_provider_retry_after_persists_without_retry(tmp_path):
    calls=[]
    def response(req):
        calls.append(req)
        return httpx.Response(429,json={'error':{'message':'Rate limit'}},headers={'retry-after':'3600'})
    p=policy(provider='groq',model='fixture',free_tier_confirmed=True)
    store=Store(tmp_path)
    assert asyncio.run(CloudProvider(p,store,Vault(),httpx.MockTransport(response)).generate('test'))['status']=='rate_limited'
    assert asyncio.run(CloudProvider(p,Store(tmp_path),Vault(),httpx.MockTransport(response)).generate('test'))['status']=='rate_limited'
    assert len(calls)==1


def test_openrouter_zero_remaining_stops_before_generation(tmp_path):
    calls=[]
    def response(req):
        calls.append(req)
        assert req.method=='GET' and req.url.path=='/api/v1/key'
        return httpx.Response(200,json={'data':{'free_model_daily_requests':{'remaining':0,'limit':50,'used':50}}})
    p=policy()
    result=asyncio.run(CloudProvider(p,Store(tmp_path),Vault(),httpx.MockTransport(response)).generate('test'))
    assert result['status']=='quota' and len(calls)==1


def test_openrouter_unknown_quota_stops_before_generation(tmp_path):
    provider=CloudProvider(policy(),Store(tmp_path),Vault(),httpx.MockTransport(lambda req:httpx.Response(200,json={'data':{}})))
    assert asyncio.run(provider.generate('test'))['status']=='quota_unverified'


def test_live_probe_output_bound_is_sent(tmp_path):
    def response(req):
        assert json.loads(req.content)['max_tokens']==32
        return httpx.Response(200,json={'choices':[{'message':{'content':'4'}}]})
    p=policy(provider='gemini',model='fixture',free_tier_confirmed=True,max_output_tokens=32)
    result=asyncio.run(CloudProvider(p,Store(tmp_path),Vault(),httpx.MockTransport(response)).generate('two plus two'))
    assert result['say']=='4'


def test_reasoning_exhausting_output_has_clear_status(tmp_path):
    def response(req):
        return httpx.Response(200,json={'choices':[{'finish_reason':'length','message':{'content':None}}]})
    p=policy(provider='groq',model='fixture',free_tier_confirmed=True)
    result=asyncio.run(CloudProvider(p,Store(tmp_path),Vault(),httpx.MockTransport(response)).generate('test'))
    assert result['status']=='output_limit'
