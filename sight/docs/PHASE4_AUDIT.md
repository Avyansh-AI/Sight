# Phase 4 audit

This pass hardens the existing SIGHT build, records measured behavior and preserves the earlier phases. It does not import arbitrary reference code or turn Markdown guidance into executable authority.

## Workspace and provenance

The workspace contains `Reference.zip`, the V2 PDF manual, original `SIGHT_UI_Clean.html`, eight extracted reference repositories, and preserved Phase-1, Phase-2 and Phase-3 builds. Phase-4 was seeded from 96 selected Phase-3 source/document/report files; environments, owner data, test data and caches were excluded. [Baseline manifest](../../evidence/phase3_baseline.json).

All **21,207 files and 1,431 directory entries** in the eight in-scope archives were reconciled against the extracted files. All file hashes match. No reference code was executed. The ninth nested archive, `rea-main.zip`, is outside the eight-repository manual scope and was left alone. [Current dispositions](../reports/file_dispositions.csv), [archive reconciliation](../reports/phase4_reconciliation.json).

The 120-row [capability matrix](../reports/capability_matrix.csv) contains 77 manual requirement mappings, 20 bounded local adapters, six inherited core families and 17 explicitly blocked integrations. These are different row kinds, not 120 independent fully implemented features. The historical 330,340 lexical/AST/file/manual candidates remain in `reports/source_symbol_candidates.csv`. Complete cross-language semantic feature coverage is not established.

[Per-file license evidence](../reports/source_license_inventory.csv) records root classifications, SPDX observations and nearest license/notice hashes for every source file. MIT, restricted source-available, unresolved and user-reported personal-use permissions remain distinct. Vendor files are flagged. Nearest notices are evidence, not blanket reuse permission. No source code from the eight repositories is incorporated in the new runtime changes.

## Runtime and routing

Python 3.12 and hash-pinned dependencies are retained. Playwright alone was updated from 1.62.0 to 1.64.0 after the external-browser review identified published security fixes newer than bundled Chromium 151.0.7922.34. Its new bundled Chromium is 156.0.8078.4; the evidence records the exact package hashes and vendor sources. Startup is loopback-only, single-instance and local-only by default; Phase-4 uses port 8084 and its own owner-data directory. Verified code snapshots have exact manifest checks, while mutable data stays outside the code snapshot.

Earlier live runs used the OBLITERATUS uncensored E4B Q4_K_M derivative. Its profile repaired parser/prompt configuration without changing model/projector blobs, but reasoning failed. The owner subsequently selected official `gemma4:e4b-it-qat`. The download and all local blob hashes are verified; live official-model inference is pending because the local Ollama executable is currently absent. [Current official model status](OFFICIAL_GEMMA.md), [historical uncensored limitations](GEMMA_REPAIR.md).

The follow-up verified the complete model/projector SHA-256 hashes against the publisher's recorded revision and compared three prompts across 54 local requests. Neither alternative improved held-out results over the selected prompt. Startup portability and caller-environment isolation were also repaired; fresh-account installation remains a separate unverified gate. [Full hashes](../reports/gemma_weight_integrity.json), [prompt results](../reports/gemma_prompt_eval.json), [follow-up checks](../reports/phase4_followup.json).

Groq, Gemini, OpenRouter and optional ChatGPT adapters retain their existing fixed-endpoint, approval, vault and quota protections. Current tests exercise fixtures for routing, rate limits, persistent quota ledgers and failures. **This Phase-4 pass made zero cloud inference requests.** Previous free-tier successes are historical Phase-2 evidence, not fresh live tests. The owner's $0 ceiling remains in force; no paid billing or automatic provider activation was introduced. ChatGPT live owner sign-in remains unverified.

## UI and application behavior

No Phase-4 UI files were edited. The existing integrated home is byte-identical to Phase-3, and original CSS/markup parity is tested against the supplied fixture. Browser tests compare eight ring states at desktop and mobile sizes and exercise real navigation, type chat, consent controls, WebSocket reconnection, HTTP recovery, XSS handling, memory/Forge/task actions and local capability approval/artifact download. Static parity tests freeze time/animation for reproducibility; interactive tests also check state transitions. They do not certify every possible animation frame.

Actual local adapters include isolated offline Chromium, installed Windows speech-to-WAV output, plain document/calendar artifacts, typed geometry and calculations, durable reminders and an authenticated MCP subset. Chromium's native sandbox is now explicitly requested; a real command-line regression reproduced and removed the previous `--no-sandbox` argument. Simulated peripheral contracts are labeled simulations. Microphone/STT, live camera, real remote devices/accounts, external browsing/CDP and broad OS automation remain disabled or incomplete.

## Security and recovery

The audit reproduced and repaired existing-link file corruption, incomplete snapshot verification, unbounded runtime responses, stale MCP capacity and WebSocket-ticket logging. [Bug-fix report](PHASE4_BUG_FIXES.md) links failures and regressions.

Existing tests cover host/origin/CSRF denial, exact one-use approvals, ZIP traversal, private workspace escape, malicious declarative skills, absent shell/network/import authority, credential redaction, untrusted tool output, browser network/script denial, device scope/revocation and crash recovery. These verify bounded local behavior; they are not a penetration-test certification of arbitrary generated code. Forge deliberately executes only a small declarative text-operation language.

Full offline backup now includes both SQLite stores, workspace outputs, artifacts and optional model selection. Restore targets a new directory, verifies hashes/schema/integrity, clears old approvals, disables cloud policies/monitoring, retains quota ledgers and pauses unfinished tasks for review. Credentials, logs, sessions, voices and model weights are excluded. [Recovery instructions](SECURITY_AND_RECOVERY.md).

The memory follow-up reproduced interrupted compaction publishing content without source links, hidden FTS matches displacing visible results, and deep/cyclic provenance crashing retrieval. Summary/index/event/source links now commit atomically; reads validate provenance iteratively in a consistent SQLite snapshot. Old unlinked summaries are retained on disk but excluded from active retrieval. Fourteen new regressions include a real crashed process, concurrent readers and a concurrent privacy correction. Eight live memory checks passed, including launcher restart and edit/delete propagation. [Memory evidence](../reports/memory_integrity_followup.json).

The backend change means the previous one-hour soak is historical, not qualification of this revision. A generated [source/dependency comparison](../reports/soak_current_scope.json) prevents the earlier pass from silently carrying forward. The new live checks also reproduced wrong Gemma answers (`29` and `1ことがある` for `2 plus 2` with synthetic memory present). The second smoke completed 56 of 57 checks successfully and exited with failure for answer quality; the checkpoint is still not reliable.

The PyPI OSV scan and distribution license inventory cover the installed pinned packages. [Dependency findings](../reports/dependency_audit.json), [CycloneDX SBOM](../reports/sbom.cdx.json), [external runtime inventory](../reports/runtime_inventory.json). Public-advisory absence is not proof of security; external binary coverage is explicitly incomplete.

## Test scope and verdict

The [test report](PHASE4_TEST_RESULTS.md) separates regression fixtures, actual Windows operations, the original failed soak, the new soak, model quality, offline installation and growth tests. The [readiness verdict](PHASE4_READINESS.md) remains **PARTIAL** while any mandatory gate is unresolved. No integrated final-release tag or personal wake enrollment is created.
