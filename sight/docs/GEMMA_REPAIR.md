# Uncensored Gemma 4 E4B repair — 21 October 2026

**Historical report.** The owner subsequently selected normal Gemma. The current model is `gemma4:e4b-it-qat`; see [official setup and verification status](OFFICIAL_GEMMA.md). The current `Run-Gemma.ps1` starts the official model. Instructions and results below record the earlier uncensored work.

During this audit, only `hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED:Q4_K_M` and profiles derived from those same installed weights were used. The selected profile then was **`sight-gemma4-e4b:uncensored`**. The source tag and weights were not overwritten. [Runtime inventory](../reports/runtime_inventory.json) verifies matching model and projector blob references and a 720-tensor GGUF header; it does not claim a new full-file weight hash.

The subsequent [full-file integrity check](../reports/gemma_weight_integrity.json) streamed both complete blobs (5,335,289,792 model bytes and 990,372,288 projector bytes). Both SHA-256 hashes matched the local manifests and publisher revision `d8678bbb9e0d4f5729c115087485a4e25ba89d65`. No weights were downloaded or changed. This rules out a mismatch against those published files; it does not establish their reasoning quality.

**Configuration and response handling are repaired; general reasoning quality is not repaired.** The user's observation came from Ollama directly. No exact failing user conversation was supplied, so all reproduction prompts were synthetic.

## Using it

From the `Phase-4` folder:

```powershell
.\Start-Local-Runtime.ps1
.\Run-Gemma.ps1
```

`Run-Gemma.ps1` checks that the existing uncensored profile is installed and invokes Ollama with thinking disabled. This avoids the reproduced thinking-only blank responses. It does not improve every answer. The direct CLI retains the profile's 1536-token output ceiling; SIGHT requests override that to 512 tokens when thinking is disabled. To compare thinking mode explicitly, use `.\Run-Gemma.ps1 -Thinking`. Neither helper downloads a model.

The runtime helper now waits up to 120 seconds for a valid Ollama version response and reports early exit or timeout. A listening port alone is not readiness. An already-listening server is given time to initialize instead of spawning a competing process. Actual direct CLI execution returned `42` for the synthetic 17+25 prompt in 21.562 seconds including model loading; [evidence](../../evidence/gemma_direct_launcher.json). This is a launcher check, not a reasoning benchmark.

The follow-up repair checks an existing server before requiring local installation paths. For a new server, model-directory precedence is explicit `-ModelsDirectory`, then `OLLAMA_MODELS`, then the existing legacy `D:\Ollama Models` directory, then `%USERPROFILE%\.ollama\models`. Both helpers find the CLI under `%LOCALAPPDATA%\Programs\Ollama`, on `PATH`, or at an explicit `-OllamaExecutable` path. Startup settings apply to the child; the invoking shell's environment is restored, including on process-creation failure. The [live follow-up](../../evidence/gemma_launcher_portability_live.json) reused the running server and returned `42` through the revised direct helper. Alternate paths and cold-start decisions were tested with PowerShell fixtures, not a fresh Windows account.

The equivalent direct Ollama command is:

```powershell
ollama run sight-gemma4-e4b:uncensored --think=false
```

In SIGHT, `Start-SIGHT.ps1` uses the profile selected in `owner-data/local-model.json`. On 21 October, this workspace's selected profile was set to **thinking disabled**, matching the direct helper. The preceding thinking-enabled soak failed after 349.125 seconds: one arithmetic answer was wrong, and the next reached the output limit. [Failed soak](../../evidence/soak-20261020T125701Z-6c5a59/result.json). Disabling thinking is a stability workaround, not a reasoning repair.

If thinking is explicitly enabled later, SIGHT makes one local retry with thinking disabled only when an interactive chat ends normally with thinking but an empty final answer. The retry uses the same model, lock and overall timeout. Durable tasks, structured Forge generation, length-limited output and runtime/network errors do not receive this automatic retry.

On a new installation, first install the original uncensored weights yourself in Ollama. Then run the existing-environment script from the Phase-4 root:

```powershell
.\sight\.venv\Scripts\python.exe .\sight\scripts\configure_gemma_profile.py
$env:SIGHT_DATA_DIR = Join-Path $PWD.Path 'owner-data'
Push-Location sight
try { .\.venv\Scripts\python.exe -m sight_core.cli configure-model 'sight-gemma4-e4b:uncensored' --no-thinking } finally { Pop-Location }
```

Profile creation refuses to overwrite an existing alias. The [Modelfile](Gemma.Modelfile) records its settings. The existing `balanced` alias was an earlier experiment using the same uncensored weights; it is not selected.

## Findings and changes

