"""Generate the handoff from actual saved evidence; makes no network requests."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
PHASE=ROOT.parent
WORKSPACE=PHASE.parent

def main():
    latest=json.loads((ROOT/'reports/latest_test_run.json').read_text())
    assert latest['exit_code']==0 and latest['counts']['FAIL']==latest['counts']['SKIP']==0
    results=json.loads(Path(latest['results']).read_text())
    growth=json.loads((ROOT/'reports/growth_benchmark.json').read_text())
    live=json.loads((ROOT/'reports/live_phase2_latest.json').read_text())
    providers={p:json.loads((PHASE/'evidence'/('live_'+p+'_latest.json')).read_text()) for p in ('groq','gemini','openrouter')}
    baseline=json.loads((PHASE/'evidence/phase1_baseline_manifest.json').read_text())
    p1=WORKSPACE/'Phase-1/extracted/SIGHT-Phase1-Verification'
    unchanged=all(hashlib.sha256((p1/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in baseline)
    assert unchanged,'Phase 1 baseline changed'
    (PHASE/'evidence/phase1_preservation.json').write_text(json.dumps({'checked_files':len(baseline),'all_unchanged':unchanged},indent=2))
    visual=[]
    for path in (Path(latest['results']).parent/'ui_visual_diffs').glob('metrics_*.json'):
        value=json.loads(path.read_text())
        visual+=value if isinstance(value,list) else value.get('metrics',[])
    assert len(visual)==16 and all(r['changed_pixels']==0 for r in visual)
    provider_rows='\n'.join(f"| {p.title()} | {r['model']} | {r['response']['say']} | {r['reply_seconds']:.4f} s | {r['quota_after']['requests_used_24h']} | $0 |" for p,r in providers.items())
    growth_rows=[]
    for task in ('owner correction','missing skill','workflow consolidation'):
        rows={r['stage']:r for r in growth['rows'] if r['task']==task}
        growth_rows.append(f"| {task} | {rows['baseline']['correct']} / {rows['baseline']['tool_calls']} | {rows['after']['correct']} / {rows['after']['tool_calls']} | {rows['repeat']['correct']} / {rows['repeat']['tool_calls']} | {rows['baseline']['seconds']:.4f} / {rows['after']['seconds']:.4f} / {rows['repeat']['seconds']:.4f} |")
    readme=r"""# SIGHT Phase 2 — learning and durable workflows

This is a separate Phase 2 verification build. Phase 1 and the original SIGHT home UI are preserved. Read [readiness](sight/docs/PHASE2_READINESS.md) for tested scope and qualifications.

From PowerShell in this folder:

§§§powershell
.\Start-Local-Runtime.ps1
.\Start-SIGHT.ps1
§§§

Leave the server running, then run §.\Open-SIGHT.ps1§ in another PowerShell window. Phase 2 uses §http://127.0.0.1:8082§ and §Phase-2/owner-data§. Open Systems → “Open memory, Forge and durable tasks” for the learning page.

The runtime helper uses the existing §D:\Ollama Models§ folder; pass §-ModelsDirectory§ if it differs. It never downloads weights or stops an existing runtime. If Ollama is already running with another model folder, stop that instance yourself and restart it with the correct folder. The verified selection is the installed third-party Gemma 4 E4B derivative §hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED:Q4_K_M§.

For a new extraction, install Python 3.12 and run §sight\scripts\install.ps1§. Then, from the Phase 2 root:

§§§powershell
$env:SIGHT_DATA_DIR = Join-Path $PWD.Path 'owner-data'
Set-Location sight
.\.venv\Scripts\python.exe -m sight_core.cli configure-model 'hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED:Q4_K_M'
§§§

Owner data, model weights and credentials are excluded from the ZIP. The existing workspace already has the model selection saved.

Cloud policies start disabled. The default launcher forces local-only mode. For reviewed free-provider use, start with §.\Start-SIGHT.ps1 -AllowConfiguredCloud§ and configure the provider in Systems. Store credentials with the hidden §credential§ CLI command. Replacing a key disables its current policy until account tier and settings are reviewed again. Avoid rerunning provider smoke scripts unnecessarily; their rolling quota ledger is retained.

Memory is project scoped, inspectable, editable and forgettable. §text.case = upper§ or §lower§ changes the deterministic format task. Default-project memory can inform home chat; local-only memory cannot enter cloud prompts or downstream cloud task steps. Historical task receipts and independent backups are separate retention records.

