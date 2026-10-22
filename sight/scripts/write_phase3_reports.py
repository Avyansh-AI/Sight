"""Write Phase 3 handoff from saved evidence; no external requests or owner data."""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];PHASE=ROOT.parent;WORKSPACE=PHASE.parent
sys.path.insert(0,str(ROOT))
from sight_core.capabilities import SPECS,BLOCKED

def write(path,text):path.write_text(text.strip()+'\n',encoding='utf-8')

def main():
    latest=json.loads((ROOT/'reports/latest_test_run.json').read_text());assert latest['exit_code']==0 and latest['counts']['FAIL']==latest['counts']['SKIP']==0
    run=ROOT/'reports/runs'/latest['run_id'];results=json.loads((run/'results.json').read_text())
    live=json.loads((ROOT/'reports/live_phase3_latest.json').read_text());assert live['passed'] and live['complete']
    inventory=json.loads((ROOT/'reports/phase3_inventory.json').read_text())
    visual=[]
    for p in (run/'ui_visual_diffs').glob('metrics_*.json'):visual+=json.loads(p.read_text())
    assert len(visual)==16 and all(r['changed_pixels']==0 for r in visual)
    baseline=json.loads((PHASE/'evidence/phase2_baseline.json').read_text())
    assert all(hashlib.sha256((WORKSPACE/'Phase-2'/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in baseline)
    unchanged={'phase2_source_files_checked':len(baseline),'all_unchanged':True,'original_home_sha256':hashlib.sha256((ROOT/'apps/ui/index.html').read_bytes()).hexdigest(),'phase2_home_identical':(ROOT/'apps/ui/index.html').read_bytes()==(WORKSPACE/'Phase-2/sight/apps/ui/index.html').read_bytes()}
    write(PHASE/'evidence/phase2_preservation.json',json.dumps(unchanged,indent=2))
    count=latest['counts']['PASS'];duration=float(ET.parse(run/'junit.xml').getroot().find('testsuite').get('time'))
    model=next(r['detail'] for r in live['checks'] if r['name']=='live WebSocket Gemma')
    timings={r['name']:r['detail']['seconds'] for r in live['checks'] if isinstance(r['detail'],dict) and 'seconds' in r['detail']}
    rows='\n'.join(f"| `{s.id}` | {s.family} | {s.description} | {s.permissions} |" for s in SPECS)
    blocked='\n'.join(f"| `{identifier}` | {status} | {reason} |" for identifier,family,description,status,reason in BLOCKED)
    test_classes=Counter(t['class'] for t in results['tests']);classes='\n'.join(f'| {name} | {value} |' for name,value in sorted(test_classes.items()))
    timing_rows='\n'.join(f'| `{name}` | {seconds:.4f} |' for name,seconds in timings.items())
    write(PHASE/'README.md',r'''# SIGHT Phase 3 — local capabilities

This is a separate Phase 3 verification build. **Phase 3 is PARTIAL**, with the enabled local scope tested and broader integrations explicitly unavailable. Read [readiness](sight/docs/PHASE3_READINESS.md), [audit](sight/docs/PHASE3_AUDIT.md), and [test results](sight/docs/PHASE3_TEST_RESULTS.md).

From PowerShell in this folder:

```powershell
.\Start-Local-Runtime.ps1
.\Start-SIGHT.ps1
```

Leave the server running. In another PowerShell window run `.\Open-SIGHT.ps1`. Open **Systems → Open capabilities**. Phase 3 uses **http://127.0.0.1:8083** and its separate `owner-data` directory. Phase 2's source and data are preserved. The original SIGHT home HTML is byte-identical to the verified Phase 2 home.

The page offers local documents, calendar export, code inspection/diffs, static site drafts, cuboid STL generation, offline browser inspection, Windows information and speech-to-WAV rendering, reminders, and small circuit/geospatial/landmark tools. Every invocation requires review of exact arguments. Remote devices, microphones, cameras and external messages are not activated. Simulations are clearly labeled.

The current workspace has an installed Python environment and verified local Gemma selection. The runtime helper uses the existing `D:\Ollama Models` directory; it never downloads weights or stops an existing runtime. The selected model is the third-party derivative `hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED:Q4_K_M`.

For a new extraction, install Python 3.12 and run `sight\scripts\install.ps1`. Start Ollama using your existing model directory, then configure it from this Phase 3 root:

```powershell
$env:SIGHT_DATA_DIR = Join-Path $PWD.Path 'owner-data'
Push-Location sight
try { .\.venv\Scripts\python.exe -m sight_core.cli configure-model 'hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED:Q4_K_M' } finally { Pop-Location }
```

Run `.\Verify-SIGHT.ps1` for the full regression suite. For the separate live local smoke, run `.\sight\.venv\Scripts\python.exe .\sight\scripts\phase3_smoke.py` from this folder. That check starts/stops only its own test server and uses an isolated test data directory.

Cloud policies are disabled by default and startup forces local-only mode. Phase 3 made **zero cloud inference requests**. Previous free-provider results and rolling quota ledgers in Phase 2 remain untouched. Do not reset those ledgers to rerun tests. The existing $0/free-tier limits still apply; paid billing was not authorized.

Artifacts are private immutable files under `owner-data/artifacts`, with a cap of 200 files / 128 MiB. Download/export them and remove unneeded files locally when full. Windows voice output is a downloadable WAV, with no automatic playback or recording. Reminder delivery is inside SIGHT only; recurrence and quiet hours use UTC. Missed intervals combine into one notice after restart.

The [local MCP bridge](sight/docs/ARCHITECTURE.md) requires an owner session, CSRF proof and a separate one-use approval for each tool call. External MCP transports and cross-device listeners are disabled. Hermes guidance is indexed without executing or installing its instructions.

Owner data, model weights, credentials and `.venv` are excluded from the portable ZIP. Phase 4 and personal wake-word enrollment have not begun.
'''.replace('\\\\','\\'))
    write(PHASE/'PLAN.md','''# Phase 3 test plan and scope

Detected workspace: original manual/PDF and HTML, eight extracted reference repositories, preserved Phase 1 and Phase 2, separate Phase 3 build.

1. Hash/reconcile every supplied file and all 77 manual references; enumerate Python AST functions and other-language declaration candidates; reconcile 211 Hermes catalog skills plus plugin manifests. Distinguish inventory from complete semantic review or executable functionality.
2. Preserve existing inference, provider limits, memory, Forge, task checkpoints and exact original home UI. Add typed local adapters with one-use approvals and bounded workers.
3. Validate every enabled family through actual local operations; test unavailable hardware via explicitly labeled contracts. Keep remote accounts/devices default-off.
4. Exercise malformed arguments, scope denial, stale approval/replay, artifact boundaries, stale device revisions, invalid print plans, disconnected fixtures, browser failure/recovery, process cancellation, corrupt skill index and schedule restart.
5. Rerun all inherited regression tests and original desktop/mobile comparisons, plus a live Windows launcher/HTTP/WebSocket/Gemma smoke. Retain failed attempts and final results.
6. Produce audit, fixes, test results and precise readiness limitations. Package the tested local scope. Do not advance to Phase 4 or owner enrollment.

Full Phase 3 certification requires remaining semantic coverage and broader required behavior. Optional/blocked statuses are not passes.
''')
    write(ROOT/'docs/PHASE3_READINESS.md',f'''# Phase 3 readiness verdict — 19 October 2026

**PARTIAL — the implemented local scope is verified; the full Phase 3 gate has not passed.**

Evidence: **{count} passed, 0 failed, 0 skipped**, {duration:.2f} seconds in the complete Windows regression run; **16 original UI comparisons with zero changed pixels**; **48/48 live Windows launcher/HTTP/WebSocket/local-tool/restart checks**; real Gemma response in {model['seconds']:.4f} seconds. No cloud inference requests or paid usage in this phase.

Available: {len(SPECS)} new reviewed local capabilities, in addition to the inherited files/desktop/learning core. Real Chromium inspection, installed Windows WAV synthesis, document/calendar/geometry artifacts, typed arithmetic, persistent in-app reminders, opt-in disk health alerts, progressive search, source skill index, and an owner-authenticated local MCP subset are tested. A durable coding-inspection operation is also available with existing task budgets and privacy propagation.

Remaining gate gaps:

1. All 21,207 files and 77 evidence paths reconcile, and 211 Hermes catalog skills plus one plugin are indexed. Python AST and other-language lexical candidates are enumerated, but cross-language semantic review is **not complete**. Sensitive files are retained restricted without parsing; source/test/vendor declarations are not all independent product capabilities. No Hermes skill has been imported as executable code or enabled merely because its Markdown exists.
2. Browser networking/CDP, broad Windows input/process/window control, folder organization/undo, rich Office/PDF conversion, and general iterative CAD remain narrower or unimplemented. Their exact dispositions are in the audit and registry, rather than presented as functioning integrations.
3. Android, home devices, printers/slicers, call/meeting accounts, camera/face, connected calendar, external MCP and remote channels have no authorized/qualified transport or device. Trust/status fixtures are not live-device acceptance. Printer profile checks are analytical fixtures, not real slicing or physical safety qualification.
4. Installed Windows TTS output is verified. Microphone/STT/barge-in and camera pipelines remain disabled. No owner voice samples were collected; wake enrollment remains a separate later gate.
5. Optional ChatGPT owner sign-in remains unverified live as in Phase 2. Earlier provider free-tier tests remain historical evidence. No new cloud requests were needed or made.
6. Fresh Windows account installation, hour-long soak, thermal/RAM/VRAM profiling and complete Phase 4 security/release qualification are outstanding. The inherited low-memory observation is not cleared by these short tests.

Phase 1 and Phase 2 remain preserved. Default Phase 3 startup is local-only. Do not label this build a completed integrated SIGHT release or begin Phase 4 on the strength of these local tests alone.
''')
    write(ROOT/'docs/PHASE3_AUDIT.md',f'''# Phase 3 architecture and capability audit

Audit date: 19 October 2026. Baseline: a separate copy of the repaired Phase 2 code; no original reference module, installer, GUI, or generated source was executed/imported. {len(baseline)} Phase 2 source files were rehashed and remain unchanged. `apps/ui/index.html` is byte-identical to its Phase 2 baseline; original CSS/body and sixteen visual states are independently tested.

## Inputs and provenance

Eight named archives contain **{inventory['files']:,} files**; all extracted file hashes match. All **77** manual paths exist. The matrix contains **{inventory['matrix_rows']:,} rows**, including source-file records, **{inventory['python_function_candidates']:,} Python AST function candidates**, **{inventory['lexical_declarations']:,} other-language declarations**, and manual references. **{inventory['duplicate_rows']:,} rows** have duplicate dispositions. These counts include tests and vendor content and are not a count of usable features.

`reports/source_inventory.csv`, `source_archives_current.json`, `capability_matrix.csv` and `phase3_inventory.json` record current evidence. The inherited `input_manifest.csv`/`hermes_provenance.json` describe an older 21,358-file audit and a cloned Hermes revision; they are historical and must not be confused with the current supplied ZIP. An additional `rea-main.zip` exists in the archive folder outside the eight repositories in this manual; it remains untouched.

Hermes has **58 built-in + 153 optional = 211 catalog skills**, plus **one Google Meet plugin SKILL.md**. Each row records path/hash, declared platform/rights, prerequisite/install indicators, network and secret indicators, unsafe operations, applicability and disabled activation. Classifications are conservative static indicators, not security certification. No Markdown is executed. MIT components are behavioral references; restricted Echo/Lite/Evo and unresolved ADA Local code remain separate, with no restricted source copied into the new implementation.

## Enabled behavior

All tool calls pass strict Pydantic schemas, existing owner session/CSRF and single-use exact-argument grants. Cloud routing is unchanged and disabled by the default launcher. The table describes the implemented behavior, not the full scope of similarly named reference components.

| Capability | Family | Implemented behavior | Permission |
|---|---|---|---|
{rows}

`coding.inspect` also runs as a pure durable job operation with per-role/tool budgets and local-only result provenance. Existing memory, Forge, original desktop allowlist and file write/read APIs remain available and regression-tested.

## Explicitly unavailable broader behavior

| Registry ID | Disposition | Actual reason |
|---|---|---|
{blocked}

The per-manual-reference matrix records narrower correspondences to existing Phase 1/2/3 modules. A path, source symbol, passing generic fixture, or available dependency never automatically becomes VERIFIED. Full semantic coverage remains false in the inventory evidence.

## Runtime controls

Artifacts use random immutable IDs, no caller paths, no symlinks/hardlinks, attachment downloads with sandbox CSP, 8 MiB per item and 200 files / 128 MiB total. HTML drafts escape text. DOCX is minimal plain-text OOXML without macros or external relationships; package/XML content is tested, but Microsoft Word visual rendering is not certified.

Offline browser inspection runs in a fresh Chromium process, with JavaScript, service workers, downloads and network disabled. It can fill local fields but never submit forms. Content is labeled untrusted. No account browser/profile is attached. A failed invocation is not automatically replayed; the next invocation starts a fresh worker. Worker cancellation kills the owned process tree; an actual parent+child test verifies cleanup.

Speech uses fixed Windows System.Speech code, passes user text as JSON data, and renders a WAV without recording, playback, cloud calls or speech-based privileged authorization. Optional speech/vision services are not boot dependencies.

Reminders use SQLite transactions, unique occurrence receipts, fixed UTC cadence, quiet-hour deferral and missed-occurrence coalescing. They deliver only in-app while SIGHT runs. Disk health alerts start off, check no faster than once per minute and notify only when state changes. No weather/flight/device values are fabricated.

Local MCP is a pinned **2025-06-18** JSON-RPC subset on the existing authenticated loopback API. Initialize/initialized, tool listing, ping and four pure tool calls are supported. Every call requires the owner-granted `actionApproval` extension documented in its schema. External MCP transports and channels are disabled. Remote-output contracts label returned data untrusted; simulator pairing has scopes, expiry, replay denial and revoke. No real device credentials or listener are created.

## Reference guidance checked

[Playwright isolated contexts](https://playwright.dev/python/docs/api/class-browser), [request routing and service-worker limits](https://playwright.dev/python/docs/api/class-browsercontext), [Microsoft System.Speech WAV output](https://learn.microsoft.com/en-us/dotnet/api/system.speech.synthesis.speechsynthesizer.setoutputtowavefile), and the [pinned MCP legacy lifecycle](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-03-26/basic/lifecycle.mdx) informed the adapters. Newer MCP protocol versions exist; this build rejects versions outside its tested subset instead of claiming universal compatibility.

Source inspection found generated Python execution in CAD, CUDA assumptions in speech, and unverified online-status language in briefing references. New SIGHT adapters replace those patterns with bounded independent behavior and truthful unavailable states. This is not a malware verdict on those repositories.
''')
    write(ROOT/'docs/PHASE3_BUG_FIXES.md','''# Phase 3 fixes and regression evidence

| Finding | Root cause and repair | Regression evidence |
|---|---|---|
| Original UI proactive notices would receive an undefined value | Backend initially returned `message`; the preserved home script reads `text`. Return both fields from the same persisted title. | `test_live_scheduler_and_truthful_briefing`; live reminder and restart smoke |
| Selected code snapshot lost the Hermes catalog | Phase 2 snapshots copied only code/UI/lock. Phase 3 also manifests and verifies its runtime skill-index JSON. | `test_release_preserves_skill_catalog_and_corrupt_index_degrades` |
| A malformed optional skill index could prevent startup | Unguarded JSON load during capability initialization. Preserve core operation and report an unavailable catalog on read/validation failure. | Same corruption test invokes a working local tool afterwards |
| JavaScript duplicate grouping could merge different bodies | The first lexical index hashed only matching declaration text. Hash full source identity plus declaration offset; a shared header is no longer enough. | Recomputed current matrix; Python uses complete AST content |
| Malformed MCP tool names could throw TypeError | Unhashable JSON values reached a set membership check. Validate name type and request IDs before dispatch. | `test_mcp_malformed_names_and_requests_are_protocol_errors` |
| Cancelled browser/speech work could outlive an HTTP task | A cancelled await alone does not terminate child processes. Bound workers and kill only their owned process trees in cleanup. | Actual parent+child cancellation test, browser failure/recovery test |
| Repeated/restarted reminders could deliver twice | Use a transaction for unique occurrence receipt plus schedule advancement; coalesce missed UTC intervals. | Once/recurring restart, quiet hours, cancellation and actual server restart tests |
| Artifact growth was unbounded | Per-item size alone did not cap accumulated output. Add count and aggregate storage limits, with explicit owner cleanup. | `test_artifact_count_limit_is_fail_closed` and path/hardlink tests |
| First live smoke harness failed before checks | httpx client had already been used before re-entering its context manager. Use explicit closing around the connected client. | Failed evidence retained as `live_phase3_20261019T085210Z.json`; subsequent complete run passed 48 checks |

No credentials were printed, embedded in artifacts, or copied into the build. No provider policies or quota ledgers were reset. Model-generated code, source skill instructions and untrusted browser content do not receive execution authority.
''')
    write(ROOT/'docs/PHASE3_TEST_RESULTS.md',f'''# Phase 3 test results — 19 October 2026

**{count} passed, 0 failed, 0 skipped in {duration:.2f} seconds.** Run: `{latest['run_id']}`. Python {results['python']}; {results['environment']}. The inherited FastAPI/Starlette httpx TestClient deprecation warning is non-failing; dependencies remain pinned and `pip check` passes.

Command from this Phase 3 root: `sight\\.venv\\Scripts\\python.exe sight\\scripts\\verify.py`.

| Test group | Passed cases |
|---|---:|
{classes}

Evidence: `reports/runs/{latest['run_id']}/junit.xml`, `pytest.log`, `results.json`, `ui_visual_diffs/`; summary at `reports/latest_test_run.json`. The suite uses isolated temporary data and provider fixtures. Real browser and installed Windows voice operations are exercised; this suite makes no real provider inference calls.

Original visual comparisons cover eight states × two viewports (1440×900 and 390×844), all **zero changed pixels**. Animations are frozen at equivalent test phases for deterministic comparison, not disabled in the product. Original CSS/body are byte-checked, and the integrated home HTML is byte-identical to Phase 2. The new capability page was tested through actual approvals/downloads, XSS text, disabled device search and mobile overflow, and its screenshots were inspected. These are separate from the original UI fidelity comparisons.

## Live Windows acceptance

`scripts/phase3_smoke.py` starts the actual root PowerShell launcher in a separate data directory, authenticates over HTTP, invokes all available local tool families, verifies returned artifact hashes, chats with the installed Gemma over WebSocket, then kills/restarts only its own server and verifies durable reminders and artifacts. **48/48 checks pass.** Evidence: `reports/live_phase3_latest.json`; dated raw copy and failed initial harness attempt remain in `Phase-3/evidence`.

Gemma: `{live['model']}`; answer `{model['answer']}`, offline, **{model['seconds']:.4f} s**. No additional cloud inference/authentication/model-list requests were made in this phase. Phase 2's real Groq/Gemini/OpenRouter free-tier evidence remains preserved and is not relabeled as a new Phase 3 test.

| Live operation | Observed seconds |
|---|---:|
{timing_rows}

Each timing is one local smoke sample, including approval/HTTP overhead where applicable. These are not p95/throughput/soak qualifications. No new thermal, sustained RAM/VRAM, microphone or printer benchmark is claimed.

## Fault and permission coverage

Tests cover absent/changed/replayed grants, cross-origin/CSRF denial, invalid schemas, traversal/hardlinks, no source execution, HTML/OOXML injection handling, timezone/event-line escaping, independently checked STL manifold edges/orientation/volume, bounded numeric inputs, missing browser fields followed by recovery, actual worker-child cancellation, reminder duplicate prevention/quiet hours/cancellation, monitor off/dedup, MCP negotiation/approval/replay/malformed input, stale device revision, expiry/revoke, invalid printer dimensions/profile and simulated disconnect/denial.

Hardware results are explicit: home/Android/printer mock state/contracts are simulated; camera/call fixtures cover trust/status only. The separate MCP client contract and actual owner-local MCP bridge are tested, while external MCP servers and all physical peripherals remain unverified. A generic fixture is not counted as completed live hardware behavior.
''')
    write(ROOT/'docs/ARCHITECTURE.md','''# SIGHT Phase 3 architecture

One FastAPI loopback backend retains the Phase 2 model router, OS vault, quota ledger, SQLite core/learning stores, Forge DSL and durable job runner. `api.py` mounts `Capabilities`, its scheduler and the owner-local MCP bridge. The home HTML is preserved; Systems links to `capabilities.html`.

Discovery: `GET /api/capability/search?q=...` returns bounded summaries without schemas. `GET /api/capability/describe/{id}` returns one typed schema. `GET /api/capability/skills` searches the non-executing Hermes index. `GET /api/capabilities` includes actual blocked reasons.

Invocation: prepare `/api/capability/invoke` with `{id, arguments}` through `/api/actions/prepare`, review the normalized arguments, then POST them with the one-use `actionApproval`. Session, CSRF, expiry, exact payload and replay checks apply before execution. Artifacts are available through authenticated attachment endpoints. The service permits one local capability at a time; browser/speech workers have a 22-second outer timeout and cleanup of their own child tree. There is no generated-code interpreter or arbitrary shell adapter.

`local_adapters.py` contains pure bounded transformations. `artifacts.py` handles immutable private files. `proactive.py` adds reminders and notification receipts to the core SQLite database; existing core backup includes these tables, while generated artifact files and brain.sqlite3 retain separate backup scopes. Quiet hours and recurrence use explicit UTC semantics. `coding.inspect` is a pure durable operation; its result remains local during later model steps.

`POST /api/mcp` is an owner-local JSON-RPC tool bridge pinned to protocol 2025-06-18. It uses the same owner cookie and CSRF header, with initialize/notifications-initialized before discovery/calls. Only coding.inspect, circuit.ohm, geo.distance and vision.landmarks are exposed. Tools include `actionApproval` in their input schemas. Obtain that proof through the ordinary review flow for `/api/capability/invoke`; a call consumes it once. No remote transport, stdio command discovery, unauthenticated LAN listener, model-granted proof, or automatic approval is available. This is a documented local subset/extension, not universal MCP interoperability.

`connector_contracts.py` is transport independent. Simulators use ephemeral token hashes, five-minute expiry, scopes, request replay denial and revocation. Home/Android/printer fixtures additionally exercise state and print-plan validation. Camera/call status fixtures do not implement real audio/vision pipelines. See the [readiness gaps](PHASE3_READINESS.md).

Code snapshots now include the hashed Hermes runtime index. Runtime data is never rewound with code rollback. Corrupt/missing skill metadata disables that catalog without disabling other local tools.
''')
    write(ROOT/'docs/START_HERE.md','''# Start SIGHT Phase 3

Use the [workspace launch instructions](../../README.md). Phase 3 uses its own data directory and port 8083. Open Systems → Open capabilities for local tools or Learning for preserved memory/Forge/tasks.

Read the [Phase 3 readiness verdict](PHASE3_READINESS.md) before enabling optional integrations. Default operation remains local-only and $0. Remote devices, camera/microphone capture and owner wake-word enrollment remain disabled.
''')
    for name in ('PHASE2_AUDIT.md','PHASE2_BUG_FIXES.md','PHASE2_READINESS.md','PHASE2_TEST_RESULTS.md'):
        path=ROOT/'docs'/name;old=path.read_text(encoding='utf-8')
        if not old.startswith('> Historical'):write(path,'> Historical Phase 2 evidence, preserved for context. Statements about later phases describe that earlier handoff. See [current Phase 3 readiness](PHASE3_READINESS.md).\n\n'+old)
    root_start=WORKSPACE/'START_HERE.md';previous=root_start.read_text(encoding='utf-8')
    if not previous.startswith('# SIGHT Phase 3'):
        write(root_start,'# SIGHT Phase 3\n\nThe separate local-capability build is available. **Full Phase 3 readiness remains PARTIAL.** [Launch instructions](Phase-3/README.md) · [readiness](Phase-3/sight/docs/PHASE3_READINESS.md) · [test results](Phase-3/sight/docs/PHASE3_TEST_RESULTS.md). Phase 1 and Phase 2 are preserved below.\n\n'+previous)
    evidence={'verdict':'PARTIAL','tests':latest['counts'],'seconds':duration,'live_checks':len(live['checks']),'original_ui_zero_difference_cases':len(visual),'available_local_capabilities':len(SPECS),'blocked_broader_capabilities':len(BLOCKED),'cloud_calls':0,'source_semantic_complete':False,'phase4_started':False}
    write(ROOT/'reports/phase3_readiness.json',json.dumps(evidence,indent=2));print(json.dumps(evidence,indent=2))

if __name__=='__main__':main()
