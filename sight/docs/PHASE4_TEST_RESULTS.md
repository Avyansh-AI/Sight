# Phase 4 test results — 22 October 2026

**Release verdict: PARTIAL.** Test results below describe their actual scope.

Selected model: **gemma4:e4b-it-qat**. Official model selection, file integrity and the live-runtime blocker are recorded in [official model status](OFFICIAL_GEMMA.md). Live/quality/growth/soak records below name their original models; uncensored results do not qualify the newly selected official model.

| Check | Recorded result | Evidence |
| --- | --- | --- |
| Full Windows regression suite | 314 passed; 0 failed; 0 skipped | [Current run](../reports/runs/20261022T100402Z-49c429be/results.json), [raw pytest log](../reports/runs/20261022T100402Z-49c429be/pytest.log) |
| Original UI comparison | 16 comparisons; 0 changed pixels | Current run's `ui_visual_diffs` directory |
| Final hardening/routing/recovery subset | See raw JUnit; superseded for release purposes by the complete suite | [JUnit](../../evidence/hardening_final.xml) |
| Last recorded live Windows launcher, HTTP, WS and local adapters | model=sight-gemma4-e4b:uncensored; complete=True; passed=False; 56/57 checks | `reports/live_phase4_latest.json` |
| One-hour soak | HISTORICAL PASS; current runtime requires a new full soak; requested=3600 s, observed=3601.125 s; cycles=60 | [Current result](../reports/soak_latest.json); progress artifact while running |
| Offline fresh venv installation | complete=True; 67.187 s; 39 local wheels | [Install result](../reports/offline_install_latest.json) |
| Dependency OSV scan | complete=True; 38 distributions; 0 advisory findings | [Scan](../reports/dependency_audit.json) |
| Reference archives | 21207 files; 22638 total entries; 21207 matching extracted file hashes | [Reconciliation](../reports/phase4_reconciliation.json) |
| Growth: baseline / after / repeated | 1 / 3 / 3 correct of 3 per stage | `reports/growth_benchmark.json` |
| Live Forge generation | tested; promoted skill origin: model_generated | [Growth evidence](../reports/growth_benchmark.json) |
| Historical direct Ollama helper | Earlier uncensored profile; non-thinking synthetic 17+25 returned 42, exit code 0 | [Direct CLI evidence](../../evidence/gemma_direct_launcher.json) |
| Startup portability follow-up | True; cold-start path/environment decisions covered by fixtures | [Follow-up](../reports/phase4_followup.json), [live helper result](../../evidence/gemma_launcher_portability_live.json) |
| Complete uncensored blob verification | passed=True; 2 complete files | [SHA-256 results](../reports/gemma_weight_integrity.json) |
| Paired prompt evaluation | complete=True; 54 local requests; selected profile unchanged | [Raw answers and grading](../reports/gemma_prompt_eval.json), [interpretation](GEMMA_REPAIR.md) |
| Memory integrity follow-up | 14 new regression cases; 8/8 live memory checks | [Crash, concurrency and retrieval evidence](../reports/memory_integrity_followup.json), [before XML](../../evidence/memory_integrity_before.xml), [after XML](../../evidence/memory_integrity_after.xml) |
| Official model switch | selected=True; all local blob hashes valid=True; live inference verified=False | [Model switch](../reports/official_model_switch.json), [selection regressions](../../evidence/official_model_after.xml) |

The memory follow-up reproduced nine failing cases before repair. Its real process crash and concurrent-reader tests use SQLite, and its deep-lineage test reads/exports/deletes a 1,100-summary chain. These synthetic checks do not measure every production workload. The latest live application run also tests memory provenance across an actual launcher restart and edit/delete propagation. Live answer-quality failures remain failures: the two follow-up runs answered `29` and `1ことがある` to `2 plus 2` with synthetic memory present. The second runner completed the independent checks and returned exit code 1. No retry-until-pass or model substitution was used.

## Soak interpretation

The first 3,600-second attempt stopped after 626.047 seconds when the third Gemma request returned no final answer. It is retained as a **failed test**, not counted as an hour. [Original failed result](../../evidence/soak-20261019T140844Z-5fd335/result.json). A preliminary 25-second harness run is also not an hour.

Every attempt is retained. Runs explicitly aborted for the concurrent SQLite-journal repair and browser dependency refresh do not count toward another run's duration. Another attempt found Ollama stopped after a session gap. The final thinking-enabled attempt failed after 349.125 seconds on the output limit, with zero of two arithmetic requests correct. The selected SIGHT profile and the new soak now have thinking disabled; the checkpoint's broader quality failures remain.

