# pi-crew worker matrix script pattern

Session: 2026-06-12  
Task context: `pi-crew` task #2283 — GoblinBench pi-crew worker model/profile suitability smoke matrix.

## When to use this pattern

Use a standalone script (not a .NET runner scenario) when the benchmark must:

- Call Den MCP worker lifecycle tools directly (`create_task`, `lease_worker`, `get_worker_run_status`, `get_latest_worker_completion`, `cleanup_worker_run`, `list_pool_members`).
- Drive pi-crew worker assignments end-to-end from GoblinBench.
- Support both automated mode (live leasing) and manual/import mode (ingesting handles from external runs).
- Iterate quickly when worker runs are unstable or timeouts are long.

## Script location

Place the script under `scripts/` in the GoblinBench repo, e.g.:
- `scripts/pi-crew-worker-matrix/pi_crew_worker_matrix.py`

## Core shape

1. **MCP transport**: `POST http://192.168.1.10:5199/mcp?tool_profile=runner` with `Mcp-Session-Id` from `initialize` header. See `references/pi-crew-worker-matrix-transport.md` in the `den-mcp` skill for the exact quirk.
2. **Matrix definition**: one Den task per cell, tagged with `goblinbench`, `model:<name>`, `profile:<name>`, `artifact:<kind>`, `role:<role>`, campaign ID. **Do not fake a cross-product of arbitrary den-router model names and worker identities.** A Den worker lease selects a configured pool member/profile; it does not pass a per-assignment model override. Treat the tested model as the model currently configured on that worker profile unless the operator has actually created separate model-specific profiles/members or supplied an explicit matrix JSON that corresponds to installed config.
3. **Cell execution**:
   - Create task
   - Lease worker with `preferred_worker_identity` + `profile_identity`
   - Poll `get_worker_run_status` until terminal or timeout
   - Read `get_latest_worker_completion`
   - `cleanup_worker_run` (best effort)
   - Verify `list_pool_members` returns `available`
4. **Scoring**: record `substrate_success`, `deliverable_success`, `packet_valid`, `failure_category` separately.
5. **Output**: `runs/pi-crew-matrix-<id>/matrix.json` + flat `matrix.md`.

## Timeout guidance

- Worker runs on reasoning models can exceed 600s. Default poll timeouts should be generous (600s–1200s) or configurable.
- Record timeout as its own failure category; do not conflate with model quality.

## Import mode

Accept JSON on stdin with pre-collected handles:
```json
{
  "model": "deepseek-flash",
  "role": "coder",
  "worker_identity": "pi-crew-coder-1",
  "task_id": 1234,
  "assignment_id": 567,
  "run_id": "piw-...",
  "completion_status": "present",
  "failure_category": null
}
```

## Pitfalls

- The live MCP facade uses plain tool names (`create_task`, not `mcp_den_create_task`) when called via raw HTTP.
- `tool_profile=runner` is required for worker tools; without it, `lease_worker` is rejected as unknown.
- Session IDs are header-only; do not look for them in the JSON body.
- Long worker timeouts make full matrix runs impractical; prefer manual/import mode for bulk comparison when timeouts are the bottleneck.
