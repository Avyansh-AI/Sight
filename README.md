# SIGHT Phase 4 — audit and hardening

**PARTIAL: the full integrated-release gate has not passed.** Read [readiness](sight/docs/PHASE4_READINESS.md), [audit](sight/docs/PHASE4_AUDIT.md), [bug fixes](sight/docs/PHASE4_BUG_FIXES.md), and [test results](sight/docs/PHASE4_TEST_RESULTS.md).

For a fresh checkout, install Python 3.12 and Ollama, then follow the [official Gemma setup](sight/docs/OFFICIAL_GEMMA.md). The selected model is **`gemma4:e4b-it-qat`**. Weights, Python environments and private data are separate from the source build.

After setup, from PowerShell in this folder:

```powershell
.\Start-Local-Runtime.ps1
.\Start-SIGHT.ps1
```

Leave the server running. In another PowerShell window run `.\Open-SIGHT.ps1`. Phase 4 uses **http://127.0.0.1:8084** and its separate `owner-data` directory. Phase 1–3 remain preserved. No Phase-4 UI files were changed. Open **Systems → Open capabilities** for local tools and **Learning** for memory/Forge/tasks.

The page offers local documents, calendar export, code inspection/diffs, static site drafts, cuboid STL generation, offline browser inspection, Windows information and speech-to-WAV rendering, reminders, and small circuit/geospatial/landmark tools. Every invocation requires review of exact arguments. Remote devices, microphones, cameras and external messages are not activated. Simulations are clearly labeled.

The selected model is the official Gemma 4 E4B QAT build. The prior uncensored model is retained but is not selected. The runtime helper reuses a running local server. For a new server it uses `-ModelsDirectory`, `OLLAMA_MODELS`, the existing legacy `D:\Ollama Models` directory, or the standard `%USERPROFILE%\.ollama\models` location, in that order. Both helpers support the per-user Ollama installation, `PATH`, and an explicit `-OllamaExecutable` path. The helper never downloads weights or stops an existing runtime. The child receives SIGHT's CUDA/context settings; the invoking shell keeps its prior environment.

To test directly in Ollama, run `.\Run-Gemma.ps1` after starting the runtime. This helper and the saved SIGHT selection initially use thinking disabled; `-Thinking` enables it for comparison in the helper. **Official-model live quality is unverified:** Ollama was absent from the build machine at publication, so no official inference or new soak was claimed. The earlier failed quality tests concern the uncensored model. [Current model status](sight/docs/OFFICIAL_GEMMA.md), [historical uncensored report](sight/docs/GEMMA_REPAIR.md).

For offline installation, provision the matching Python installer, wheel directory and Playwright Chromium cache before disconnecting, then use `sight\scripts\install.ps1 -Offline -Wheelhouse <path> -BrowserCache <path>`. The source handoff excludes wheels and external runtimes. Current-account offline installation was tested, not a new Windows account.

Run `.\Verify-SIGHT.ps1` for the full regression suite. For the separate live local smoke, run `.\sight\.venv\Scripts\python.exe .\sight\scripts\phase4_smoke.py` from this folder. Run live model tests sequentially; each uses an isolated test-data directory.

Cloud policies are disabled by default and startup forces local-only mode. Phase 4 made **zero cloud inference requests**. Previous free-provider results and rolling quota ledgers remain untouched. Do not reset those ledgers to rerun tests. The existing $0/free-tier limits still apply; paid billing was not authorized.

Artifacts are private immutable files under `owner-data/artifacts`, with a cap of 200 files / 128 MiB. Download/export them and remove unneeded files locally when full. Windows voice output is a downloadable WAV, with no automatic playback or recording. Reminder delivery is inside SIGHT only; recurrence and quiet hours use UTC. Missed intervals combine into one notice after restart.

The [local MCP bridge](sight/docs/ARCHITECTURE.md) requires an owner session, CSRF proof and a separate one-use approval for each tool call. External MCP transports and cross-device listeners are disabled. Hermes guidance is indexed without executing or installing its instructions.

The new full-data backup/restore commands are documented in [security and recovery](sight/docs/SECURITY_AND_RECOVERY.md). Owner data, test databases, model weights, credentials, wheels, external browsers and `.venv` are excluded from the source ZIP. Personal wake-word enrollment has not begun. Earlier phase reports remain historical evidence.

## Download and verification

[Download the source build ZIP](dist/SIGHT-Phase4-Partial.zip) and [SHA-256 checksum](dist/SIGHT-Phase4-Partial.zip.sha256). The ZIP includes the source, setup helpers, tests and detailed audit evidence. It excludes credentials, owner data, models, Python environments and third-party reference repositories.

This is the latest Phase 4 handoff, marked **PARTIAL**, not a production-ready certification. The recorded Windows regression run passed **314 tests**, with zero failures/skips and zero UI pixel changes. Official Gemma live inference remains unverified because Ollama was absent on the build machine at publication. See [publication details](PUBLICATION.md).
