# Vision chaotic-description 9-model matrix — 2026-06-25

- Run: `run-20260625-231036-8d1e43ce`
- Command: `python3 scripts/gb-run.py --suite vision ... --candidate <9 vision candidates>` with six legacy UI scenarios skipped.
- Store: imported into `runs/goblinbench.sqlite`, label `vision-chaotic-description-9-model-matrix-2026-06-25`.
- Candidate token budget: all 9 vision candidates set to `max_tokens=8192` for this run.
- Scorer: `vision-description-quality` against deterministic manifests; threshold 0.70.

## Aggregate

| rank | candidate | pass | avg score | min score | avg sec | notes |
|---:|---|---:|---:|---:|---:|---|
| 1 | `grok` | 4/4 | 0.931 | 0.875 | 10.4 |  |
| 2 | `mimo` | 4/4 | 0.925 | 0.900 | 35.1 |  |
| 3 | `lemonade-qwen35-4b` | 4/4 | 0.907 | 0.830 | 36.7 |  |
| 4 | `lemonade-qwen36-35b-mtp` | 4/4 | 0.906 | 0.825 | 41.3 |  |
| 5 | `qwenplus` | 4/4 | 0.904 | 0.862 | 37.3 |  |
| 6 | `lemonade-gemma4-26b` | 4/4 | 0.901 | 0.825 | 51.8 |  |
| 7 | `stepfun` | 4/4 | 0.895 | 0.780 | 15.8 |  |
| 8 | `kimi-code` | 3/4 | 0.681 | 0.000 | 28.2 | map-board |
| 9 | `minimax` | 3/4 | 0.669 | 0.000 | 31.4 | busy-dashboard |

## Per-scenario scores

| candidate | chaotic desk | busy dashboard | map board | warehouse shelf |
|---|---:|---:|---:|---:|
| `lemonade-gemma4-26b` | 0.900 | 0.950 | 0.929 | 0.825 |
| `lemonade-qwen35-4b` | 0.900 | 0.950 | 0.950 | 0.830 |
| `lemonade-qwen36-35b-mtp` | 0.900 | 0.950 | 0.950 | 0.825 |
| `mimo` | 0.900 | 0.950 | 0.950 | 0.900 |
| `kimi-code` | 0.900 | 0.950 | 0.000 ❌ | 0.875 |
| `minimax` | 0.900 | 0.000 ❌ | 0.950 | 0.825 |
| `grok` | 0.950 | 0.950 | 0.950 | 0.875 |
| `stepfun` | 0.900 | 0.950 | 0.950 | 0.780 |
| `qwenplus` | 0.862 | 0.950 | 0.929 | 0.875 |

## Format failures

- `den-router-minimax-vision` / `busy-dashboard`: model produced a detailed response with `<think>` plus JSON-looking content, but the JSON had an unescaped quoted text fragment (`"ng"`) inside a string. Strict scorer recorded 0.0 as a format/parse failure, not as absent visual understanding.
- `den-router-kimi-code-vision` / `map-board`: model produced JSON-looking content, but it used invalid escaped single quotes (`\'`) inside JSON strings. Strict scorer recorded 0.0 as a format/parse failure.

## First-pass takeaways

- All candidates returned from the runner successfully for all 36 cells; no HTTP/timeouts in the final matrix.
- The scorer is currently too easy on synthetic fixtures once JSON parses: 34/36 cells passed and many scores cluster around 0.90–0.95.
- `grok` was fastest and highest by this scorer, but this may mostly reflect clean JSON + concise coverage, not necessarily best real screenshot judgment.
- Lemonade local models were viable but slower (~37–52s average/cell in this run). `Qwen3.5-4B` local was nearly tied with the bigger local models on this synthetic set.
- `stepfun` passed all four and was fast, but dipped on warehouse shelf (0.780; 5/6 required mentions).
- To get more discrimination, add harder fixtures/criteria: smaller text, occlusion, similar decoys, red-herring prompt language, and more nuanced region/relationship expectations.

