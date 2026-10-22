> Historical Phase 2 evidence, preserved for context. Statements about later phases describe that earlier handoff. See [current Phase 3 readiness](PHASE3_READINESS.md).

# Phase 2 test results

Final run: 20261019T033613Z-5803a81e. **178 passed, 0 failed, 0 skipped**, in 51.02 seconds. Environment: Windows-11-10.0.26300-SP0; Python 3.12.5. Logs/JUnit/per-test records/screenshots: reports/runs/20261019T033613Z-5803a81e. Pinned hash-verified binary dependency installation and pip check passed.

One non-failing warning remains: Starlette's existing deprecation of the httpx TestClient integration.

## Tested coverage

The complete inherited Phase 1 suite ran alongside quotas/cooldowns, memory provenance/projects/TTL/forgetting/corruption, schema-constrained Forge and dependency pause, sandbox authority negatives, promotion/rollback/archive, roles/budgets/deadlines/pause, scoped grants, actual process death and receipt recovery, private-memory dataflow, code corruption/launcher fallback, OAuth signed identity/refresh/revoke/stream completion, and Chromium interaction.

Original home: **16/16 comparisons, 0 changed pixels**, at 1440×900 and 390×844 across eight states. CSS/body remain byte-identical. The learning page passes real memory edit/delete, XSS, staged skill promotion and task completion flows, with no JavaScript errors or mobile overflow.

## Live inference

Groq/Gemini/OpenRouter each returned expected 4 on synthetic prompts; actual inference, replay and throttle results are recorded in reports/live_PROVIDER_latest.json. No additional cloud calls were used for learning validation.

The final local HTTP/WebSocket test passed **14/14** checks: actual Gemma-generated skill via authenticated API, testing, promotion, two durable DAGs using the same version, output files/receipts, chat, forgetting and unchanged home. Cold Forge generation took 15.758 seconds. The first 19 October attempt correctly failed with Ollama stopped; starting the existing runtime resolved the environment issue.

## Growth benchmark

Every task run had equal allowances: 4 tool calls and 0 model calls. One-time skill generation is separate (1.773 seconds, local Gemma). Correction/promotion was explicitly performed by the synthetic benchmark owner, not autonomous permission escalation.

| Task | Baseline correct / calls | After correct / calls | Repeat correct / calls | Seconds baseline / after / repeat |
|---|---:|---:|---:|---:|
| owner correction | False / 1 | True / 1 | True / 1 | 0.0191 / 0.0183 / 0.0176 |
| missing skill | False / 1 | True / 1 | True / 1 | 0.0203 / 0.0821 / 0.0886 |
| workflow consolidation | True / 2 | True / 1 | True / 1 | 0.1713 / 0.0833 / 0.0998 |

Correctness: **1/3 → 3/3 → 3/3**. Consolidation uses one call instead of two; repeated calls use the same immutable version. Missing-skill rejection is faster than executing the newly learned skill, so capability improvement does not imply every elapsed time improved. Reported times include SQLite/worker overhead; startup, generation and owner review are not hidden in task-only metrics.

Editing the correction changed behavior; deleting it restored the original. Forgetting the procedure made invocation unavailable. Failed-test rollback and stale/archive behavior have separate acceptance tests.

This is evidence for three deterministic text tasks, not general self-improvement or broad coding ability. The UI shows measurements and leaves its general growth_proven flag false.

## Not established

Live owner ChatGPT sign-in/eligibility/catalog/refresh/revoke; fresh Windows user installation; other hardware/OS; long memory-pressure soak; arbitrary Python or package installation; Codex app-server coding; Phases 3–4. External apps' shared quota consumption cannot be inferred from model lists. Phase 1's low transient RAM headroom remains a qualification.