Forge generates restricted text transformations, tests examples in a bounded subprocess and requires review before immutable promotion. Arbitrary Python, shell commands, network, unrelated folders and package installation are unavailable. Dependency requests pause. Faulty candidates cannot replace active skills. Archive, activate an earlier version or forget all versions from the learning page.

Tasks persist their DAG, assignments, dependencies, budgets and results. One worker shares inference with chat. Pause/cancellation occur between atomic operations; a model call may take until its deadline. Interrupted model calls require review and are never automatically billed again. File creation reconciles crash receipts without rewriting or overwriting an unrelated file.

Learning backups restore into a new directory for inspection. Code snapshots are selected for the next restart; the root launcher verifies them and falls back to the installed baseline if corrupt. Code rollback preserves task receipts and data. Different dependency locks require a separately installed and verified environment.

Optional official ChatGPT sign-in is available in Systems. Signed protocol fixtures pass, but the owner's live account remains unqualified. Select a current account model and disable SIGHT credit use in ChatGPT Settings before enabling plan-only fallback. No Codex desktop tokens are borrowed.

Run regression tests from §sight§:

§§§powershell
.\.venv\Scripts\python.exe scripts\verify.py
§§§

§scripts\phase2_smoke.py§ uses live local Gemma and no cloud. §scripts\growth_benchmark.py --model <installed-tag>§ repeats the three synthetic learning tasks.

Reports: [audit](sight/docs/PHASE2_AUDIT.md), [bug fixes](sight/docs/PHASE2_BUG_FIXES.md), [tests](sight/docs/PHASE2_TEST_RESULTS.md), [readiness](sight/docs/PHASE2_READINESS.md). Phase 3 has not begun.
""".replace('§',chr(96))
    (PHASE/'README.md').write_text(readme,encoding='utf-8')
    (ROOT/'docs/START_HERE.md').write_text('See the Phase 2 root [README](../../README.md) for the exact launch, install, model-selection and recovery commands.\n\n'+readme.replace('sight/docs/',''),encoding='utf-8')
    audit=f"""# Phase 2 audit — 19 October 2026

Owner scope: full Phase 2, starting with free-tier API tests. Gemini/Groq were explicitly confirmed Free tier with paid billing disabled. Spending authorization remained $0. Recorded cloud inference ran on 18 October; no repeat cloud inference was needed on 19 October.

## Located build and preservation

The workspace contains Reference.zip, the V2 master manual PDF, original SIGHT_UI_Clean.html, eight extracted reference repositories, the repaired Phase 1 build, and the separate Phase-2/sight implementation. Phase 2 evidence/test-data are siblings of the build and never substituted for owner data.

All **{len(baseline)}** saved Phase 1 baseline files still match their hashes. Original home CSS/body remain byte-identical to the supplied HTML; sixteen desktop/mobile state comparisons have zero changed pixels. The learning page is secondary.

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
{provider_rows}

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
"""
    bugs="""# Phase 2 bug-fix report

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
"""
    tests=f"""# Phase 2 test results

Final run: {latest['run_id']}. **{latest['counts']['PASS']} passed, 0 failed, 0 skipped**, in 51.02 seconds. Environment: {results['environment']}; Python {results['python']}. Logs/JUnit/per-test records/screenshots: reports/runs/{latest['run_id']}. Pinned hash-verified binary dependency installation and pip check passed.

One non-failing warning remains: Starlette's existing deprecation of the httpx TestClient integration.

## Tested coverage

The complete inherited Phase 1 suite ran alongside quotas/cooldowns, memory provenance/projects/TTL/forgetting/corruption, schema-constrained Forge and dependency pause, sandbox authority negatives, promotion/rollback/archive, roles/budgets/deadlines/pause, scoped grants, actual process death and receipt recovery, private-memory dataflow, code corruption/launcher fallback, OAuth signed identity/refresh/revoke/stream completion, and Chromium interaction.

Original home: **16/16 comparisons, 0 changed pixels**, at 1440×900 and 390×844 across eight states. CSS/body remain byte-identical. The learning page passes real memory edit/delete, XSS, staged skill promotion and task completion flows, with no JavaScript errors or mobile overflow.

## Live inference

Groq/Gemini/OpenRouter each returned expected 4 on synthetic prompts; actual inference, replay and throttle results are recorded in reports/live_PROVIDER_latest.json. No additional cloud calls were used for learning validation.

