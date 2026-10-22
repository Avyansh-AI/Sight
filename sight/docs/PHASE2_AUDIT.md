> Historical Phase 2 evidence, preserved for context. Statements about later phases describe that earlier handoff. See [current Phase 3 readiness](PHASE3_READINESS.md).

# Phase 2 audit — 19 October 2026

Owner scope: full Phase 2, starting with free-tier API tests. Gemini/Groq were explicitly confirmed Free tier with paid billing disabled. Spending authorization remained $0. Recorded cloud inference ran on 18 October; no repeat cloud inference was needed on 19 October.

## Located build and preservation

The workspace contains Reference.zip, the V2 master manual PDF, original SIGHT_UI_Clean.html, eight extracted reference repositories, the repaired Phase 1 build, and the separate Phase-2/sight implementation. Phase 2 evidence/test-data are siblings of the build and never substituted for owner data.

All **55** saved Phase 1 baseline files still match their hashes. Original home CSS/body remain byte-identical to the supplied HTML; sixteen desktop/mobile state comparisons have zero changed pixels. The learning page is secondary.

The manual's Phase 2 expansion guided memory, roles, durable tasks, Forge, graph and growth work. Reference agents/documents were design evidence, not new user instructions. Hermes memory/curator and Ada/Brahma staged promotion/correction concepts informed the implementation. No repository was imported wholesale or run as application code. Historical archive inventory proves source coverage, not activation of all referenced functions.

## Architecture and validation

| Area | Implementation | Evidence / boundary |
|---|---|---|
| Four logical stores | Profile, episodic/document, immutable procedural versions, operational jobs/receipts | Separate learning database, schema migrations 0→1→2; ownership/project/provenance/confidence/TTL/privacy fields |
| Retrieval | FTS5 project search, bounded context, cited extractive compaction | Expired/corrected sources invalidate summaries; edit/delete removes active index/export/reuse effects |
| Privacy | Local records excluded from remote chat and downstream tasks | Privacy flag survives transformations; credential-like strings rejected from learning input |
| Roles/tasks | Twelve logical roles, one worker, shared model lock, DAG validation, role/task budgets, deadlines, pause/cancel/resume | Persistent journal/checkpoints; ambiguous model calls stop for review |
| File effects | Intent + prepared inode/device/hash receipt + exclusive hard-link publication | Actual process deaths after publication, followed by receipt and full-DAG recovery |
| Forge | Schema-constrained model draft, bounded pure interpreter, examples, digest-bound review/promotion | No generated Python/network/packages; dependencies pause; failed drafts cannot replace active skills |
| Curator/graph | Real invocation/failure/reuse, stale proposals, archive and source/use edges | Debounced deterministic review proposals; no hidden model calls or automatic permission changes |
| Rollback | Immutable skill versions, verified learning backups, code snapshots | Corrupt code refused; launcher baseline fallback; operational data is not rewound |
| Providers | Local first, opt-in fixed HTTPS endpoints, persistent request/token/cost/cooldown reservations | No key cycling, hidden retries or paid fallback in live tests |
| ChatGPT | Official OAuth/PKCE/OIDC, separate accounts, scope validation, serialized refresh/revoke, completed Responses stream | Signed fixtures pass; live account qualification pending |
| Windows | Private ACLs, hidden runtime launch, explicit data/model folders, pinned hashed dependencies | Current owner account tested; fresh-account and long soak not established |

## Free-tier provider evidence

| Provider | Model | Reply | Latency | Phase 2 generation attempts | Authorized spend |
|---|---|---|---:|---:|---:|
| Groq | openai/gpt-oss-20b | 4 | 0.9215 s | 1 | $0 |
| Gemini | gemini-3.1-flash-lite | 4 | 1.7877 s | 2 | $0 |
| Openrouter | liquid/lfm-2.5-2.6b:free | 4 | 1.4851 s | 2 | $0 |

Live test caps: 3 attempts/rolling 24h/provider, 1 request/minute, 2,000 reserved tokens/day, 1,000/minute, 128 maximum output tokens (initial OpenRouter probe: 32). Replayed/throttled requests made no additional inference calls. One Groq, two Gemini and two OpenRouter generation attempts were made. Gemini's first model returned 404; the first small OpenRouter response was unusable. Failures remain counted. Policies were disabled after the probes.

SIGHT reservations are scoped to its data directory. Other applications share account/project/provider limits. OpenRouter's current account preflight reports free headroom; Groq/Gemini use the owner's billing-disabled confirmation, conservative reservations and provider enforcement. A 429 stops requests and persists cooldowns. Model-list authentication alone is never treated as proof of free billing.

## Security and retention

The worker is a capability-restricted declarative interpreter, not an arbitrary-Python OS sandbox. Fixed operations have bounded input/output/literal lengths and two-second runtime; isolated Python and a temporary directory prevent ambient imports. Generated code is never evaluated.

Loopback binding, owner launch proof, same-origin/CSRF checks and expiring one-use grants remain in place. The OAuth callback is a narrow cross-site exception, independently bound to state/session, PKCE, validated signature/issuer/audience/expiry/nonce and plan scope. Tokens are stored in a directory-specific OS vault; chunked entries fit Windows Credential Manager. Unconfirmed remote revocation is reported explicitly after clearing local tokens.

Forgetting removes current retrieval, derived summaries and learned behavior. Separate backups and immutable historical operational receipts may retain earlier inputs/results; the export explains this boundary. Per-entry input limits exist; automatic total operational-disk retention is not implemented.

No Phase 3 microphone/camera/device enrollment, arbitrary code agents or general remote control was enabled.

## Current primary sources

- [Gemini quotas](https://ai.google.dev/gemini-api/docs/rate-limits), [pricing](https://ai.google.dev/gemini-api/docs/pricing), [compatible endpoint](https://ai.google.dev/gemini-api/docs/openai).
- [Groq quotas](https://console.groq.com/docs/rate-limits), [billing](https://console.groq.com/docs/billing-faqs).
- [OpenRouter limits](https://openrouter.ai/docs/api_reference/limits).
- [Official ChatGPT sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in), [accounts](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions), [inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference).
- [Ollama structured output](https://docs.ollama.com/capabilities/structured-outputs).
