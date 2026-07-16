# Den-channel delivery and background-run reliability

## Symptom

After a background `dotnet run` matrix completes, the user reports that the
final tool output (run IDs, scores, summary tables) never appeared in the
chat. The process did finish; the output was simply never delivered.

## Root cause

Long-running background shells can exit successfully while the chat transport
drops or buffers the final stdout burst. The process exit status and run
artifacts are correct, but the user sees nothing.

## Recovery pattern

1. Check the background process status with `process(action='poll')` or
   `process(action='wait')` after the run should have finished.
2. If it shows `exited` but the user says output is missing, **do not rerun**.
   Rerunning wastes time and model budget.
3. Reconstruct the answer from the run ID file (e.g. `/tmp/qwenmax_full_run_ids`)
   or from the run directories under `/home/dev/goblinbench/runs/`.
4. Extract scores with a Python script that reads `scores.json` files and
   prints per-scenario tables.
5. Repost the tables verbatim.

## Run ID file convention

```bash
OUT=/tmp/run_ids_$$
echo "suite|candidate|run_id" > "$OUT"
```

Then each line is `suite|candidate|run_id`. Parse with:

```python
with open('/tmp/run_ids_...') as f:
    for line in f:
        suite, cand, run = line.strip().split('|')
```

## When to repost

- Process status is `exited` and run ID file has N entries matching the
  expected matrix size.
- User explicitly says "output didn't show up" or similar.
- Any time a background run takes > 5 minutes and the final summary is
  missing from the chat.

## When to rerun

- Run ID file is empty or shorter than expected.
- Run directories are missing from `/home/dev/goblinbench/runs/`.
- Process status is `failed` / `killed` / non-zero exit.

## Candidate routing quick reference

| Suite type | Candidate suffix | Runner | Key flag |
|---|---|---|---|
| MCP tool-use | `-tool-behavior` | `OpenAiMcpToolUseRunner` | `config.runner: "mcp-openai-tool-use"` |
| Autonomy / grounding | `-fuzzy` | `OpenAiFuzzyAgentRunner` | no `cli_command`, no `config.runner` |
| Orchestrator decision | `-orchestrator` | `OpenAiChatRunner` | no `cli_command`, no `config.runner` |
| Coding | `-coding` (pi) | `CodingAgentRunner` | `kind: "CodingAgent"` |

**Critical:** never run an orchestrator suite through a `-tool-behavior`
candidate. The MCP runner rejects non-MCP scenarios and scores 0.00.
