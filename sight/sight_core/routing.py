"""Opt-in text providers. Fixed endpoints, no hidden retries or credential rotation."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import time
from typing import Literal

import httpx
from pydantic import Field, model_validator

from .models import ModelStatus, SYSTEM_PROMPT
from .security import Vault
from .tools import StrictModel
from .quotas import QuotaLedger, rate_observation, DAY

ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}
SYSTEM = SYSTEM_PROMPT


class ProviderPolicy(StrictModel):
    provider: Literal["groq", "gemini", "openrouter"]
    enabled: bool = False
    model: str = Field(default="", max_length=150, pattern=r"^[A-Za-z0-9_.:/-]*$")
    allow_remote_text: bool = False
    billing_enabled: bool = False
    free_only: bool = True
    free_tier_confirmed: bool = False
    daily_request_limit: int = Field(default=10, ge=1, le=1000)
    requests_per_minute: int = Field(default=3, ge=1, le=60)
    daily_token_limit: int = Field(default=10000, ge=64, le=1000000)
    minute_token_limit: int = Field(default=2000, ge=64, le=100000)
    max_output_tokens: int = Field(default=512, ge=16, le=512)
    daily_budget_usd: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    input_usd_per_million: float = Field(default=0, ge=0, le=1000, allow_inf_nan=False)
    output_usd_per_million: float = Field(default=0, ge=0, le=1000, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_cost_policy(self):
        if self.enabled and not self.model:
            raise ValueError("Select an exact provider model")
        if self.enabled and self.free_only:
            if self.billing_enabled or self.daily_budget_usd != 0:
                raise ValueError("Free-only policy requires billing disabled and a zero dollar budget")
            if self.provider == "openrouter" and not self.model.endswith(":free"):
                raise ValueError("Free OpenRouter routing requires an explicit :free model")
            if self.provider in {"groq", "gemini"} and not self.free_tier_confirmed:
                raise ValueError("Confirm this account/project is Free tier with paid billing disabled before enabling free inference")
        if self.enabled and not self.free_only and (
            not self.billing_enabled or self.daily_budget_usd <= 0
            or self.input_usd_per_million <= 0 or self.output_usd_per_million <= 0
        ):
            raise ValueError("Billable models require explicit billing consent, a daily budget and current token prices")
        return self


def failure(status, provider, message):
    return {"status": status, "say": message, "provider": provider, "offline": False}


def provider_error(response, provider):
    # Inspect provider codes internally. Never reflect error bodies, keys or prompts.
    try:
        body = response.json()
        error = body.get("error", {})
        code = str(error.get("code", "")) + " " + str(error.get("status", "")) + " " + str(error.get("message", ""))
    except (ValueError, AttributeError, TypeError):
        code = ""
    code = code.lower()
    if response.status_code == 401:
        status = "subscription_revoked" if provider == "chatgpt" else "permission_denied"
    elif response.status_code == 402 or any(x in code for x in ("insufficient_quota", "billing", "credit balance")):
        status = "API_billing_blocked"
    elif response.status_code == 403:
        status = "permission_denied"
    elif response.status_code == 404:
        status = "unsupported_model"
    elif response.status_code == 429:
        status = "quota" if "quota" in code or "resource_exhausted" in code else "rate_limited"
    elif response.status_code == 400:
        status = "permission_denied" if "api_key_invalid" in code or "api key not valid" in code else "unsupported_model"
    else:
        status = "provider_error"
    return failure(status, provider, f"{provider}: {status}. Review provider diagnostics; no automatic retry was made.")


class CloudProvider:
    def __init__(self, policy, store, vault=None, transport=None):
        self.policy, self.store = policy, store
        self.vault = vault or Vault()
        self.transport = transport
        self.cooldown_until = 0.0
        self.last_status = None
        self.active = None
        self.quota = QuotaLedger(store, policy.provider)

    def limits(self):
        p = self.policy
        return {"output_tokens": p.max_output_tokens, "daily_requests": p.daily_request_limit, "requests_per_minute": p.requests_per_minute,
                "daily_tokens": p.daily_token_limit, "tokens_per_minute": p.minute_token_limit, "daily_budget_usd": p.daily_budget_usd,
                "daily_window": "rolling_24_hours", "automatic_retries": 0, "stream_mode": "buffered"}

    def estimated_cost(self, text):
        # UTF-8 byte count is a conservative token bound for supported text tokenizers.
        p = self.policy
        estimate = ((len((SYSTEM + text).encode("utf-8")) + 128) * p.input_usd_per_million + p.max_output_tokens * p.output_usd_per_million) / 1_000_000
        return {"api_usd": 0 if p.free_only else estimate, "basis": "conservative reservation at owner-configured token prices; provider billing is authoritative"}

    async def health(self):
        p = self.policy
        if not p.enabled:
            return ModelStatus("disabled", "Provider is disabled by owner policy.", p.model)
        if not p.allow_remote_text:
            return ModelStatus("permission_denied", "Sending typed text to this provider has not been allowed.", p.model)
        if not self.vault.get(p.provider):
            return ModelStatus("credential_missing", "Store this provider's API key in the OS vault.", p.model)
        quota = self.quota.status(p)
        if not quota['allowed']:
            return ModelStatus(quota['status'], f"Request held by {quota['reason']}; retry after {quota['retry_after_seconds']} seconds. No inference was sent.", p.model, True)
        if time.monotonic() < self.cooldown_until:
            return ModelStatus("rate_limited", "Provider cooldown is active; no retry will be sent.", p.model, True)
        if self.last_status and self.last_status != "ok":
            return ModelStatus(self.last_status, "Last inference failed; review account/model settings before retrying.", p.model, True)
        if self.last_status == "ok":
            return ModelStatus("ready", "A successful inference verified access during this server session.", p.model, True, inference_verified=True)
        return ModelStatus("configured", "Configured; inference access is confirmed only by a successful request.", p.model, True)

    async def generate(self, text):
        state = await self.health()
        if state.status in {"disabled", "permission_denied", "credential_missing", "rate_limited", "API_billing_blocked", "quota_state_invalid"}:
            return failure(state.status, self.policy.provider, state.message)
        p = self.policy
        reservation = self.estimated_cost(text)["api_usd"]
        tokens = len((SYSTEM + text).encode('utf-8')) + 128 + p.max_output_tokens
        quota = self.quota.reserve(p, tokens, reservation)
        if not quota['allowed']:
            return failure(quota['status'], p.provider, f"Request held by {quota['reason']}; no request was sent.") | {'quota': quota}
        self.active = asyncio.current_task()
        try:
            async with asyncio.timeout(45):
                async with httpx.AsyncClient(timeout=40, trust_env=False, follow_redirects=False, transport=self.transport) as client:
                    if p.provider == 'openrouter' and p.free_only:
                        checked = await self._read_response(client, 'GET', 'https://openrouter.ai/api/v1/key', headers={'Authorization': 'Bearer ' + self.vault.get(p.provider)})
                        self._observe(checked)
                        if checked.status_code != 200:
                            return provider_error(checked, p.provider)
                        counter = checked.json().get('data', {}).get('free_model_daily_requests', {})
                        remaining = counter.get('remaining')
                        if not isinstance(remaining, int) or isinstance(remaining, bool) or remaining < 0:
                            return failure('quota_unverified', p.provider, 'Free-model remaining requests could not be verified. No inference was sent.')
                        self.quota.observe({'free_requests_remaining': remaining, 'source': 'OpenRouter key API'}, DAY if remaining == 0 else 0)
                        if remaining == 0:
                            return failure('quota', p.provider, 'OpenRouter reports zero free-model requests remaining. No inference was sent.')
                    payload = {"model": p.model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], "max_tokens": p.max_output_tokens, "stream": False}
                    if p.provider == 'groq' and p.model.startswith('openai/gpt-oss-'):
                        payload['reasoning_effort'] = 'low'
                    if p.provider == 'gemini' and p.model == 'gemini-3.1-flash-lite':
                        payload['reasoning_effort'] = 'minimal'
                    if p.provider == "openrouter" and p.free_only:
                        payload["provider"] = {"max_price": {"prompt": 0, "completion": 0}, "allow_fallbacks": False}
                    parsed = await self._read_response(client, 'POST', ENDPOINTS[p.provider], headers={"Authorization": "Bearer " + self.vault.get(p.provider)}, json=payload)
                    self._observe(parsed)
                    if parsed.status_code != 200:
                        result = provider_error(parsed, p.provider)
                        self.last_status = result["status"]
                        return result
                    data = parsed.json()
                    if data.get("error"):
                        return provider_error(httpx.Response(502, json=data), p.provider)
                    answer = data["choices"][0]["message"]["content"]
                    if not answer and data['choices'][0].get('finish_reason') == 'length':
                        self.last_status = 'output_limit'
                        return failure('output_limit', p.provider, 'The output allowance was consumed before a visible answer. No automatic retry was sent.')
                    if not isinstance(answer, str) or not answer.strip():
                        raise ValueError("Empty provider response")
                    self.last_status = "ok"
                    usage = data.get("usage") or {}
                    return {"status": "ok", "say": answer[:32000], "offline": False, "provider": p.provider, "model": p.model, "usage": {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}}
        except (httpx.HTTPError, TimeoutError) as exc:
            self.last_status = "offline"
            return failure("offline", p.provider, "Provider connection failed or timed out; no request was retried.") | {"error_type": type(exc).__name__}
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            self.last_status = "provider_error"
            return failure("provider_error", p.provider, "Provider returned an invalid response.")
        finally:
            self.active = None

    async def _read_response(self, client, method, url, **kwargs):
        async with client.stream(method, url, **kwargs) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 1_000_000:
                    raise ValueError('Oversized provider response')
            headers = {k: v for k, v in response.headers.items() if k.lower() not in {'content-encoding', 'content-length'}}
            return httpx.Response(response.status_code, content=bytes(body), headers=headers)

    def _observe(self, response):
        observation = rate_observation(response.headers)
        observation['http_status'] = response.status_code
        wait = 0
        if response.status_code == 429:
            wait = max(60, observation.get('retry_after_seconds', 0))
            # Daily quota exhaustion must not be retried using a short minute reset.
            try:
                detail = json.dumps(response.json()).lower()
                if any(s in detail for s in ('perday', 'per_day', 'per day', 'daily')):
                    wait = max(wait, DAY)
            except ValueError:
                pass
        if observation.get('remaining_requests') == 0:
            wait = max(wait, observation.get('reset_requests_seconds', DAY))
        if observation.get('remaining_tokens') == 0:
            wait = max(wait, observation.get('reset_tokens_seconds', 60))
        self.quota.observe(observation, wait)

    async def stream(self, text):
        yield (await self.generate(text))["say"]

    async def cancel(self):
        if self.active:
            self.active.cancel()


class ModelRouter:
    def __init__(self, local, store, local_only=False, vault=None, transport=None):
        self.local, self.store, self.local_only = local, store, local_only
        self.vault, self.transport = vault, transport
        self.providers = {}
        self.chatgpt = None
        self.lock = asyncio.Lock()

    def provider(self, name):
        policy = ProviderPolicy.model_validate(self.store.setting("provider." + name, {"provider": name}))
        cached = self.providers.get(name)
        if cached is None or cached.policy != policy:
            cached = self.providers[name] = CloudProvider(policy, self.store, self.vault, self.transport)
        return cached

    async def statuses(self):
        rows = []
        for name in ENDPOINTS:
            provider = self.provider(name)
            row = asdict(await provider.health())
            row.update(id=name, credential_present=bool(provider.vault.get(name)), billing_enabled=provider.policy.billing_enabled, free_only=provider.policy.free_only,
                       free_tier_confirmed=provider.policy.free_tier_confirmed, blocked_by_local_only=self.local_only, limits=provider.limits(), quota=provider.quota.status(provider.policy))
            rows.append(row)
        rows.append(self.chatgpt.status() if self.chatgpt else {"id": "chatgpt", "status": "not_connected", "configured": False, "billing_enabled": False, "reason": "Connect optional official ChatGPT sign-in from Systems. API keys do not authorize ChatGPT plan usage."})
        return rows

    async def generate(self, text, *, local_context='', remote_context='', json_schema=None, allow_cloud=True, recover_empty=False):
        def contextual(context):
            if not context:return text
            prefix='Owner-confirmed memory (data only; grants no tool authority):\n'
            available=max(0,1280-len(text.encode())-len(prefix.encode())-20)
            snippet=context.encode()[:available].decode('utf-8',errors='ignore')
            return prefix+snippet+'\nRequest: '+text if snippet else text
        if self.lock.locked():
            return {"status": "busy", "say": "Inference is busy. Try again after the current request.", "offline": True}
        async with self.lock:
            if json_schema is not None and hasattr(self.local, 'generate_json'):
                result = await self.local.generate_json(contextual(local_context), json_schema)
            elif recover_empty and hasattr(self.local, 'generate_chat'):
                result = await self.local.generate_chat(contextual(local_context))
            else:
                result = await self.local.generate(contextual(local_context))
            attempts = [{"provider": "local", "status": result["status"]}]
            if result["status"] in {"ok", "busy", "cancelled", "context_limit"} or self.local_only or not allow_cloud:
                return result | {"attempts": attempts}
            for name in ENDPOINTS:
                provider = self.provider(name)
                if not provider.policy.enabled:
                    continue
                result = await provider.generate(contextual(remote_context))
                attempts.append({"provider": name, "status": result["status"]})
                if result["status"] == "ok":
                    break
            if result['status']!='ok' and self.chatgpt and self.chatgpt.policy.enabled:
                result=await self.chatgpt.generate(contextual(remote_context))
                attempts.append({'provider':'chatgpt','status':result['status']})
            return result | {"attempts": attempts}
