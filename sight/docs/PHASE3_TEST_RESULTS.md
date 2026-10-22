# Phase 3 test results — 19 October 2026

**221 passed, 0 failed, 0 skipped in 55.60 seconds.** Run: `20261019T090624Z-0c8d66eb`. Python 3.12.5; Windows-11-10.0.26300-SP0. The inherited FastAPI/Starlette httpx TestClient deprecation warning is non-failing; dependencies remain pinned and `pip check` passes.

Command from this Phase 3 root: `sight\.venv\Scripts\python.exe sight\scripts\verify.py`.

| Test group | Passed cases |
|---|---:|
| tests.test_archive_security | 7 |
| tests.test_browser | 9 |
| tests.test_capabilities | 42 |
| tests.test_chatgpt | 14 |
| tests.test_concurrency | 2 |
| tests.test_core | 56 |
| tests.test_gate_requirements | 3 |
| tests.test_learning | 25 |
| tests.test_provider_quotas | 18 |
| tests.test_repairs | 18 |
| tests.test_routing | 27 |

Evidence: `reports/runs/20261019T090624Z-0c8d66eb/junit.xml`, `pytest.log`, `results.json`, `ui_visual_diffs/`; summary at `reports/latest_test_run.json`. The suite uses isolated temporary data and provider fixtures. Real browser and installed Windows voice operations are exercised; this suite makes no real provider inference calls.

Original visual comparisons cover eight states × two viewports (1440×900 and 390×844), all **zero changed pixels**. Animations are frozen at equivalent test phases for deterministic comparison, not disabled in the product. Original CSS/body are byte-checked, and the integrated home HTML is byte-identical to Phase 2. The new capability page was tested through actual approvals/downloads, XSS text, disabled device search and mobile overflow, and its screenshots were inspected. These are separate from the original UI fidelity comparisons.

## Live Windows acceptance

`scripts/phase3_smoke.py` starts the actual root PowerShell launcher in a separate data directory, authenticates over HTTP, invokes all available local tool families, verifies returned artifact hashes, chats with the installed Gemma over WebSocket, then kills/restarts only its own server and verifies durable reminders and artifacts. **48/48 checks pass.** Evidence: `reports/live_phase3_latest.json`; dated raw copy and failed initial harness attempt remain in `Phase-3/evidence`.

Gemma: `hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED:Q4_K_M`; answer `4`, offline, **13.5419 s**. No additional cloud inference/authentication/model-list requests were made in this phase. Phase 2's real Groq/Gemini/OpenRouter free-tier evidence remains preserved and is not relabeled as a new Phase 3 test.

| Live operation | Observed seconds |
|---|---:|
| `files.search` | 0.0198 |
| `documents.docx` | 0.0201 |
| `documents.markdown` | 0.0201 |
| `coding.inspect` | 0.0200 |
| `coding.diff` | 0.0202 |
| `coding.site` | 0.0194 |
| `calendar.export` | 0.0213 |
| `cad.box` | 0.0247 |
| `circuit.ohm` | 0.0232 |
| `geo.distance` | 0.0232 |
| `vision.landmarks` | 0.0206 |
| `windows.info` | 0.0240 |
| `speech.render` | 0.5155 |
| `browser.inspect` | 1.5631 |
| `reminders.add` | 0.0371 |
| `monitor.configure` | 0.0387 |
| `briefing.local` | 0.0379 |
| `mcp.local` | 0.0345 |
| `contracts.simulate` | 0.0338 |
| `live WebSocket Gemma` | 13.5419 |
| `reminders.cancel` | 0.0265 |

Each timing is one local smoke sample, including approval/HTTP overhead where applicable. These are not p95/throughput/soak qualifications. No new thermal, sustained RAM/VRAM, microphone or printer benchmark is claimed.

## Fault and permission coverage

Tests cover absent/changed/replayed grants, cross-origin/CSRF denial, invalid schemas, traversal/hardlinks, no source execution, HTML/OOXML injection handling, timezone/event-line escaping, independently checked STL manifold edges/orientation/volume, bounded numeric inputs, missing browser fields followed by recovery, actual worker-child cancellation, reminder duplicate prevention/quiet hours/cancellation, monitor off/dedup, MCP negotiation/approval/replay/malformed input, stale device revision, expiry/revoke, invalid printer dimensions/profile and simulated disconnect/denial.

Hardware results are explicit: home/Android/printer mock state/contracts are simulated; camera/call fixtures cover trust/status only. The separate MCP client contract and actual owner-local MCP bridge are tested, while external MCP servers and all physical peripherals remain unverified. A generic fixture is not counted as completed live hardware behavior.
