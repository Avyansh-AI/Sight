import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json

import httpx
import pytest
from pydantic import ValidationError

from sight_core.routing import CloudProvider, ModelRouter, ProviderPolicy, provider_error
from sight_core.store import Store


def quota_transport(respond):
    # Existing provider-contract cases focus on inference; supply a real-shaped
    # quota preflight response independently of the response under test.
    def route(request):
        if request.method == 'GET' and request.url.path == '/api/v1/key':
            return httpx.Response(200, json={'data': {'free_model_daily_requests': {'remaining': 48}}})
        return respond(request)
    return httpx.MockTransport(route)


class TestVault:
    __test__ = False
    def get(self, provider):
        return 'fixture-key-not-real'


class UnavailableLocal:
    async def generate(self, text):
        return {'status':'offline','say':'Local fixture unavailable','offline':True}


def policy(name='openrouter', **changes):
    values = dict(provider=name, enabled=True, model='fixture/model:free', allow_remote_text=True)
    if name != 'openrouter':
        values.update(model='fixture-model', free_only=False, billing_enabled=True, daily_budget_usd=.01, input_usd_per_million=1, output_usd_per_million=1)
    return ProviderPolicy(**(values | changes))


@pytest.mark.parametrize('name', ['groq','gemini','openrouter'])
def test_provider_contract_uses_only_fixed_endpoint(tmp_path, name):
    calls=[]
    def respond(request):
        calls.append(request)
        assert request.headers['authorization'] == 'Bearer fixture-key-not-real'
        data=json.loads(request.content)
        assert data['stream'] is False and data['max_tokens']==512
        assert data['messages'][-1]['content']=='synthetic test'
        assert 'tools' not in data
        if name=='openrouter':
            assert data['provider']=={'max_price':{'prompt':0,'completion':0},'allow_fallbacks':False}
        return httpx.Response(200,json={'choices':[{'message':{'content':'fixture reply'}}], 'usage':{'prompt_tokens':5,'completion_tokens':2}})
    provider=CloudProvider(policy(name),Store(tmp_path),TestVault(),quota_transport(respond))
    result=asyncio.run(provider.generate('synthetic test'))
    assert result['status']=='ok' and result['provider']==name
    assert result['usage']=={'input_tokens':5,'output_tokens':2}
    assert len(calls)==1 and calls[0].url.scheme=='https'


@pytest.mark.parametrize('code,error,expected', [
    (401,{},'permission_denied'),(402,{},'API_billing_blocked'),(403,{},'permission_denied'),
    (404,{},'unsupported_model'),(429,{},'rate_limited'),(429,{'code':'insufficient_quota'},'API_billing_blocked'),
    (429,{'status':'RESOURCE_EXHAUSTED'},'quota'),(500,{},'provider_error'),(302,{},'provider_error'),
    (400,{'message':'API key not valid'},'permission_denied'),
])
def test_provider_error_categories(code,error,expected):
    assert provider_error(httpx.Response(code,json={'error':error}),'gemini')['status']==expected
    if code==401:
        assert provider_error(httpx.Response(code,json={}), 'chatgpt')['status']=='subscription_revoked'


def test_local_only_never_contacts_cloud_even_when_enabled(tmp_path):
    store=Store(tmp_path)
    store.set_setting('provider.openrouter',policy().model_dump())
    def forbidden(request):
        pytest.fail('Cloud request escaped local-only policy')
    router=ModelRouter(UnavailableLocal(),store,local_only=True,vault=TestVault(),transport=quota_transport(forbidden))
    assert asyncio.run(router.generate('private text'))['attempts']==[{'provider':'local','status':'offline'}]


def test_explicit_fallback_preserves_failures_and_stops_on_success(tmp_path):
    store=Store(tmp_path)
    store.set_setting('provider.groq',policy('groq').model_dump())
    store.set_setting('provider.openrouter',policy().model_dump())
    hosts=[]
    def respond(request):
        hosts.append(request.url.host)
        if request.url.host=='api.groq.com': return httpx.Response(429,json={'error':{'code':'rate_limit'}})
        return httpx.Response(200,json={'choices':[{'message':{'content':'fallback response'}}]})
    router=ModelRouter(UnavailableLocal(),store,vault=TestVault(),transport=quota_transport(respond))
    response=asyncio.run(router.generate('synthetic test'))
    assert response['status']=='ok' and response['provider']=='openrouter'
    assert response['attempts']==[{'provider':'local','status':'offline'},{'provider':'groq','status':'rate_limited'},{'provider':'openrouter','status':'ok'}]
    assert hosts==['api.groq.com','openrouter.ai']