| Run | Requested / observed seconds | Thinking | Completed cycles | Outcome |
| --- | --- | --- | --- | --- |
| [soak-20261019T135821Z-aba992](../../evidence/soak-20261019T135821Z-aba992/result.json) | 10 / 25.407 | automatic | 1 | Short harness run |
| [soak-20261019T140844Z-5fd335](../../evidence/soak-20261019T140844Z-5fd335/result.json) | 3600 / 626.047 | automatic | 10 | FAILED check: real Gemma inference completes |
| [soak-20261020T063618Z-1f15c7](../../evidence/soak-20261020T063618Z-1f15c7/result.json) | 3600 / 1149.64 | automatic | 20 | ABORTED: New full-suite concurrency failure in SQLite journal validation requires a runtime repair and fresh full-duration soak. Only the owned soak process tree was stopped. |
| [soak-20261020T123548Z-34d222](../../evidence/soak-20261020T123548Z-34d222/result.json) | 3600 / 6.297 | automatic | 0 | FAILED check: real Gemma inference completes |
| [soak-20261020T124641Z-45fa46](../../evidence/soak-20261020T124641Z-45fa46/result.json) | 3600 / 364.781 | automatic | 7 | ABORTED: Stopped to update the pinned browser dependency after identifying published security fixes newer than installed Chromium; restart on final dependencies. |
| [soak-20261020T125701Z-6c5a59](../../evidence/soak-20261020T125701Z-6c5a59/result.json) | 3600 / 349.125 | automatic | 5 | FAILED check: real Gemma inference completes |
| [soak-20261021T100817Z-fa2acf](../../evidence/soak-20261021T100817Z-fa2acf/result.json) | 3600 / 3601.125 | False | 60 | Qualified runtime pass |

The final run uses the uncensored profile (thinking=False) and actual HTTP/WebSocket requests, one durable output-file job per cycle, real local inference every five cycles, scoped loopback-runtime fault injection and planned termination/restart of its own test server at cycles 10, 30 and 50. It does not disconnect the host network or kill the owner's applications. Interrupted model tasks must remain `needs_review`; completed files and receipts must persist without replay. The end-of-run full backup/restore, unchanged runtime-source hashes and unchanged installed dependency versions are mandatory for its pass.

Recorded planned server crashes: 3; unplanned exits: 0. Peak GPU memory: 4573.0 MiB; peak GPU temperature: 61.0 C; minimum available host RAM: 341.32 MiB; peak host CPU: 52.65%; peak SIGHT worker working set: 70.65 MiB. Host RAM/CPU include other applications. Regression and offline-install checks overlapped the early part of the final soak, so these are not isolated idle-machine measurements. Live model tests were sequential. CPU temperature is unavailable through the interfaces used.

Arithmetic correctness during the historical uncensored soak: 12/12 recorded requests. Inference latency: median 8.711 s; maximum 23.422 s. This small repeated-prompt check does not establish general quality. Independent diagnostic prompts failed, so **uncensored reasoning quality remained FAIL even though its runtime soak passed**. Official-model reasoning is separately unverified.

The startup-helper follow-up matched the completed soak's server files at that time. The subsequent memory repair changed backend code. Current server/UI/lock/worker hashes match the completed soak: False; changed paths: sight_core/memory.py, sight_core/models.py; installed dependency versions match: True. The original hour remains historical evidence; no new hour is claimed for the memory repair. [Current comparison](../reports/soak_current_scope.json), [earlier startup verification](../reports/phase4_followup.json).

## Reproduction

From `Phase-4/sight`, using the installed Python environment:

```powershell
.\.venv\Scripts\python.exe scripts\verify.py
.\.venv\Scripts\python.exe scripts\phase4_smoke.py
.\.venv\Scripts\python.exe scripts\phase4_soak.py --seconds 3600 --model gemma4:e4b-it-qat
.\.venv\Scripts\python.exe scripts\growth_benchmark.py --model gemma4:e4b-it-qat
.\.venv\Scripts\python.exe scripts\offline_install_check.py
```

Run live model checks sequentially. They use synthetic data in separate test directories. Regression tests use model/provider fixtures; those fixtures do not count as real Gemma or live-provider tests. The observed Starlette/httpx deprecation warning is retained in the log; it did not fail tests.

[Acceptance map](../reports/phase4_acceptance.json) maps the manual's named gates to actual test identifiers and explicit scope limits. Simulations, missing hardware, missing owner sign-in and a current-account venv are never relabeled as real integration or fresh-account passes.
