# Sandboxed coding-agent provider + artifact debugging

Use this when a sandboxed coding-agent runner reaches the model/provider but still reports bad diffs, polluted artifacts, or confusing FAIL/OK boundaries.

## Pattern from GoblinBench + pi + Lemonade

A real local-model smoke can prove different layers independently:

1. **Provider registration outside the harness**
   - Run the agent CLI with explicit extension loading and list models.
   - For pi + Lemonade, the durable launch shape is:
     ```bash
     PI_CODING_AGENT_DIR=/home/dev/goblinbench/.sandbox-runtime/agent \
     node .sandbox-runtime/node_modules/@earendil-works/pi-coding-agent/dist/cli.js \
       --no-extensions \
       --extension /home/dev/goblinbench/scripts/lemonade-pi-extension.js \
       --list-models lemonade
     ```
   - This distinguishes "provider is not registered" from "model behavior failed later".

2. **Tiny deterministic e2e before hard benchmark**
   - Run a tiny fixture (`e2e-pi-mock` style) through the full sandbox before a real coding benchmark.
   - Verify `agent.patch`, `output.json`, and `files_changed`, not just process exit.

3. **Artifact pollution check**
   - Agent/runtime tooling may write execution scratch inside the writable workspace.
   - pi loads TypeScript extensions through jiti; jiti can create `.tmp/jiti/*.mjs` under the workspace cwd.
   - These are runner/runtime artifacts, not candidate edits. If they appear in `agent.patch`, fix snapshot/diff filtering rather than blaming the model.
   - Add a regression test that writes both a real code file and a scratch file, watches the scratch file appear in RED, then filters runner-owned scratch dirs.

4. **Separate plumbing success from model success**
   - A local model run can be a valid harness/provider success even if the benchmark candidate fails.
   - Example failure shape: model edits a file and scorer sees visible tests pass, but process exits non-zero/137 or strict tests fail. Report this as model/agent behavior after proving provider + sandbox + artifact capture work.

## Durable implementation notes

- Prefer explicit extension launch (`--no-extensions --extension <known path>`) for benchmark repeatability.
- Keep extension paths visible inside the sandbox. Paths under host `/tmp` may disappear if the sandbox overlays `/tmp` with tmpfs.
- Diff filters for sandboxed coding agents should ignore runner-owned scratch dirs such as `.tmp`, `.cache`, `.home`, and `.dotnet-home` when those are intentionally mapped under the workspace.
- Preserve run IDs/artifact paths for benchmark interpretation, but do not turn them into long-term memory entries.