| Finding | Change | Evidence and limitation |
| --- | --- | --- |
| The imported Hugging Face tag lacked Ollama's native Gemma thinking capability metadata. Controlled requests could produce repeated symbols to the output cap. | A separate alias uses native `gemma4` renderer/parser and a short professional system prompt. | [Profile creation](../../evidence/gemma_uncensored_profile_creation.json). No model training or weight modification. |
| Greedy/low-temperature variants and long instructions did not give dependable quality. | Temperature 0.7, top-p 0.9, top-k 40, repeat penalty 1.1; 4096 context, batch 128, memory mapping. The profile defaults to 1536 output tokens; SIGHT uses 1536 thinking or 512 non-thinking output tokens. | Matches the creator's recommended sampling configuration, but local tests still fail factual questions. |
| Thinking can end without any final answer. | Explicit rejection plus one narrowly scoped interactive-chat recovery, with summed token usage and recovery metadata. | [Eight thinking requests](../../evidence/gemma-repeat-1792477110.json): two blank answers and one wrong answer to 17+25. [Eight non-thinking requests](../../evidence/gemma-repeat-1792477276.json): eight correct answers to the same simple question. This is a small diagnostic sample, not a benchmark. |
| Output cap or conversation markers could masquerade as an answer. | Length-limited and unparsed output fail explicitly; private thinking is never returned to the UI or stored in diagnostic evidence. | Regression tests in `tests/test_phase4_hardening.py`. |
| Windows CUDA initialization crashed twice before model warm-up. | The runtime helper applies `CUDA_MODULE_LOADING=EAGER`, one loaded model, one parallel request and a 4096 default context to the process it starts. | Subsequent local loads worked. This is a workaround for the observed runtime failure, not proof of an upstream driver fix. An already-running Ollama process is left alone. |

The new profile stopped the repeated-symbol behavior in the tested cases and produced a more restrained tone. It still gave **1900 instead of 220** on a non-thinking discount/tax test. An earlier thinking-mode comparison using the `balanced` alias of the same uncensored weights gave **275**. That comparison used explicit sampling overrides; it was not the final selected tag. It sometimes contradicts its own correct arithmetic conclusion. [Five-case non-thinking evidence](../../evidence/gemma-controlled-1792477278.json) and [earlier five-case thinking evidence](../../evidence/gemma-thinking-1792418802.json) preserve these failures. Therefore this build is not certified for dependable reasoning.

An official non-uncensored comparison download had already finished when the owner clarified the restriction. Its newly created tag was removed, it was never used for inference, and the comparison script is disabled. [Disposition](../../evidence/gemma_official_pull.json). Other pre-existing owner models were not removed or selected.

## Follow-up prompt comparison

A [54-request paired evaluation](../reports/gemma_prompt_eval.json) compared the selected prompt, the publisher's short neutral prompt and a short professional prompt. All used the same installed uncensored weights, native parser, thinking disabled and sampling settings. Eight objective questions plus one style sample were run with each of two fixed seeds for each prompt. Six objective questions were held out from the two calibration questions. These are small diagnostic sets, not a general benchmark.

| Prompt | Calibration: exact answer and requested format | Held-out: exact answer and requested format | Style screen |
| --- | --- | --- | --- |
| Selected SIGHT prompt | 1/4 | 10/12 | 2/2 |
| Publisher's minimal prompt | 0/4 | 6/12 | 2/2 |
| Short professional prompt | 2/4 | 8/12 | 2/2 |

No candidate met the declared all-cases-pass condition for a separate confirmation run. The selected prompt remains unchanged. For example, it answered `YES` to fitting 37 minutes of sequential work into 35 minutes, and `6` instead of `9` on the printer-rate question. Those are substantive errors, not merely formatting failures. Style screening only checks completion and a small slang/emoji list; several RAM explanations remained awkward or inaccurate despite passing that screen. No model-produced code was executed, and no cloud inference was used.

The later memory-repair smoke tests exposed further failures through SIGHT's real WebSocket route with a synthetic local memory present: `Reply only the number: 2 plus 2?` produced `29` and then `1ことがある`. The first run stopped at the failed answer check. The second runner recorded answer quality separately so independent restart/recovery checks could finish; it passed 56 of 57 checks and still exited with code 1. Both failures are retained in the [memory follow-up evidence](../reports/memory_integrity_followup.json). The model, weights, prompt, sampling and thinking selection were unchanged; these results are not treated as a repaired reasoning gate.

## Sources

The [creator's model card](https://huggingface.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED) supplies the sampling recommendations and describes coherence limitations and an older missing-tensor defect. These are publisher statements, not independent certification. The installed file has 720 tensors, unlike the 666-tensor defect described there.

[Ollama thinking documentation](https://docs.ollama.com/capabilities/thinking) documents separate thinking and final content. [NVIDIA lazy-loading documentation](https://docs.nvidia.com/cuda/cuda-programming-guide/04-special-topics/lazy-loading.html) describes the `EAGER` setting. The matching Windows failure is also discussed in [Ollama issue 17380](https://github.com/ollama/ollama/issues/17380).

The [Ollama 0.40.6 GPU discovery source](https://github.com/ollama/ollama/blob/v0.40.6/discover/runner.go) includes a longer Windows bootstrap timeout because initial library scanning can be slow. That is context for readiness waiting, not proof of the cause of this machine's intermittent delay.

[Ollama's Windows documentation](https://docs.ollama.com/windows) and [model-storage FAQ](https://docs.ollama.com/faq#where-are-models-stored) describe the normal installation/model locations and the `OLLAMA_MODELS` override used by the portability repair. The full-file check records the publisher's metadata URL and revision in its evidence.
