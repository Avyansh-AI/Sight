# Phase 4 security and recovery

The HTTP server binds 127.0.0.1. A launch token held in an owner-private directory establishes an HttpOnly owner session; writes require same-origin CSRF proof. Privileged changes additionally require a short-lived, one-use grant bound to the session, exact action and validated arguments. WebSockets require an expiring ticket. Text is rendered with textContent and script hashes enforce CSP.

Keys remain in the OS vault with no plaintext fallback. ChatGPT registrations/tokens are separated by data directory and account, stored in bounded vault chunks, and refreshes are serialized. Official sign-in verifies state, nonce, PKCE, issuer, audience, expiry, signature and plan scope. The callback is the only narrow cross-site exception. Remote revocation failure is explicitly reported after clearing local tokens.

The Forge worker is a bounded declarative interpreter, not an arbitrary-code sandbox. It has no user-controlled imports, shell, file/network APIs or package installation. Dependencies pause. Immutable candidate hashes, test results and explicit promotion bind the reviewed version.

Learning memory cannot modify operational receipts or provider permissions. Corrections/deletion remove derived summaries and live retrieval. Historical task inputs/results and independent backups are separate retention records. Avoid claiming whole-disk erasure after forgetting active memory.

The legacy core `backup` command covers only `sight.sqlite3`; the learning-page backup covers only `brain.sqlite3`. For the full supported data set, stop SIGHT and use the new offline `backup-all` / `restore-all` commands below. These include both databases, the private text workspace, artifacts and optional local model selection. Vault credentials, browser tokens, active sessions, logs, voice samples, model weights and code snapshots are excluded.

Code snapshots are verified against a complete manifest and dependency lock before the root launcher selects them. Corrupt selections fall back to the installed baseline. Code rollback preserves the current data/receipts; different dependency environments require separate verification. A crash after file publication is reconciled by inode/device/hash and never blindly rewrites the target. An interrupted model call requires review and is never automatically billed again.

Phase 3 local tools reuse the same grant checks. Browser and speech operations use bounded fixed-code workers; cancellation terminates their owned process trees. Browser inspection has no network, JavaScript, downloads, account profile or form submission. The browser worker explicitly enables Chromium's native sandbox; an actual command-line test verifies that `--no-sandbox` is absent. This is not a general OS sandbox or sandbox-escape certification. The owner-local MCP subset requires session/CSRF and an exact one-use tool grant. Remote listeners and external MCP transports remain disabled.

Generated artifacts are immutable owner-private attachments, capped at 8 MiB each and 200 files / 128 MiB total. Export and remove unwanted files locally. Full backup includes them; the two legacy SQLite-only backups do not. Skill-index metadata is included in verified code snapshots.

The full bundle uses a 2 GiB/10,000-file limit and an exact hash/size manifest. The server's single-instance lock must be free; unresolved file-publication receipts must be reviewed first. Restore validates the bundle before creating a new destination, checks database versions/integrity, preserves completed receipts and quota ledgers, removes old approvals, disables providers/ChatGPT/monitoring and marks unfinished jobs `needs_review`. It does not automatically replay them. Keep an independent backup: a hash detects corruption but is not authentication if someone can rewrite the data and manifest together.

From the Phase-4 root, choose unused destination names:

```powershell
$env:SIGHT_DATA_DIR = Join-Path $PWD.Path 'owner-data'
$sightBackup = Join-Path $PWD.Path 'owner-backup'
$sightRestored = Join-Path $PWD.Path 'owner-restored'
Push-Location sight
try {
    .\.venv\Scripts\python.exe -m sight_core.cli backup-all $sightBackup
    .\.venv\Scripts\python.exe -m sight_core.cli restore-all $sightBackup $sightRestored
} finally { Pop-Location }
```

Inspect the returned manifest and restored state. Set `$env:SIGHT_DATA_DIR = $sightRestored` before `Start-SIGHT.ps1` to use the restored copy; default startup remains local-only. Reauthorize credentials separately if needed. The original directory is preserved.

Existing symlink/junction ancestors, hard-linked sensitive files, SQLite sidecars and release bytecode are rejected. These checks do not promise immunity to concurrent same-owner path replacement. WebSocket ticket query values are now redacted in Uvicorn's error/access logs as well as structured audit payloads.

The selected local model profile in this workspace has thinking disabled. If thinking is explicitly enabled, interactive local chat can retry once on a successful thinking-only stop, using the same model with thinking disabled. It never executes model text as a tool. Durable tasks and Forge retain their no-automatic-retry budget behavior. Output length, runtime failures and cancellation do not trigger that retry.

Current-user Windows ACL/recovery tests and the fresh-venv offline installation have evidence. Fresh-account installation, hardware integrations and model quality remain qualifications in [readiness](PHASE4_READINESS.md).
