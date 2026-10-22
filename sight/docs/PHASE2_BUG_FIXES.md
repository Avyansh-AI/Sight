> Historical Phase 2 evidence, preserved for context. Statements about later phases describe that earlier handoff. See [current Phase 3 readiness](PHASE3_READINESS.md).

# Phase 2 bug-fix report

| Defect / reproduced risk | Root cause | Repair and regression |
|---|---|---|
| Free status inferred from authentication | Model list does not prove billing tier | Explicit tier confirmation and free policy; disable policy on key replacement |
| Lost caps/cooldowns | Volatile counters and short reset assumptions | Atomic rolling reservations; failures count; long Retry-After persists across restart |
| Free OpenRouter quota not verified | Model suffix alone cannot prove account headroom | Account preflight fails closed when absent/zero; zero-price route constraints |
| Gemini returned 404 | Old listed model unavailable for actual inference | Verified current free-tier gemini-3.1-flash-lite; bounded live retest passed |
| Empty OpenRouter answer | Initial 32-token response unusable; exact server reason unavailable | 128-token retest passed; output-limit diagnosis and no automatic retry |
| Task remained running | Review SQL used created instead of created_at | Fixed insert/query; actual background completion/review test |
| Memory grant rejected with 403 | Numeric default changed from 1 to 1.0 after validation | Typed defaults and default validation; content-bound approval tests |
| Expired source remained in summary | Summary only checked its own TTL | Source ancestry checks, cascading edit/delete, concurrent revision validation |
| Private memory could reach cloud task | Downstream text lost privacy provenance | Persisted privacy flag; transformed private input disables cloud fallback |
| Crash risk duplicated file effects | Filesystem publication preceded task checkpoint | Prepared identity receipt plus exclusive publication; two real process-crash tests |
| Ambiguous model call could repeat | Running step may already have consumed remote quota | Restart marks needs-review; no automatic retry |
| Gemma produced malformed Forge JSON | Prompt-only output included string array/extra bracket | Ollama schema grammar plus strict OperationPlan parsing; real model retest passed |
| Gemma appeared absent | Runtime offline or wrong model directory | Explicit existing D: folder and hidden runtime helper; saved selection, failed attempt retained |
| Learning UI showed stale running status | Snapshot refresh and out-of-order responses | Bounded active-task polling and refresh generation check; real Chromium test |
| Visual test timing differed | New transitions/animations not fixed to the same phase | Test-only transition stabilization/paused phase on both versions; zero-pixel assertion unchanged |
| Corrupt code selection | Unmanifested extra files not excluded | Full manifest membership, file/dependency hashes, verified baseline fallback |
| ChatGPT connection unavailable | Supplied build lacked supported adapter | Official sign-in, signed identity validation, refresh/revoke, stream completion fixtures |

Failed results were not converted to passes by relaxing correctness, file identity, schema authority or UI pixel thresholds. Captured failed live evidence and passing retests are separate. The complete final regression suite was rerun.
