# Official Gemma selection

The owner changed the requested model to normal Gemma. The selected model is now **`gemma4:e4b-it-qat`**, the official quantized Gemma 4 E4B build in [Ollama's library](https://ollama.com/library/gemma4:e4b-it-qat). The previous uncensored model remains installed but is no longer selected by SIGHT or `Run-Gemma.ps1`.

The official download completed on 21 October 2026. The follow-up verified all six local manifest/config/model/projector/license/parameter blobs against their SHA-256 digests. This proves file integrity, not answer quality. [Installation evidence](../reports/gemma_official_install.json), [selection and integrity checks](../reports/official_model_switch.json).

**Live official-model inference is unverified.** At publication, the local Ollama executable was no longer present in its previous installation directory or on PATH, and the loopback service was unavailable. No official inference, fresh model comparison or official-model soak is claimed. Earlier wrong answers and the earlier one-hour soak concern the uncensored model. They remain historical evidence, not results for the official model.

SIGHT uses the official model's temperature 1.0, top-p 0.95 and top-k 64, with repetition penalty 1.0. Context stays at 4,096 tokens, one request runs at a time, and non-thinking output is capped at 512 tokens. Thinking is initially disabled; its quality and latency still need live testing. The direct helper accepts `-Thinking` for an explicit comparison.

From the build's top-level folder, after installing Python 3.12 and [Ollama for Windows](https://docs.ollama.com/windows):

```powershell
Push-Location .
try { .\sight\scripts\install.ps1 }
finally { Pop-Location }
ollama pull gemma4:e4b-it-qat
.\Start-Local-Runtime.ps1
$env:SIGHT_DATA_DIR = Join-Path $PWD.Path 'owner-data'
Push-Location sight
try { .\.venv\Scripts\python.exe -m sight_core.cli configure-model gemma4:e4b-it-qat --no-thinking }
finally { Pop-Location }
.\Start-SIGHT.ps1
```

Open SIGHT using `Open-SIGHT.ps1` in a second PowerShell window. Use `Run-Gemma.ps1` for a direct local chat. Model weights and Ollama are separate downloads and are not included in the GitHub source or handoff ZIP. No cloud provider is enabled by these steps.
