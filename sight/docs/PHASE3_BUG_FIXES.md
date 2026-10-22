# Phase 3 fixes and regression evidence

| Finding | Root cause and repair | Regression evidence |
|---|---|---|
| Original UI proactive notices would receive an undefined value | Backend initially returned `message`; the preserved home script reads `text`. Return both fields from the same persisted title. | `test_live_scheduler_and_truthful_briefing`; live reminder and restart smoke |
| Selected code snapshot lost the Hermes catalog | Phase 2 snapshots copied only code/UI/lock. Phase 3 also manifests and verifies its runtime skill-index JSON. | `test_release_preserves_skill_catalog_and_corrupt_index_degrades` |
| A malformed optional skill index could prevent startup | Unguarded JSON load during capability initialization. Preserve core operation and report an unavailable catalog on read/validation failure. | Same corruption test invokes a working local tool afterwards |
| JavaScript duplicate grouping could merge different bodies | The first lexical index hashed only matching declaration text. Hash full source identity plus declaration offset; a shared header is no longer enough. | Recomputed current matrix; Python uses complete AST content |
| Malformed MCP tool names could throw TypeError | Unhashable JSON values reached a set membership check. Validate name type and request IDs before dispatch. | `test_mcp_malformed_names_and_requests_are_protocol_errors` |
| Cancelled browser/speech work could outlive an HTTP task | A cancelled await alone does not terminate child processes. Bound workers and kill only their owned process trees in cleanup. | Actual parent+child cancellation test, browser failure/recovery test |
| Repeated/restarted reminders could deliver twice | Use a transaction for unique occurrence receipt plus schedule advancement; coalesce missed UTC intervals. | Once/recurring restart, quiet hours, cancellation and actual server restart tests |
| Artifact growth was unbounded | Per-item size alone did not cap accumulated output. Add count and aggregate storage limits, with explicit owner cleanup. | `test_artifact_count_limit_is_fail_closed` and path/hardlink tests |
| First live smoke harness failed before checks | httpx client had already been used before re-entering its context manager. Use explicit closing around the connected client. | Failed evidence retained as `live_phase3_20261019T085210Z.json`; subsequent complete run passed 48 checks |

No credentials were printed, embedded in artifacts, or copied into the build. No provider policies or quota ledgers were reset. Model-generated code, source skill instructions and untrusted browser content do not receive execution authority.
