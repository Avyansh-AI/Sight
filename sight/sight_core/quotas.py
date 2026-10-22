"""Durable, conservative provider quotas shared across models and keys in one data store."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re
import time

DAY = 86400


def duration_seconds(value, now=None):
    """Accept Retry-After seconds/date and Groq's compound duration headers."""
    now = time.time() if now is None else now
    value = str(value or '').strip()
    try:
        seconds = float(value)
    except ValueError:
        parts = re.findall(r'(\d+(?:\.\d+)?)(ms|s|m|h|d)', value)
        if parts and ''.join(n + unit for n, unit in parts) == value:
            seconds = sum(float(n) * {'ms': .001, 's': 1, 'm': 60, 'h': 3600, 'd': DAY}[unit] for n, unit in parts)
        else:
            try:
                date = parsedate_to_datetime(value)
                seconds = date.timestamp() - now if date.tzinfo else 0
            except (ValueError, TypeError, OverflowError):
                return None
    return max(0, seconds) if math.isfinite(seconds) else None


def rate_observation(headers, now=None):
    """Retain only numeric quota headers; never arbitrary server headers."""
    values = {}
    for kind in ('requests', 'tokens'):
        for field in ('limit', 'remaining'):
            raw = headers.get(f'x-ratelimit-{field}-{kind}')
            if raw is not None and re.fullmatch(r'\d+', str(raw)):
                values[f'{field}_{kind}'] = int(raw)
        seconds = duration_seconds(headers.get(f'x-ratelimit-reset-{kind}'), now)
        if seconds is not None:
            values[f'reset_{kind}_seconds'] = seconds
    retry = duration_seconds(headers.get('retry-after'), now)
    if retry is not None:
        values['retry_after_seconds'] = retry
    return values


class QuotaLedger:
    def __init__(self, store, provider, clock=time.time):
        self.store, self.provider, self.clock = store, provider, clock
        self.key = 'provider_quota.' + provider

    def _load(self, db, now):
        row = db.execute('SELECT value FROM settings WHERE key=?', (self.key,)).fetchone()
        state = json.loads(row[0]) if row else {'attempts': [], 'blocked_until': 0, 'observation': {}}
        return self._validate(state, now)

    def _validate(self, state, now):
        if not isinstance(state, dict) or not isinstance(state.get('attempts'), list):
            raise ValueError('Invalid quota ledger')
        until = state.get('blocked_until', 0)
        if not isinstance(until, (int, float)) or not math.isfinite(until):
            raise ValueError('Invalid quota cooldown')
        for attempt in state['attempts']:
            if not isinstance(attempt, dict) or any(
                not isinstance(attempt.get(k), (int, float)) or not math.isfinite(attempt[k]) or attempt[k] < 0
                for k in ('ts', 'tokens', 'usd')
            ):
                raise ValueError('Invalid quota reservation')
        state['attempts'] = [a for a in state['attempts'] if a['ts'] > now - DAY]
        return state

    def _save(self, db, state):
        db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                   (self.key, json.dumps(state, separators=(',', ':'), allow_nan=False)))

    def _check(self, state, policy, now, tokens, usd):
        attempts = state['attempts']
        minute = [a for a in attempts if a['ts'] > now - 60]
        used = sum(a['tokens'] for a in attempts)
        reason, status, retry = '', 'ok', 0
        if state.get('blocked_until', 0) > now:
            reason, status, retry = 'provider_cooldown', 'rate_limited', state['blocked_until'] - now
        elif len(attempts) >= policy.daily_request_limit:
            reason, status = 'rolling_24h_requests', 'API_billing_blocked'
        elif used + tokens > policy.daily_token_limit:
            reason, status = 'rolling_24h_tokens', 'API_billing_blocked'
        elif sum(a['usd'] for a in attempts) + usd > policy.daily_budget_usd + 1e-12:
            reason, status = 'rolling_24h_budget', 'API_billing_blocked'
        elif len(minute) >= policy.requests_per_minute:
            reason, status = 'requests_per_minute', 'rate_limited'
        elif sum(a['tokens'] for a in minute) + tokens > policy.minute_token_limit:
            reason, status = 'tokens_per_minute', 'rate_limited'
        if reason.startswith('rolling'):
            # Recheck is allowed only after every current reservation has aged out.
            retry = max((a['ts'] + DAY - now for a in attempts), default=DAY)
        elif reason in {'requests_per_minute', 'tokens_per_minute'}:
            retry = max((a['ts'] + 60 - now for a in minute), default=60)
        return {'allowed': not reason, 'status': status, 'reason': reason, 'retry_after_seconds': math.ceil(max(0, retry)),
                'requests_used_24h': len(attempts), 'requests_remaining_24h': max(0, policy.daily_request_limit-len(attempts)),
                'tokens_reserved_24h': used, 'reserved_usd_24h': sum(a['usd'] for a in attempts),
                'window': 'rolling_24_hours', 'scope': 'all models and keys for this provider in this SIGHT data directory',
                'provider_observation': state.get('observation', {})}

    def status(self, policy):
        now = self.clock()
        try:
            state = self.store.setting(self.key, {'attempts': [], 'blocked_until': 0, 'observation': {}})
            return self._check(self._validate(state, now), policy, now, 0, 0)
        except (ValueError, TypeError, KeyError):
            return {'allowed': False, 'status': 'quota_state_invalid', 'reason': 'quota_ledger_unreadable', 'retry_after_seconds': 0}

    def reserve(self, policy, tokens, usd):
        now = self.clock()
        try:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                state = self._load(db, now)
                verdict = self._check(state, policy, now, tokens, usd)
                if verdict['allowed']:
                    state['attempts'].append({'ts': now, 'tokens': tokens, 'usd': usd})
                    self._save(db, state)
                return verdict
        except (ValueError, TypeError, KeyError):
            return {'allowed': False, 'status': 'quota_state_invalid', 'reason': 'quota_ledger_unreadable', 'retry_after_seconds': 0}

    def observe(self, observation, block_seconds=0):
        now = self.clock()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._load(db, now)
            state['observation'] = observation | {'observed_at_utc': datetime.fromtimestamp(now, timezone.utc).isoformat()}
            state['blocked_until'] = max(state.get('blocked_until', 0), now + max(0, block_seconds))
            self._save(db, state)
