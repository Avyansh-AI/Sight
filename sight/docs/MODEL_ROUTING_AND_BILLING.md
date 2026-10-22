# Model routing and the zero-dollar test scope

Local Gemma runs first, under a shared inference lock. Successful, busy, cancelled and context-limit replies do not invoke fallback. Startup local-only mode overrides saved cloud policies. Private memory is removed from remote chat context; downstream tasks retain their privacy flag and cannot send local-only results to remote inference.

The owner authorized free-tier Groq, Gemini and OpenRouter tests and confirmed Gemini/Groq paid billing is disabled. All three passed real inference in Phase 2. Detailed historical attempts, latency and restrictions are in [the Phase 2 audit](PHASE2_AUDIT.md). Phase 3 made no additional cloud requests; its live inference smoke used the installed local Gemma. The earlier Phase 1 authentication-only scope was explicitly expanded by the owner for Phase 2.

Every provider reserves request/token/budget usage atomically before network use. Failed and ambiguous attempts count. Rolling daily/minute caps and server cooldown survive restarts. OpenRouter free routing requires an explicit free model, zero maximum route price and positive current account free-request headroom. No key rotation or automatic request retry occurs. These caps apply to one SIGHT data directory; other apps share the upstream account limit.

Default policies are disabled. The provider smoke ledger is intentionally retained under Phase-2/test-data/provider-smoke; do not reset it to gain more requests. Store keys through the hidden CLI prompt; a replacement key disables that provider until its tier/policy is reviewed again.

Optional ChatGPT uses official sign-in and plan scopes, never a stored API key or another app's account tokens. Its policy requires confirmation that SIGHT credit use is disabled in ChatGPT Settings, an account-listed model, bounded reservations and completed streamed inference. Live owner account qualification remains pending. No Codex coding integration is enabled.
