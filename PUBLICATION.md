# Published SIGHT build

This repository contains the latest Phase 4 source handoff. Its release verdict remains **PARTIAL**. Publishing the source does not change the recorded readiness verdict or erase failed/historical tests.

- Selected model: official `gemma4:e4b-it-qat`, thinking initially disabled.
- Windows regression evidence: 314 passed, zero failures/skips; 16 UI comparisons, zero changed pixels.
- Official model files passed complete local SHA-256 checks. Live official inference, reasoning and soak qualification are pending because Ollama is currently absent from the build machine.
- Prior uncensored inference/growth/soak reports remain explicitly historical.
- The original repository MIT license is preserved. No reference-repository source code is bundled.
- Credentials, owner-data databases, test databases, model weights, installed environments and raw server logs are excluded.

The [build ZIP](dist/SIGHT-Phase4-Partial.zip) preserves the complete handoff layout. The source tree is extracted from that verified ZIP, with publication notes added to README and byte-preservation rules added to .gitattributes. One historical 151 MB source-symbol index exceeds GitHub's individual-file limit; it is published as `sight/reports/source_symbol_candidates.csv.gz`. Decompressing it reproduces the exact original CSV. The full ZIP also contains the original CSV. This index is metadata, not executable product source or proof of semantic coverage.

[Upload manifest](UPLOAD_MANIFEST.json) records every published file's hash and the compressed-file mapping. The manifest itself is excluded from its own hash list.

Run `Verify-SIGHT.ps1` on Windows after installing the pinned requirements and Playwright browser. Recorded paths inside historical evidence describe the build machine. Audit-only scripts such as `check_phase4_handoff.py` additionally need the preserved earlier phases and private key-exclusion input on that machine; they are not required to run SIGHT.

[Readiness](sight/docs/PHASE4_READINESS.md) | [Tests](sight/docs/PHASE4_TEST_RESULTS.md) | [Official model setup](sight/docs/OFFICIAL_GEMMA.md)

The exported GitHub checkout was separately retested: **314 passed, zero failures/skips**, in 120.65 seconds using the provisioned environment. [Checkout test results](publication-tests/result.json), [raw log](publication-tests/pytest.log), [JUnit](publication-tests/junit.xml).
