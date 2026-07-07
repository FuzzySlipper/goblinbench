# Vision HUD-chaos distractor matrix — 2026-06-26

- Run: `run-20260626-022642-df01eb2b`
- Store label: `vision-hud-chaos-distractor-9-model-matrix-2026-06-26`
- Scenarios: `vision.inspect-game-hud-overheat-chaos`, `vision.inspect-game-hud-low-health-chaos`
- Candidates: same 9 vision candidates as the chaotic-description matrix.
- Harness changes: two deterministic PIL HUD-chaos fixtures plus optional `distractor_mentions` scoring in `vision-description-quality`.
- Verification: scripted deterministic smoke passed; `pytest tests/ -q` -> `20 passed`.

## Aggregate

| rank | candidate | pass | avg score | min score | focus avg | avg sec | notes |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | `stepfun` | 2/2 | 0.942 | 0.934 | 0.750 | 20.0 |  |
| 2 | `lemonade-gemma4-26b` | 2/2 | 0.930 | 0.877 | 0.875 | 56.2 |  |
| 3 | `kimi-code` | 2/2 | 0.867 | 0.784 | 0.375 | 43.2 |  |
| 4 | `lemonade-qwen36-35b-mtp` | 2/2 | 0.867 | 0.784 | 0.375 | 37.6 |  |
| 5 | `lemonade-qwen35-4b` | 2/2 | 0.859 | 0.784 | 0.375 | 39.8 |  |
| 6 | `minimax` | 2/2 | 0.850 | 0.800 | 0.250 | 16.4 |  |
| 7 | `grok` | 2/2 | 0.830 | 0.784 | 0.375 | 6.6 |  |
| 8 | `qwenplus` | 2/2 | 0.828 | 0.779 | 0.500 | 30.1 |  |
| 9 | `mimo` | 1/2 | 0.492 | 0.000 | 0.500 | 30.8 | low-health parse failure |

`focus avg` is the distractor-resistance score average. 1.0 means no configured center-noise terms appeared in the structured answer; 0.0 means the model mentioned most/all configured center decoys.

## Per-scenario

| candidate | overheat score | overheat focus/hits | low-health score | low-health focus/hits |
|---|---:|---|---:|---|
| `stepfun` | 0.934 | 0.75 (CHAOS BOSS, TARGET) | 0.950 | 0.75 (CHAOS BOSS, bones) |
| `lemonade-gemma4-26b` | 0.984 | 1.00 | 0.877 | 0.75 (CHAOS BOSS, bones) |
| `kimi-code` | 0.784 | 0.00 (SKELETON, DRONE, CHAOS BOSS…) | 0.950 | 0.75 (CHAOS BOSS, bones) |
| `lemonade-qwen36-35b-mtp` | 0.784 | 0.00 (SKELETON, DRONE, CHAOS BOSS…) | 0.950 | 0.75 (CHAOS BOSS, bones) |
| `lemonade-qwen35-4b` | 0.784 | 0.00 (SKELETON, DRONE, CHAOS BOSS…) | 0.934 | 0.75 (CHAOS BOSS, bones) |
| `minimax` | 0.800 | 0.00 (SKELETON, DRONE, CHAOS BOSS…) | 0.900 | 0.50 (CHAOS BOSS, bones, particles) |
| `grok` | 0.784 | 0.00 (SKELETON, DRONE, CHAOS BOSS…) | 0.877 | 0.75 (CHAOS BOSS, bones) |
| `qwenplus` | 0.779 | 0.25 (SKELETON, DRONE, LOOT…) | 0.877 | 0.75 (CHAOS BOSS, bones) |
| `mimo` | 0.984 | 1.00 | 0.000 ❌ | n/a |

## Takeaways

- This scenario shape is more discriminating than the first chaotic-description fixtures. All parseable cells got full required HUD coverage, but focus/distractor behavior varied sharply.
- `stepfun` was the best overall on this scoring shape: clean 2/2, high average score, fast, and only light distractor leakage.
- `lemonade-gemma4-26b` was strong and had perfect focus on overheat, but slower.
- `mimo` was interesting: perfect focus and high score on overheat, then strict-JSON failure on low-health despite visually useful content. This should be classified as structured-output failure, not blank vision failure.
- Several models extracted all HUD facts but also repeated center decoys (`SKELETON`, `DRONE`, `CHAOS BOSS`, etc.). That is exactly the failure mode this harder family is meant to expose.
- Current overall threshold still lets full-HUD-coverage / bad-focus answers pass. If we want the pass/fail to mean “HUD-focused,” increase `distractor_weight` or make focus a required threshold, while keeping the flat focus column either way.

