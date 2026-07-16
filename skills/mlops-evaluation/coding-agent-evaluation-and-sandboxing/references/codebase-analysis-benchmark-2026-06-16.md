# Codebase Analysis Mode A Benchmark — den-core-v1 (2026-06-16)

**WARNING: The original 4-model runs used a hint-leaking packet that described each file's known problems in prose. The 8-model rerun embeds full source code without issue hints. The two batches are NOT directly comparable.**

## Initial 4-model runs (leaky packet — 5.6KB of hints)

These scores are inflated by hint leakage. Packet described file purposes ("TaskRepository has concurrency notes") — models could rephrase hints as findings.

| Model | Recall | TP | FP | Duration |
|---|---:|---:|---:|---:|
| glm52 | 92% | 11 | 0 | 237s |
| deepseek-flash | 83% | 10 | 1 | 47s |
| deepseek-pro | 75% | 9 | 2 | 138s |
| stepfun | 58% | 7 | 2 | 140s |

## 8-model rerun (full-source packet — 90KB of code)

Rerun in progress. Results will replace the above once complete.

- Models: deepseek-flash, deepseek-pro, glm52, stepfun, kimi-code, qwen-max, mimo-pro, minimax
- Packet: embedded full source (~3000 lines across 36 files)
- Den doc: `goblinbench/codebase-analysis-mode-a-benchmark-1` (will be updated)

## Methodology

See `references/codebase-analysis-benchmark-methodology.md` for the canonical design, including gold-ledger patterns, decoy design, packet generation, scoring rubric, and the critical "no hint-leakage" rule.

## Files

- Fixture: `/home/dev/goblinbench/fixtures/codebase-analysis/den-core-v1/`
- Packet generator: `/home/dev/goblinbench/scripts/generate-packet.py`
- Runner: `/home/dev/goblinbench/scripts/codebase-analysis-runner.py`
- Den doc: `goblinbench/codebase-analysis-mode-a-benchmark-1`
