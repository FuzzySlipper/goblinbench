# Codebase Analysis Mode A — Full-Source Packet (2026-06-16)

Second run with proper full-source embedded packet (72KB, not the 5.6KB hint-leaker from the first run).

## The packet fix

The original `repo-packet.md` was an overview that described each file's known problems (e.g. "In-memory cache with concurrency notes"). Models could rephrase this as findings — DeepSeek Flash "found" 83% of issues this way. Replaced with a `scripts/generate-packet.py` that embeds all source files inline. Results dropped dramatically, but became much more meaningful.

## Results (6 models)

| Model | Recall | TP | FP | Bonus | Evidence | Sev Cal | Duration |
|---|---:|---:|---:|---:|---:|---:|---:|
| **stepfun** | **58%** | **7** | 0 | 0 | 62% | 50% | 334s |
| deepseek-flash | 42% | 5 | 0 | 0 | 80% | 40% | **61s** |
| kimi-code | 33% | 3 | 0 | 1 | 85% | 50% | 258s |
| deepseek-pro | 25% | 3 | 0 | **4** | **100%** | **67%** | 218s |
| qwen-max | 8% | 1 | 0 | 0 | 90% | 50% | 167s |
| minimax | 8% | 1 | 0 | 0 | 90% | 80% | 308s |

**Missing:** glm52 (502 from z.ai backend), mimo-pro (40KB truncated/malformed JSON)

## Key findings

- **Stepfun is the real winner** — 7/12, 0 FP. Only model to find MCP boundary leak.
- **DeepSeek Flash dropped from 83%→42%** when packet switched from hints to real code — the hint packet inflated scores 2x.
- **Hardcoded-lan-ip** — 0/6 models found it.
- **Worker-release-before-completion** — 6/6 found it (easiest issue).
- **Stepfun only model to find**: stale-review-verdict, core-mcp-boundary-leak, tool-schema-description-mismatch, assignment-release-null-state.
- **DeepSeek Pro** had 4 bonus findings — good at serendipitous discovery.

## Den docs

- Full-source run: `goblinbench/codebase-analysis-mode-a-benchmark-2`
- Hint-based run: `goblinbench/codebase-analysis-mode-a-benchmark-1`
