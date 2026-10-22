"""Assemble readiness from actual artifacts; missing or partial evidence never passes."""
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports'
DOCS = ROOT / 'docs'


def read(name):
    path = REPORTS / name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def measured(value):
    return round(value, 3) if isinstance(value, (int, float)) else 'pending'


def main():
    report_date = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime('%d %B %Y')
    tests = read('latest_test_run.json')
    run = read('runs/' + tests.get('run_id', 'missing') + '/results.json')
    soak = read('soak_latest.json')
    progress = read('soak_progress.json')
    # Never present an older completed run as the currently running soak.
    current_soak_path = Path(progress.get('evidence', '.')) / 'result.json'
    if current_soak_path.is_file():
        soak = json.loads(current_soak_path.read_text(encoding='utf-8'))
    live = read('live_phase4_latest.json')
    growth = read('growth_benchmark.json')
    if growth.get('model') != 'sight-gemma4-e4b:uncensored' or not growth.get('run_manifest'):
        growth = {}
    install = read('offline_install_latest.json')
    dependencies = read('dependency_audit.json')
    runtime = read('runtime_inventory.json')
    followup = read('phase4_followup.json')
    integrity = read('gemma_weight_integrity.json')
    prompt_eval = read('gemma_prompt_eval.json')
    memory = read('memory_integrity_followup.json')
    model_switch = read('official_model_switch.json')
    selected_model = model_switch.get('selected', {}).get('model', 'sight-gemma4-e4b:uncensored')
    official_selected = selected_model == 'gemma4:e4b-it-qat'
    reconciliation = read('phase4_reconciliation.json')
    current_sources = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                       for folder in ('sight_core', 'apps') for p in sorted((ROOT/folder).rglob('*'))
                       if p.is_file() and '__pycache__' not in p.parts}
    for name in ('requirements.lock', 'requirements-bootstrap.lock', 'scripts/launch.py', 'scripts/soak_worker.py'):
        current_sources[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    recorded_sources = soak.get('source_hashes', {})
    changed_sources = sorted(name for name in current_sources.keys() | recorded_sources.keys()
                             if current_sources.get(name) != recorded_sources.get(name))
    dependencies_match = dict((d.metadata['Name'], d.version) for d in distributions()) == soak.get('dependency_versions')
    soak_model_matches = soak.get('model') == selected_model
    soak_current = bool(recorded_sources) and not changed_sources and dependencies_match and soak_model_matches
    soak_scope = {'checked_utc': datetime.now(timezone.utc).isoformat(),
                  'recorded_run_started_utc': soak.get('started_utc'),
                  'historical_one_hour_qualified': soak.get('one_hour_qualified', False),
                  'current_runtime_matches': soak_current, 'changed_sources': changed_sources,
                  'dependencies_match': dependencies_match,
                  'selected_model': selected_model, 'model_matches': soak_model_matches,
                  'current_runtime_hashes': current_sources,
                  'status': 'PASS_RUNTIME_SCOPE' if soak_current and soak.get('one_hour_qualified') else 'REVALIDATION_REQUIRED'}
    (REPORTS/'soak_current_scope.json').write_text(json.dumps(soak_scope, indent=2), encoding='utf-8')
    passed = {row['id'] for row in run.get('tests', []) if row['status'] == 'PASS'}
    checks = []
    def gate(identifier, status, evidence, limit=''):
        checks.append({'id': identifier, 'status': status, 'evidence': evidence, 'limit': limit})
    def unit(identifier, names, limitation=''):
        okay = all(any(item == name or item.startswith(name + '[') for item in passed) for name in names)
        gate(identifier, 'PASS_BOUNDED' if okay else 'MISSING', names, limitation)
    unit('test_ui_visual_parity', ['test_ui_visual_parity'], 'Eight frozen animation states, two viewports; not every animation frame.')
    unit('test_html_route_compatibility', ['test_html_route_compatibility'])
    unit('test_local_first_boot', ['test_local_first_boot'])
    # Test identifiers in this implementation differ from the manual's gate labels.
    router_tests = [name for name in sorted(passed) if 'fallback' in name or 'failover' in name]
    gate('test_model_router_failover', 'PASS_FIXTURES' if router_tests else 'MISSING', router_tests,
         'No new cloud inference. Optional live ChatGPT sign-in is unverified.')
    unit('test_kanban_restart_exactly_once', ['test_task_dag_budgets_idempotency_and_receipts', 'test_file_crash_recovery_real_process'])
    unit('test_memory_search_source_links', ['test_memory_provenance_project_privacy_and_forgetting'])
    unit('test_memory_delete_propagation', ['test_memory_correction_changes_task_then_forget_removes_effect'],
         'Active retrieval and derived summaries only; independent historical task records/backups are not erased.')
    unit('test_memory_atomic_compaction', ['test_compaction_graph_failure_rolls_back_summary_fts_and_event',
         'test_process_crash_during_compaction_leaves_no_orphan', 'test_compaction_is_not_visible_before_source_links_commit',
         'test_concurrent_source_privacy_correction_removes_committed_summary'])
    unit('test_memory_filtered_search_and_lineage', ['test_hidden_matches_do_not_consume_search_limit',
         'test_deep_summary_lineage_is_readable_and_forgettable', 'test_cyclic_summary_lineage_is_unavailable_without_recursion_error',
         'test_legacy_orphan_summary_is_preserved_but_not_retrieved'])
    unit('test_background_review_audit', ['test_skill_curator_archive_restore_and_owner_delete'],
         'Explicit curator review; not a general autonomous learning auditor.')
    unit('test_skill_curator_archive_restore', ['test_skill_curator_archive_restore_and_owner_delete'])
    unit('test_forge_missing_skill', ['test_forge_promote_reuse_failed_candidate_rollback_forget'],
         'Declarative text skills only; fresh live generation quality is recorded separately.')
    unit('test_forge_rollback_unsafe_update', ['test_forge_promote_reuse_failed_candidate_rollback_forget', 'test_sandbox_rejects_authority_escalation'])
    summary = growth.get('summary', {})
    gate('test_growth_before_after', 'HISTORICAL_OTHER_MODEL' if growth.get('model') != selected_model else 'PASS_BOUNDED' if summary.get('after_correct') == summary.get('repeat_correct') == 3 else 'PENDING',
         ['reports/growth_benchmark.json'], 'Three deterministic text tasks; authored fallback is distinguished from model generation.')
    gate('live_forge_generation', 'HISTORICAL_OTHER_MODEL' if growth.get('model') != selected_model else 'PASS_BOUNDED' if growth.get('promotion_origin') == 'model_generated' else 'FAIL' if growth else 'PENDING',
         ['reports/growth_benchmark.json'],
         'One model-generated declarative text skill; not general code generation.' if growth.get('promotion_origin') == 'model_generated' else
         'A tested harness-authored fallback demonstrates promotion/reuse but does not pass model skill generation.')
    unit('test_tool_search_resolution', ['test_progressive_discovery_and_skills'])
    unit('test_remote_pair_revoke', ['test_device_trust_scopes_expiry_replay_and_revoke'], 'Contract simulation only; no remote device transport.')
    unit('test_printer_adapter_negotiation', ['test_printer_profile_build_volume_and_home_revision_guard'], 'Analytical contract only; no slicing or printing.')
    unit('test_sentinel_defence_only', ['test_quiet_hours_defer_and_health_change_dedup'], 'Local disk-health observations only; no broader defensive sentinel.')
    unit('test_voice_consent_toggle', ['test_voice_consent_toggle'], 'Consent-state and unavailable-backend behavior; microphone/STT remains absent.')
    gate('test_wake_enrollment_calibration', 'BLOCKED', [], 'No enrollment; voice backend and owner-specific enrollment gate are absent.')
    unit('test_memory_backup_restore', ['test_memory_backup_restore_full_data_and_safe_start'])
    unit('test_untrusted_content_is_data', ['test_zip_readme_and_python_top_level_never_execute_during_inventory',
                                          'test_model_echo_of_untrusted_instructions_grants_no_tool_authority',
                                          'test_terminal_arguments_cannot_enter_allowlisted_desktop_action'])
    unit('test_runtime_launcher_readiness', ['test_runtime_launcher_reports_readiness_not_process_creation'],
         'Delayed readiness, early exit and existing-listener decisions use PowerShell fixtures; direct Ollama execution is separate live evidence.')
    unit('test_runtime_portable_paths', ['test_runtime_portable_paths_and_parent_environment'],
         'Nine PowerShell fixture scenarios; live existing-runtime and direct CLI checked separately. Not a fresh-account installation.')
    gate('uncensored_weight_integrity', 'PASS' if integrity.get('passed') else 'UNVERIFIED',
         ['reports/gemma_weight_integrity.json'], 'Full model/projector hashes match the recorded publisher revision; no quality certification.')
    if official_selected:
        unit('official_model_sampling_and_launcher', ['test_official_model_does_not_inherit_derivative_sampling', 'test_direct_helper_selects_normal_gemma'],
             'Provider HTTP and PowerShell fixtures only; official live inference is pending.')
        gate('official_model_file_integrity', 'PASS' if model_switch.get('all_blob_hashes_valid') else 'UNVERIFIED',
             ['reports/official_model_switch.json'], 'Complete local blob hashes; no inference-quality certification.')
    unit('test_sandbox_exfiltration_denial', ['test_sandbox_rejects_authority_escalation', 'test_forge_manifest_rejects_dependencies_network',
                                          'test_browser_real_chromium_blocks_network_scripts_and_recovers'],
         'Bounded interpreter and isolated offline browser; no arbitrary-code OS sandbox claim.')
    unit('test_browser_native_sandbox_enabled', ['test_untrusted_html_browser_does_not_disable_native_sandbox'],
         'Real Chromium command-line check and HTML rendering; not a sandbox-escape assessment.')
    gate('one_hour_soak', soak_scope['status'],
         ['reports/soak_latest.json', 'reports/soak_current_scope.json'],
         'A historical completed hour qualifies the current runtime only when all covered source hashes and dependency versions still match. Reasoning is a separate gate.')
    gate('local_model_reasoning_quality', 'UNVERIFIED' if official_selected else 'FAIL',
         ['docs/OFFICIAL_GEMMA.md' if official_selected else 'docs/GEMMA_REPAIR.md'],
         'The official model is selected but could not be tested live because Ollama is absent. The prior uncensored quality failures remain historical.' if official_selected else 'Repeated arithmetic, logic and coherence failures remain.')
    gate('fresh_windows_account_install', 'UNVERIFIED', ['reports/offline_install_latest.json'],
         'Fresh directory/venv on the current account, preinstalled Python and provisioned browser cache.')
    gate('complete_semantic_source_coverage', 'INCOMPLETE', ['reports/phase4_reconciliation.json'],
         'All files reconciled; full cross-language unique-feature review is not complete.')
    gate('external_binary_advisory_coverage', 'INCOMPLETE', ['reports/runtime_inventory.json'],
         'PyPI OSV scan does not cover every OS/browser/CUDA/runtime binary.')
    acceptance = {'updated_utc': datetime.now(timezone.utc).isoformat(), 'phase': 4, 'verdict': 'PARTIAL',
                  'regression_run': tests.get('run_id'), 'checks': checks,
                  'final_release_tag_created': False, 'owner_enrollment_started': False,
                  'cloud_inference_requests_in_phase4': 0}
    (REPORTS/'phase4_acceptance.json').write_text(json.dumps(acceptance, indent=2), encoding='utf-8')
    metrics = []
    for path in (REPORTS/'runs'/tests.get('run_id', 'missing')/'ui_visual_diffs').glob('metrics_*.json'):
        metrics += json.loads(path.read_text())
    counts = tests.get('counts', {})
    telemetry = soak.get('telemetry', {})
    soak_line = ('PASS for the bounded runtime soak' if soak.get('one_hour_qualified') and soak_current else
                 'HISTORICAL PASS; current runtime requires a new full soak' if soak.get('one_hour_qualified') else
                 'PENDING/FAILED — not a one-hour pass')
    history = []
    for path in sorted((ROOT.parent/'evidence').glob('soak-*/result.json')):
        old = json.loads(path.read_text(encoding='utf-8'))
        status = ('Qualified runtime pass' if old.get('one_hour_qualified') else
                  'Short harness run' if old.get('complete') else
                  'ABORTED: ' + old['abort_reason'] if old.get('abort_reason') else
                  'FAILED check: ' + old['error'] if old.get('error') else
                  'In progress or interrupted; not qualified')
        history.append(f"| [{path.parent.name}](../../evidence/{path.parent.name}/result.json) | "
                       f"{old.get('requested_seconds', 0)} / {old.get('elapsed_seconds', 0)} | "
                       f"{old.get('thinking', 'automatic')} | {old.get('cycles', 0)} | {status} |")
    soak_history = '\n'.join(history)
    body = f"""# Phase 4 test results — {report_date}

**Release verdict: PARTIAL.** Test results below describe their actual scope.

Selected model: **{selected_model}**. Official model selection, file integrity and the live-runtime blocker are recorded in [official model status](OFFICIAL_GEMMA.md). Live/quality/growth/soak records below name their original models; uncensored results do not qualify the newly selected official model.

| Check | Recorded result | Evidence |
| --- | --- | --- |
| Full Windows regression suite | {counts.get('PASS', 0)} passed; {counts.get('FAIL', 0)} failed; {counts.get('SKIP', 0)} skipped | [Current run](../reports/runs/{tests.get('run_id', 'missing')}/results.json), [raw pytest log](../reports/runs/{tests.get('run_id', 'missing')}/pytest.log) |
| Original UI comparison | {len(metrics)} comparisons; {sum(row['changed_pixels'] for row in metrics)} changed pixels | Current run's `ui_visual_diffs` directory |
| Final hardening/routing/recovery subset | See raw JUnit; superseded for release purposes by the complete suite | [JUnit](../../evidence/hardening_final.xml) |
| Last recorded live Windows launcher, HTTP, WS and local adapters | model={live.get('model', 'unknown')}; complete={live.get('complete', False)}; passed={live.get('passed', False)}; {sum(bool(row['passed']) for row in live.get('checks', []))}/{len(live.get('checks', []))} checks | `reports/live_phase4_latest.json` |
| One-hour soak | {soak_line}; requested={soak.get('requested_seconds', 0)} s, observed={soak.get('elapsed_seconds', 0)} s; cycles={soak.get('cycles', 0)} | [Current result](../reports/soak_latest.json); progress artifact while running |
| Offline fresh venv installation | complete={install.get('complete', False)}; {install.get('seconds', 0)} s; {install.get('wheel_count', 0)} local wheels | [Install result](../reports/offline_install_latest.json) |
| Dependency OSV scan | complete={dependencies.get('scan_complete', False)}; {len(dependencies.get('dependencies', []))} distributions; {len(dependencies.get('vulnerabilities', []))} advisory findings | [Scan](../reports/dependency_audit.json) |
| Reference archives | {reconciliation.get('file_entries', 0)} files; {reconciliation.get('all_archive_entries', 0)} total entries; {reconciliation.get('extracted_file_hash_matches', 0)} matching extracted file hashes | [Reconciliation](../reports/phase4_reconciliation.json) |
| Growth: baseline / after / repeated | {summary.get('baseline_correct', 'pending')} / {summary.get('after_correct', 'pending')} / {summary.get('repeat_correct', 'pending')} correct of 3 per stage | `reports/growth_benchmark.json` |
| Live Forge generation | {growth.get('live_generation', {}).get('state', 'pending')}; promoted skill origin: {growth.get('promotion_origin', 'pending')} | [Growth evidence](../reports/growth_benchmark.json) |
| Historical direct Ollama helper | Earlier uncensored profile; non-thinking synthetic 17+25 returned 42, exit code 0 | [Direct CLI evidence](../../evidence/gemma_direct_launcher.json) |
| Startup portability follow-up | {followup.get('launcher_live_passed', 'pending')}; cold-start path/environment decisions covered by fixtures | [Follow-up](../reports/phase4_followup.json), [live helper result](../../evidence/gemma_launcher_portability_live.json) |
| Complete uncensored blob verification | passed={integrity.get('passed', False)}; {len(integrity.get('files', []))} complete files | [SHA-256 results](../reports/gemma_weight_integrity.json) |
| Paired prompt evaluation | complete={prompt_eval.get('complete', False)}; {len(prompt_eval.get('rows', []))} local requests; selected profile unchanged | [Raw answers and grading](../reports/gemma_prompt_eval.json), [interpretation](GEMMA_REPAIR.md) |
| Memory integrity follow-up | {memory.get('new_regression_cases', 'pending')} new regression cases; {memory.get('live_memory_checks_passed', 'pending')}/8 live memory checks | [Crash, concurrency and retrieval evidence](../reports/memory_integrity_followup.json), [before XML](../../evidence/memory_integrity_before.xml), [after XML](../../evidence/memory_integrity_after.xml) |
| Official model switch | selected={official_selected}; all local blob hashes valid={model_switch.get('all_blob_hashes_valid', False)}; live inference verified={model_switch.get('live_inference_verified', False)} | [Model switch](../reports/official_model_switch.json), [selection regressions](../../evidence/official_model_after.xml) |

The memory follow-up reproduced nine failing cases before repair. Its real process crash and concurrent-reader tests use SQLite, and its deep-lineage test reads/exports/deletes a 1,100-summary chain. These synthetic checks do not measure every production workload. The latest live application run also tests memory provenance across an actual launcher restart and edit/delete propagation. Live answer-quality failures remain failures: the two follow-up runs answered `29` and `1ことがある` to `2 plus 2` with synthetic memory present. The second runner completed the independent checks and returned exit code 1. No retry-until-pass or model substitution was used.

## Soak interpretation

The first 3,600-second attempt stopped after 626.047 seconds when the third Gemma request returned no final answer. It is retained as a **failed test**, not counted as an hour. [Original failed result](../../evidence/soak-20261019T140844Z-5fd335/result.json). A preliminary 25-second harness run is also not an hour.

Every attempt is retained. Runs explicitly aborted for the concurrent SQLite-journal repair and browser dependency refresh do not count toward another run's duration. Another attempt found Ollama stopped after a session gap. The final thinking-enabled attempt failed after 349.125 seconds on the output limit, with zero of two arithmetic requests correct. The selected SIGHT profile and the new soak now have thinking disabled; the checkpoint's broader quality failures remain.

| Run | Requested / observed seconds | Thinking | Completed cycles | Outcome |
| --- | --- | --- | --- | --- |
{soak_history}

The final run uses the uncensored profile (thinking={soak.get('thinking', 'automatic')}) and actual HTTP/WebSocket requests, one durable output-file job per cycle, real local inference every five cycles, scoped loopback-runtime fault injection and planned termination/restart of its own test server at cycles 10, 30 and 50. It does not disconnect the host network or kill the owner's applications. Interrupted model tasks must remain `needs_review`; completed files and receipts must persist without replay. The end-of-run full backup/restore, unchanged runtime-source hashes and unchanged installed dependency versions are mandatory for its pass.

Recorded planned server crashes: {soak.get('planned_server_crashes', 0)}; unplanned exits: {soak.get('unplanned_server_exits', 0)}. Peak GPU memory: {telemetry.get('peak_gpu_mib', 'pending')} MiB; peak GPU temperature: {telemetry.get('peak_gpu_temperature_c', 'pending')} C; minimum available host RAM: {telemetry.get('minimum_available_host_ram_mib', 'pending')} MiB; peak host CPU: {telemetry.get('peak_host_cpu_percent', 'pending')}%; peak SIGHT worker working set: {telemetry.get('peak_server_working_set_mib', 'pending')} MiB. Host RAM/CPU include other applications. Regression and offline-install checks overlapped the early part of the final soak, so these are not isolated idle-machine measurements. Live model tests were sequential. CPU temperature is unavailable through the interfaces used.

Arithmetic correctness during the historical uncensored soak: {soak.get('model_answer_correct_count', 'pending')}/{len(soak.get('model_calls', []))} recorded requests. Inference latency: median {measured(soak.get('model_latency', {}).get('median_seconds'))} s; maximum {measured(soak.get('model_latency', {}).get('max_seconds'))} s. This small repeated-prompt check does not establish general quality. Independent diagnostic prompts failed, so **uncensored reasoning quality remained FAIL even though its runtime soak passed**. Official-model reasoning is separately unverified.

The startup-helper follow-up matched the completed soak's server files at that time. The subsequent memory repair changed backend code. Current server/UI/lock/worker hashes match the completed soak: {soak_current}; changed paths: {', '.join(changed_sources) or 'none'}; installed dependency versions match: {dependencies_match}. The original hour remains historical evidence; no new hour is claimed for the memory repair. [Current comparison](../reports/soak_current_scope.json), [earlier startup verification](../reports/phase4_followup.json).

## Reproduction

From `Phase-4/sight`, using the installed Python environment:

```powershell
.\\.venv\\Scripts\\python.exe scripts\\verify.py
.\\.venv\\Scripts\\python.exe scripts\\phase4_smoke.py
.\\.venv\\Scripts\\python.exe scripts\\phase4_soak.py --seconds 3600 --model {selected_model}
.\\.venv\\Scripts\\python.exe scripts\\growth_benchmark.py --model {selected_model}
.\\.venv\\Scripts\\python.exe scripts\\offline_install_check.py
```

Run live model checks sequentially. They use synthetic data in separate test directories. Regression tests use model/provider fixtures; those fixtures do not count as real Gemma or live-provider tests. The observed Starlette/httpx deprecation warning is retained in the log; it did not fail tests.

[Acceptance map](../reports/phase4_acceptance.json) maps the manual's named gates to actual test identifiers and explicit scope limits. Simulations, missing hardware, missing owner sign-in and a current-account venv are never relabeled as real integration or fresh-account passes.
"""
    (DOCS/'PHASE4_TEST_RESULTS.md').write_text(body, encoding='utf-8')
    verdict = f"""# Phase 4 readiness verdict — {report_date}

**PARTIAL — the hardened local build is reviewable; the complete integrated-release gate has not passed.**

The current regression run has **{counts.get('PASS', 0)} passes, {counts.get('FAIL', 0)} failures and {counts.get('SKIP', 0)} skips**. Original-UI comparisons report {sum(row['changed_pixels'] for row in metrics)} changed pixels across {len(metrics)} comparisons. The current soak status is **{soak_line}**. [Detailed test results](PHASE4_TEST_RESULTS.md).

Available repairs include stronger Windows file/database/snapshot boundaries, atomic memory compaction with consistent retrieval and source validation, portable runtime discovery with caller-environment restoration, bounded Ollama responses, redacted transport logs, complete local-data backup/restore, an offline installer path, and the updated browser with its native sandbox explicitly enabled. Existing local tools, typed durable tasks, Forge and the exact UI remain preserved. The selected model is **{selected_model}**, initially with thinking disabled.

Remaining gaps and unverified items:

1. **The official Gemma model needs live verification.** Its download and complete blob hashes are verified, but the Ollama executable is currently absent and no official inference comparison has run. The previous uncensored model's reasoning failed. Its earlier Forge/growth and soak results do not qualify the official model. [Official model status](OFFICIAL_GEMMA.md), [historical uncensored evidence](GEMMA_REPAIR.md).
2. **Fresh Windows account installation is unverified.** The offline test used a new venv/data directory on the current account with Python and Chromium already provisioned.
3. **Complete semantic source coverage is incomplete.** Every supplied file has a disposition and hash, but symbol indexing is not exhaustive unique-feature analysis.
4. **Broader integrations remain partial or blocked.** Remote browsing/CDP, broad Windows input, folder organization, rich document conversion, external devices/accounts/MCP, microphone/STT/camera and general CAD are not certified by local adapters or simulated contracts.
5. **External binary advisory coverage is incomplete.** The recorded PyPI scan does not clear all Windows, GPU, Ollama and Chromium components.
6. **Optional ChatGPT owner sign-in and wake enrollment have not been performed.** No owner voice samples or external account changes were made.
{'' if soak_current else '7. **The changed backend and official model need a new full-duration soak.** The previous 3,601-second pass applies to the earlier runtime and uncensored model. No new one-hour qualification is claimed.'}

The owner-selected $0/free-tier policy remains intact; Phase-4 made zero cloud inference requests. Earlier provider successes remain historical evidence. Earlier phase packages and the Phase-3 baseline are checked again during final packaging.

No `sight-v1-integrated` tag, deployment or claim of full readiness is made. This handoff is an audited **partial build**, with original failures and remaining gates retained.

Read [audit](PHASE4_AUDIT.md), [bug fixes](PHASE4_BUG_FIXES.md), [recovery](SECURITY_AND_RECOVERY.md), [acceptance map](../reports/phase4_acceptance.json).
"""
    (DOCS/'PHASE4_READINESS.md').write_text(verdict, encoding='utf-8')
    (REPORTS/'final_verification.md').write_text(verdict.replace('(PHASE4_', '(../docs/PHASE4_').replace('(GEMMA_', '(../docs/GEMMA_').replace('(OFFICIAL_', '(../docs/OFFICIAL_').replace('(SECURITY_', '(../docs/SECURITY_').replace('(../reports/phase4_acceptance.json)', '(phase4_acceptance.json)'), encoding='utf-8')
    (REPORTS/'BUILD_PROGRESS.md').write_text(
        '# Phase 4 build progress\n\nStatus: **PARTIAL**.\n\n'
        f'Current regression run: {tests.get("run_id")}; counts: {counts}.\n\n'
        f'Soak: {soak_line}; observed {soak.get("elapsed_seconds", 0)} seconds.\n\n'
        'See [final verification](final_verification.md) for outstanding gates. This file records evidence, not a release authorization.\n',
        encoding='utf-8')
    print(json.dumps({'tests': counts, 'historical_soak_qualified': soak.get('one_hour_qualified', False),
                      'current_runtime_soak_qualified': soak_current and soak.get('one_hour_qualified', False),
                      'live_complete': live.get('complete', False), 'growth_recorded': bool(growth), 'verdict': 'PARTIAL'}))


if __name__ == '__main__':
    main()
