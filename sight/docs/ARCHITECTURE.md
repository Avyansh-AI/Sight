# SIGHT Phase 3 architecture

One FastAPI loopback backend retains the Phase 2 model router, OS vault, quota ledger, SQLite core/learning stores, Forge DSL and durable job runner. `api.py` mounts `Capabilities`, its scheduler and the owner-local MCP bridge. The home HTML is preserved; Systems links to `capabilities.html`.

Discovery: `GET /api/capability/search?q=...` returns bounded summaries without schemas. `GET /api/capability/describe/{id}` returns one typed schema. `GET /api/capability/skills` searches the non-executing Hermes index. `GET /api/capabilities` includes actual blocked reasons.

Invocation: prepare `/api/capability/invoke` with `{id, arguments}` through `/api/actions/prepare`, review the normalized arguments, then POST them with the one-use `actionApproval`. Session, CSRF, expiry, exact payload and replay checks apply before execution. Artifacts are available through authenticated attachment endpoints. The service permits one local capability at a time; browser/speech workers have a 22-second outer timeout and cleanup of their own child tree. There is no generated-code interpreter or arbitrary shell adapter.

`local_adapters.py` contains pure bounded transformations. `artifacts.py` handles immutable private files. `proactive.py` adds reminders and notification receipts to the core SQLite database; existing core backup includes these tables, while generated artifact files and brain.sqlite3 retain separate backup scopes. Quiet hours and recurrence use explicit UTC semantics. `coding.inspect` is a pure durable operation; its result remains local during later model steps.

`POST /api/mcp` is an owner-local JSON-RPC tool bridge pinned to protocol 2025-06-18. It uses the same owner cookie and CSRF header, with initialize/notifications-initialized before discovery/calls. Only coding.inspect, circuit.ohm, geo.distance and vision.landmarks are exposed. Tools include `actionApproval` in their input schemas. Obtain that proof through the ordinary review flow for `/api/capability/invoke`; a call consumes it once. No remote transport, stdio command discovery, unauthenticated LAN listener, model-granted proof, or automatic approval is available. This is a documented local subset/extension, not universal MCP interoperability.

`connector_contracts.py` is transport independent. Simulators use ephemeral token hashes, five-minute expiry, scopes, request replay denial and revocation. Home/Android/printer fixtures additionally exercise state and print-plan validation. Camera/call status fixtures do not implement real audio/vision pipelines. See the [readiness gaps](PHASE3_READINESS.md).

Code snapshots now include the hashed Hermes runtime index. Runtime data is never rewound with code rollback. Corrupt/missing skill metadata disables that catalog without disabling other local tools.