def test_no_consent_no_credential_no_network(tmp_path):
    def forbidden(request): pytest.fail('Unexpected network access')
    provider=CloudProvider(policy(allow_remote_text=False),Store(tmp_path),TestVault(),quota_transport(forbidden))
    assert asyncio.run(provider.generate('private'))['status']=='permission_denied'
    provider.policy=policy()
    provider.vault=type('MissingVault',(),{'get':lambda self,name:None})()
    assert asyncio.run(provider.generate('private'))['status']=='credential_missing'


def test_request_cap_survives_restart_and_counts_failures(tmp_path):
    store=Store(tmp_path)
    p=policy(daily_request_limit=1)
    transport=quota_transport(lambda req:httpx.Response(500,json={}))
    assert asyncio.run(CloudProvider(p,store,TestVault(),transport).generate('test'))['status']=='provider_error'
    assert asyncio.run(CloudProvider(p,Store(tmp_path),TestVault(),transport).generate('test'))['status']=='API_billing_blocked'


def test_budget_reservation_is_atomic(tmp_path):
    store=Store(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:store.reserve_cloud('groq','2026-10-18',.01,100,.03),range(16)))
    assert sum(results)==3


def test_unsafe_free_or_uncapped_policy_rejected():
    with pytest.raises(ValidationError): policy('groq',free_only=True)
    with pytest.raises(ValidationError): policy('groq',daily_budget_usd=0)
    with pytest.raises(ValidationError): policy('groq',billing_enabled=False)
    with pytest.raises(ValidationError): policy(model='paid-model')
    with pytest.raises(ValidationError): policy('groq',input_usd_per_million=float('nan'))


@pytest.mark.parametrize('data', [None,[],{}, {'choices':[]}, {'choices':[{'message':{'content':None}}]}])
def test_malformed_success_returns_error(tmp_path,data):
    p=CloudProvider(policy(),Store(tmp_path),TestVault(),quota_transport(lambda req:httpx.Response(200,json=data)))
    assert asyncio.run(p.generate('test'))['status']=='provider_error'


def test_provider_configuration_requires_bound_approval(client):
    args=policy().model_dump()
    assert client.post('/api/models/configure',json=args).status_code==403
    review=client.post('/api/actions/prepare',json={'path':'/api/models/configure','args':args}).json()
    assert client.post('/api/models/configure',json=args|{'actionApproval':review['approvalId']}).status_code==200
    assert client.get('/api/health').json()['cloud_enabled'] is True
    assert client.get('/api/settings').json()['privacy']['cloud'] is True


def test_gzip_provider_reply_is_decoded_once(tmp_path):
    import gzip
    body=gzip.compress(json.dumps({'choices':[{'message':{'content':'compressed reply'}}]}).encode())
    p=CloudProvider(policy(),Store(tmp_path),TestVault(),quota_transport(lambda req:httpx.Response(200,content=body,headers={'content-encoding':'gzip'})))
    result=asyncio.run(p.generate('test'))
    assert result['status']=='ok' and result['say']=='compressed reply'


def test_readiness_tracks_verified_cloud_fallback(client,app):
    app.state.store.set_setting('provider.openrouter',policy().model_dump())
    app.state.router.vault=TestVault()
    app.state.router.transport=quota_transport(lambda req:httpx.Response(200,json={'choices':[{'message':{'content':'fixture reply'}}]}))
    assert client.get('/api/ready').status_code==503
    assert client.post('/api/utterance',json={'text':'hello','requestId':'ready-fallback'}).json()['status']=='ok'
    assert client.get('/api/ready').json()['status']=='cloud_ready'
    assert client.get('/api/status').json()['online'] is True
