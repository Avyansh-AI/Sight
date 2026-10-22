# Phase 3 architecture and capability audit

Audit date: 19 October 2026. Baseline: a separate copy of the repaired Phase 2 code; no original reference module, installer, GUI, or generated source was executed/imported. 61 Phase 2 source files were rehashed and remain unchanged. `apps/ui/index.html` is byte-identical to its Phase 2 baseline; original CSS/body and sixteen visual states are independently tested.

## Inputs and provenance

Eight named archives contain **21,207 files**; all extracted file hashes match. All **77** manual paths exist. The matrix contains **330,340 rows**, including source-file records, **137,232 Python AST function candidates**, **177,673 other-language declarations**, and manual references. **9,522 rows** have duplicate dispositions. These counts include tests and vendor content and are not a count of usable features.

`reports/source_inventory.csv`, `source_archives_current.json`, `capability_matrix.csv` and `phase3_inventory.json` record current evidence. The inherited `input_manifest.csv`/`hermes_provenance.json` describe an older 21,358-file audit and a cloned Hermes revision; they are historical and must not be confused with the current supplied ZIP. An additional `rea-main.zip` exists in the archive folder outside the eight repositories in this manual; it remains untouched.

Hermes has **58 built-in + 153 optional = 211 catalog skills**, plus **one Google Meet plugin SKILL.md**. Each row records path/hash, declared platform/rights, prerequisite/install indicators, network and secret indicators, unsafe operations, applicability and disabled activation. Classifications are conservative static indicators, not security certification. No Markdown is executed. MIT components are behavioral references; restricted Echo/Lite/Evo and unresolved ADA Local code remain separate, with no restricted source copied into the new implementation.

## Enabled behavior

All tool calls pass strict Pydantic schemas, existing owner session/CSRF and single-use exact-argument grants. Cloud routing is unchanged and disabled by the default launcher. The table describes the implemented behavior, not the full scope of similarly named reference components.

| Capability | Family | Implemented behavior | Permission |
|---|---|---|---|
| `files.search` | files | Find names in the private SIGHT text workspace | sight.workspace.read |
| `documents.docx` | documents | Create a plain text Word document without macros | artifacts.create |
| `documents.markdown` | documents | Create a Markdown note | artifacts.create |
| `coding.inspect` | coding | Parse Python syntax and list symbols without execution | local.compute |
| `coding.diff` | coding | Preview a unified text diff; never apply or run it | local.compute |
| `coding.site` | coding | Create an escaped static HTML draft | artifacts.create |
| `calendar.export` | calendar | Create one local ICS event; no invitations or account writes | artifacts.create |
| `cad.box` | cad | Generate a watertight rectangular cuboid STL in millimetres | artifacts.create |
| `circuit.ohm` | circuit | Calculate ideal resistor current/power below 25 V; no wiring control | local.compute |
| `geo.distance` | geospatial | Calculate great-circle distance between supplied coordinates | local.compute |
| `vision.landmarks` | vision | Measure pinch distance in supplied normalized landmarks; no camera or action | local.compute |
| `browser.inspect` | browser | Inspect owner-supplied HTML, fill local fields, and capture a screenshot; offline, scripts disabled | browser.isolated |
| `speech.render` | speech | Render text to an offline WAV with installed Windows voice; no microphone or playback | artifacts.create |
| `windows.info` | windows | Read operating system and Python architecture; no process/window contents | system.read |
| `reminders.add` | notifications | Schedule a durable in-app reminder, optionally at a fixed UTC interval | notifications.schedule |
| `reminders.cancel` | notifications | Cancel one scheduled in-app reminder | notifications.schedule |
| `monitor.configure` | proactive | Enable local disk health change alerts and UTC quiet hours | notifications.monitor |
| `briefing.local` | proactive | Compose actual local reminders and capability availability; online feeds reported unavailable | notifications.read |
| `contracts.simulate` | contracts | Run an explicitly simulated peripheral trust contract; no device traffic | local.compute |
| `mcp.local` | mcp | Inspect the owner-authenticated local MCP tool bridge and its approval requirements | local.compute |

`coding.inspect` also runs as a pure durable job operation with per-role/tool budgets and local-only result provenance. Existing memory, Forge, original desktop allowlist and file write/read APIs remain available and regression-tested.

## Explicitly unavailable broader behavior

| Registry ID | Disposition | Actual reason |
|---|---|---|
| `browser.remote` | DISABLED_SECURITY | Opt-in network policy and trusted browsing transport are not configured |
| `browser.cdp` | DISABLED_SECURITY | Owner-authorized CDP endpoint and account access scope are absent |
| `windows.input` | DISABLED_SECURITY | Interactive target/window authorization and recovery qualification pending |
| `files.organize` | DISABLED_SECURITY | Selected folder roots and reversible organization adapter pending |
| `documents.pdf` | REFERENCE_ONLY | Optional conversion engines and independently verified format adapters pending |
| `home.devices` | BLOCKED_HARDWARE | No paired home device or scoped credentials; simulator only |
| `calendar.account` | BLOCKED_CREDENTIALS | No calendar account authorization; local ICS export available |
| `android.gateway` | BLOCKED_HARDWARE | No paired Android gateway; in-memory trust contract only |
| `speech.listen` | BLOCKED_HARDWARE | STT model/backend and opt-in microphone pipeline absent; enrollment is a later owner gate |
| `camera.gesture` | BLOCKED_HARDWARE | No camera consent or installed vision pipeline; supplied landmarks only |
| `printer.submit` | BLOCKED_HARDWARE | No printer, slicer, material/profile or endpoint authorized; no Bambu support assumed |
| `calls.assistant` | BLOCKED_CREDENTIALS | No connected call account, participant consent or audio transport |
| `geo.live` | DISABLED_SECURITY | No opt-in live data adapter; offline values are never fabricated |
| `mcp.remote` | DISABLED_SECURITY | No approved external server or transport; protocol contract fixtures only |
| `channels.remote` | DISABLED_SECURITY | Remote channels have no listener; device trust and transport qualification pending |
| `games.update` | DISABLED_SECURITY | No platform authorization, download/storage limits or updater adapter |
| `communications.send` | BLOCKED_CREDENTIALS | No platform authorization or final reviewed recipient/action |

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
