# Vision chaotic-description matrix pattern (2026-06-25)

Session-specific reference for GoblinBench task #3425: synthetic chaotic screenshot description benchmark for visual-inspect model selection.

## Candidate wiring

Direct Lemonade vision candidates work without den-router or API keys when pointed at den-nimo:

```json
{
  "id": "lemonade-qwen35-4b-q4-vision",
  "kind": "OpenAiModel",
  "model": "Qwen3.5-4B-GGUF",
  "provider": "lemonade",
  "base_url": "http://192.168.1.23:13305/v1",
  "cli_command": "vision-openai",
  "config": {"temperature": 0.0, "max_tokens": 8192}
}
```

Cloud baselines can use local den-router with the same `vision-openai` runner:

```json
{
  "id": "den-router-kimi-code-vision",
  "kind": "OpenAiModel",
  "model": "kimi-code",
  "provider": "den-router",
  "base_url": "http://127.0.0.1:18082/v1",
  "cli_command": "vision-openai",
  "config": {"temperature": 1.0, "max_tokens": 8192}
}
```

Important parameter lessons:
- Prefer `max_tokens: 8192` for wordy/reasoning vision models when the goal is comparative signal rather than cost minimization. Otherwise some models produce empty/truncated visible content or fail before JSON.
- Keep Kimi-family candidates at `temperature: 1.0` through den-router.
- Direct Lemonade endpoint (`192.168.1.23:13305/v1`) is already enough for local vision models; den-router is optional only for central routing/accounting.

## Model set used

Local Lemonade models:
- `Gemma-4-26B-A4B-it-GGUF`
- `Qwen3.5-4B-GGUF`
- `Qwen3.6-35B-A3B-MTP-GGUF`

Cloud/remote den-router models:
- `mimo`
- `kimi-code`
- `minimax`
- `grok`
- `stepfun`
- `qwenplus`

## Run summary

Run: `run-20260625-231036-8d1e43ce`
Store label: `vision-chaotic-description-9-model-matrix-2026-06-25`
Den doc: `goblinbench/vision-chaotic-description-matrix-2026-06-25`

4 scenarios × 9 candidates = 36 cells. All runner calls returned. No HTTP/timeouts.

Aggregate by strict `vision-description-quality` scorer:

| candidate | pass | avg score | avg sec | note |
|---|---:|---:|---:|---|
| `grok` | 4/4 | 0.931 | 10.4 | fastest/top by current scorer |
| `mimo` | 4/4 | 0.925 | 35.1 | clean all-pass |
| `lemonade-qwen35-4b` | 4/4 | 0.907 | 36.7 | small local model competitive |
| `lemonade-qwen36-35b-mtp` | 4/4 | 0.906 | 41.3 | tied-ish with local 4B |
| `qwenplus` | 4/4 | 0.904 | 37.3 | clean all-pass |
| `lemonade-gemma4-26b` | 4/4 | 0.901 | 51.8 | clean but slow |
| `stepfun` | 4/4 | 0.895 | 15.8 | warehouse dipped to 0.780 |
| `kimi-code` | 3/4 | 0.681 | 28.2 | strict JSON parse failure on map-board |
| `minimax` | 3/4 | 0.669 | 31.4 | strict JSON parse failure on busy-dashboard |

## Scoring interpretation pitfall

The two 0.0 cells were not blank/no-vision failures:
- MiniMax produced detailed visual content with `<think>` plus JSON-looking output, but an unescaped quoted text fragment inside a JSON string made strict parsing fail.
- Kimi-code produced JSON-looking content but used invalid escaped single quotes inside JSON strings.

When reporting results, separate:
1. runner/HTTP success,
2. strict structured-output compliance,
3. visual-understanding/content quality.

For future versions, consider adding a secondary lenient content-extraction score or a repair-only diagnostic score, but keep strict JSON as a service-readiness gate.

## Harness/discrimination lessons

- Synthetic fixtures are valuable for deterministic smoke and calibration, but the first fixture set was too easy once JSON parsed: 34/36 cells passed and scores clustered near 0.90–0.95.
- To discriminate better, add harder fixtures: smaller text, occlusion, similar decoys, red-herring prompt language, visually plausible forbidden claims, and more specific relationship/region expectations.
- For long buffered GoblinBench runs, artifact directories under `runs/<run>/scenarios/.../candidates/...` are written incrementally. If stdout is silent because Python is buffered, inspect partial `scores.json`/`output.json` rather than killing the run.
