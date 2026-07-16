# GPT-5.6 medium/high reasoning-effort matrix pattern — 2026-07-09

Session-specific reference for running a new reasoning-model family against the existing GoblinBench general agentic-fitness suites while preserving comparability with the older July 09 broad matrix.

## User preference / evaluation stance

Patch does **not** usually treat `reasoning_effort=low` as the meaningful setting for complex evaluations. Low-effort tasks are usually routed to a cheaper/faster model family such as StepFun or local models. For expensive GPT-ish reasoning models on complex agentic evaluations, the useful branch is usually:

- `reasoning_effort: medium`
- `reasoning_effort: high`

Report these as separate candidate rows. Do not silently mix effort levels into one model row.

## Model family tested

Requested den-router IDs:

```text
gpt-5.6-terra-test-only
gpt-5.6-luna-test-only
gpt-5.6-sol-test-only
```

The `test-only` suffix is intentional: these models do not use Patch's Codex subscription and should not accidentally become normal/default usage models.

## Candidate-file pattern

Use separate candidate files by runner family, with medium/high variants for every model:

```text
candidates.gpt56-reasoning-mcp.json
candidates.gpt56-reasoning-session.json
candidates.gpt56-reasoning-fuzzy.json
```

Each entry should use the same API model id, but a distinct candidate id/name with the reasoning variant in it:

```json
{
  "id": "denrouter-gpt-5-6-sol-test-only-reasoning-high-tool-behavior",
  "kind": "OpenAiModel",
  "model": "gpt-5.6-sol-test-only",
  "provider": "den-router",
  "base_url": "http://127.0.0.1:18082/v1",
  "cli_command": "mcp-openai-tool-use",
  "config": {
    "runner": "mcp-openai-tool-use",
    "max_tokens": 16384,
    "max_tool_rounds": 8,
    "reasoning_effort": "high"
  }
}
```

Do **not** include temperature when `reasoning_effort` is present unless the specific provider/model requires it. Several reasoning APIs reject both knobs together.

## Runner support added / required

Before this session, only some runner paths honored `reasoning_effort`.

Required behavior across the suite families:

- `mcp_tool_use.py`: already supported `reasoning_effort` and omitted temperature when set.
- `mcp_session.py`: patch `_build_request_body` so it also sends `reasoning_effort` and omits temperature when set.
- `fuzzy_agent.py`: patch request body similarly, preserving `response_format: {"type":"json_object"}`.
- `codebase-analysis-runner.py`: support model specs of the form `model@medium` / `model@high`, sending API model `model` while labeling artifacts as `model-reasoning-medium` / `model-reasoning-high`.

Codebase-analysis examples:

```text
gpt-5.6-terra-test-only@medium
gpt-5.6-terra-test-only@high
gpt-5.6-luna-test-only@medium
gpt-5.6-luna-test-only@high
gpt-5.6-sol-test-only@medium
gpt-5.6-sol-test-only@high
```

## Smoke probes

Before launching a large matrix, verify every model × effort pair with:

1. plain chat: `Reply exactly READY.`
2. fake tool call: tiny `ping` function, check `tool_calls` exists
3. JSON response format: `response_format: {"type":"json_object"}` and a tiny JSON response

For the 2026-07-09 setup, all 3 GPT-5.6 variants succeeded on chat/tool/JSON for both medium and high.

## Driver shape

Use a separate campaign dir to avoid confusing it with the original July 09 matrix:

```text
runs/requested-regression-matrix-20260709-gpt56-reasoning/
```

Run the same suite sequence as the broad regression matrix, but only the new candidate files:

```bash
python3 scripts/gb-run.py --suite tool-call-behavior --candidates candidates.gpt56-reasoning-mcp.json
python3 scripts/gb-run.py --suite mcp-tools --candidates candidates.gpt56-reasoning-mcp.json
python3 scripts/gb-run.py --suite mcp-tools-hard --candidates candidates.gpt56-reasoning-mcp.json
python3 scripts/gb-run.py --suite mcp-session --candidates candidates.gpt56-reasoning-session.json
python3 scripts/gb-run.py --suite den-mcp-ambiguity --candidates candidates.gpt56-reasoning-mcp.json
python3 scripts/gb-run.py --suite den-mcp-ambiguity-hinted --candidates candidates.gpt56-reasoning-mcp.json
python3 scripts/gb-run.py --suite autonomy-calibration --candidates candidates.gpt56-reasoning-fuzzy.json
python3 scripts/gb-run.py --suite evidence-grounding --candidates candidates.gpt56-reasoning-fuzzy.json
```

Then run codebase analysis with suffixed model specs and a combined report.

## Reporting pattern

Generate combined old+new HTML reports by passing run IDs from both campaigns to `gb-report.py`:

```bash
python3 scripts/gb-report.py \
  --runs <old-july09-run-ids>,<new-gpt56-run-ids> \
  --view grid \
  --embed output \
  --limit 800 \
  --title "GoblinBench agentic fitness — old matrix + GPT-5.6 medium/high" \
  --out runs/requested-regression-matrix-20260709-gpt56-reasoning/<group>-combined-grid.html
```

Report medium/high variants as separate rows; the interesting question is whether the model family hard-swings with effort.

## Verification used in-session

After patching runner support and writing candidates/driver:

```bash
python3 -m py_compile scripts/gb/runners/fuzzy_agent.py scripts/gb/runners/mcp_session.py scripts/codebase-analysis-runner.py
bash -n scripts/run-gpt56-reasoning-regression-matrices-20260709.sh
python3 -m pytest tests/ -q
```

Observed result: `30 passed`.