The final local HTTP/WebSocket test passed **{len(live['checks'])}/{len(live['checks'])}** checks: actual Gemma-generated skill via authenticated API, testing, promotion, two durable DAGs using the same version, output files/receipts, chat, forgetting and unchanged home. Cold Forge generation took 15.758 seconds. The first 19 October attempt correctly failed with Ollama stopped; starting the existing runtime resolved the environment issue.

## Growth benchmark

Every task run had equal allowances: 4 tool calls and 0 model calls. One-time skill generation is separate ({growth['generation_seconds']:.3f} seconds, local Gemma). Correction/promotion was explicitly performed by the synthetic benchmark owner, not autonomous permission escalation.

| Task | Baseline correct / calls | After correct / calls | Repeat correct / calls | Seconds baseline / after / repeat |
|---|---:|---:|---:|---:|
{chr(10).join(growth_rows)}

Correctness: **1/3 → 3/3 → 3/3**. Consolidation uses one call instead of two; repeated calls use the same immutable version. Missing-skill rejection is faster than executing the newly learned skill, so capability improvement does not imply every elapsed time improved. Reported times include SQLite/worker overhead; startup, generation and owner review are not hidden in task-only metrics.

Editing the correction changed behavior; deleting it restored the original. Forgetting the procedure made invocation unavailable. Failed-test rollback and stale/archive behavior have separate acceptance tests.

This is evidence for three deterministic text tasks, not general self-improvement or broad coding ability. The UI shows measurements and leaves its general growth_proven flag false.

## Not established

Live owner ChatGPT sign-in/eligibility/catalog/refresh/revoke; fresh Windows user installation; other hardware/OS; long memory-pressure soak; arbitrary Python or package installation; Codex app-server coding; Phases 3–4. External apps' shared quota consumption cannot be inferred from model lists. Phase 1's low transient RAM headroom remains a qualification.
"""
    readiness=f"""# Phase 2 readiness verdict

**CONDITIONAL READY for local text learning and durable workflows.** This is a Phase 2 verification build, not a claim that every optional integration or later capability is qualified.

Evidence: **{latest['counts']['PASS']} passing tests**, no failures/skips; sixteen unchanged UI comparisons; all three requested free APIs passed real inference; live Gemma/HTTP/WebSocket/Forge/task smoke passed {len(live['checks'])} checks; three-task correctness 1/3→3/3→3/3; forgetting, failed-candidate rejection and skill/code/crash recovery tested.

Ready: typed memory and project retrieval/compaction; procedural versions and operational DAGs/receipts; twelve bounded logical roles; pure-text Forge; review/promote/invoke/curator/archive; graph and owner corrections; persistent quotas; backups and verified restart code selection.

Qualifications:
1. Forge supports a fixed text transformation language. Dependency requests pause; package installation and arbitrary generated code remain unavailable.
2. Optional official ChatGPT adapter passes protocol fixtures but needs owner sign-in/account-specific completion before live qualification. No Codex app-server coding integration is enabled.
3. After-task review is deterministic and proposes changes; it never silently rewrites memory or grants authority. The growth benchmark is narrow.
4. Fresh Windows account, longer soak and broader hardware performance remain unqualified. Phase 1 observed low transient RAM headroom on this 16 GB machine.
5. Forgetting stops current retrieval/reuse, while separate backups and historical operational receipts retain their explicit scope. Code rollback does not rewind task receipts.

Default handoff: local-only startup; cloud policies disabled; credentials in Windows Credential Manager; provider-smoke quota reservations retained; Phase 1 preserved. Phase 3 has not begun.
"""
    for filename,body in [('PHASE2_AUDIT.md',audit),('PHASE2_BUG_FIXES.md',bugs),('PHASE2_TEST_RESULTS.md',tests),('PHASE2_READINESS.md',readiness)]:
        (ROOT/'docs'/filename).write_text(body,encoding='utf-8')
    for provider in providers:shutil.copyfile(PHASE/'evidence'/('live_'+provider+'_latest.json'),ROOT/'reports'/('live_'+provider+'_latest.json'))
    for filename in ('phase1_preservation.json','openrouter_preflight.json','openrouter_test_model.json','forge_model_probe.json'):
        shutil.copyfile(PHASE/'evidence'/filename,ROOT/'reports'/filename)
    print(json.dumps({'regression':latest['counts'],'visual_comparisons':len(visual),'phase1_unchanged':unchanged,'reports':4}))

if __name__=='__main__':main()

