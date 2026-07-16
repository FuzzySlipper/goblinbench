# Pi + den-router coding candidate pattern

Reusable recipe for running the `coding` suite through pi against models exposed by the local den-router (`http://127.0.0.1:18082/v1`).

## Why this exists

The coding suite requires `kind: CodingAgent` candidates; plain OpenAI chat candidates are silently skipped by `CodingAgentRunner`. The `/home/dev/den-pi/extensions/den-router.ts` extension auto-registers a `den-router` provider by fetching `/v1/models` and mapping every model id into pi’s provider model list, so no hand-built `models.json` is needed.

## Workspace layout

- Extension: `/home/dev/den-pi/extensions/den-router.ts`
- Shared pi runtime: `/home/dev/goblinbench/.sandbox-runtime/`
- Shared pi workspace for den-router coding runs: `/home/dev/goblinbench/.sandbox-runtime/den-router-coding-workspace/`

The workspace directory must exist before the run; pi/jiti writes extension cache under it. The `CodingAgentRunner` copies the per-scenario fixture into a per-candidate subdir inside the run artifacts, so parallel runs sharing the same workspace root are safe.

## Candidate config shape

```json
{
  "id": "pi-coding-<model>-den-router",
  "name": "Pi Coding Agent — <Model Name> via den-router (sandboxed)",
  "kind": "CodingAgent",
  "model": "<model-id>",
  "provider": "den-router",
  "cli_args": [
    "--print",
    "--no-session",
    "--no-extensions",
    "--extension",
    "/home/dev/goblinbench/.sandbox-runtime/den-router-coding-workspace/den-router.ts",
    "--provider",
    "den-router",
    "--model",
    "<model-id>",
    "--mode",
    "json"
  ],
  "config": {
    "agent_resolved": "/home/dev/goblinbench/.sandbox-runtime/node_modules/@earendil-works/pi-coding-agent/dist/cli.js",
    "sandbox_root": "/home/dev/goblinbench/.sandbox-runtime",
    "node_resolved": "/usr/bin/node",
    "workspace": "/home/dev/goblinbench/.sandbox-runtime/den-router-coding-workspace"
  }
}
```

## Smoke test before adding

```bash
curl -s -m 30 -X POST http://127.0.0.1:18082/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<model-id>","messages":[{"role":"user","content":"PONG"}],"max_tokens":16}' \
  -o /tmp/<model-id>_resp.txt -w "HTTP_CODE:%{http_code}\n"
```

- `HTTP 200` with non-empty content → good.
- `HTTP 404` → model id not routed; remove from candidates.
- StepFun and HY3 return SSE-whitespace-prefixed JSON; the runner handles this internally, but ad-hoc `json.loads()` probes must strip to the first `{`.

## Observed results (2026-06-11, 6-scenario × 8-model via pi sandbox)

Full matrix run IDs: `/tmp/coding_run_ids_407020`.

| scenario | stepfun | flash | pro | minimax | hy3 | qwenplus | qwenmax | grok |
|---|---|---|---|---|---|---|---|---|
| cache-key | 1.00 | 1.00 | 1.00 | 1.00 | 0.35 | 0.80 | 1.00 | 1.00 |
| expression-evaluator | 0.10 | 0.10 | 0.10 | 0.10 | 0.10 | 0.10 | **1.00** | **1.00** |
| kth-selection | 1.00 | 1.00 | 0.96 | 0.00* | 1.00 | 0.96 | 1.00 | 0.00* |
| retry-policy | 0.35 | 1.00 | 1.00 | 1.00 | 0.35 | 0.00 | 1.00 | 1.00 |
| tree-prune | 1.00 | 1.00 | 1.00 | 1.00 | 0.57 | 1.00 | 1.00 | 1.00 |
| weighted-split | 1.00 | 0.63 | 1.00 | 1.00 | 0.63 | 0.63 | 1.00 | 1.00 |

`*` grok and minimax on kth-selection: 0.00 with no visible/strict breakdown — likely runner/parse failure or timeout, not necessarily zero test passes.
`†` minimax hit 300s scenario timeout on kth-selection specifically.

Pass rates:
- **qwenmax: 6/6 (100%)** — only model to clear all 6.
- **grok: 5/6 (83%)** — nailed expression-evaluator but failed kth-selection (unclear why).
- **stepfun, deepseek-flash, deepseek-pro, minimax: 4/6 (67%)** — different failure profiles.
- **qwenplus, hy3: 1/6 (17%)** — weak on expression-evaluator, retry-policy, and cache-key.

`expression-evaluator` is the great filter: only qwenmax and grok passed; the other 6 scored 0.10.

## Verified 2026-06-11

- `stepfun`, `deepseek-flash`, `deepseek-pro`, `minimax`, `hy3`, `qwenplus`, `qwenmax`, `grok` all smoke-tested 200.
- `pi-coding-stepfun-den-router` ran `coding.tree-prune` end-to-end: 12/12 tests passed in 69s.
- Per-candidate fixture copy under `runs/<run>/scenarios/<scenario>/candidates/<candidate-id>/fixture` confirmed safe for parallel runs. Multiple candidates can share the same `workspace` root (`den-router-coding-workspace/`) because pi/jiti extension caches live under `.tmp/jiti` inside that workspace, and the runner filters `.tmp`, `.cache`, `.home`, and `.dotnet-home` from candidate diffs.

## Common pitfall: `autonomy-calibration` / `evidence-grounding` runner mismatch

These suites use `FakeFuzzyCandidateRunner` (`cli_command: "fuzzy-scripted"`) and the `fuzzy-agent-behavior` scorer, which requires a structured `decision_packet` JSON. Plain `OpenAiModel` chat candidates will always score 0.00 here with "no parseable decision packet" — it is not a model failure, it is a runner contract mismatch. See `references/fuzzy-agent-scorer-and-chat-candidates.md`.
- Full 6-scenario × 8-model matrix completed: qwenmax 6/6 (only model to clear all), grok 5/6, stepfun/deepseek-flash/deepseek-pro/minimax 4/6 each, qwenplus/hy3 1/6 each. `expression-evaluator` was the great filter (only qwenmax + grok passed).
