# Maintainability Mini-Service Prose Style-Guidance Matrix (2026-06-22)

Context: third maintainability mini-service matrix, adding a longer prose clean-code/module-boundary prompt and adding `pi-coding-deepseek-flash-den-router`.

Artifacts:
- Den doc: `goblinbench/maintainability-mini-service-prose-style-guidance-matrix-7-models-4-languages`
- Summary: `/home/dev/goblinbench/runs/maintainability-style-prose-guided-matrix-logs/prompt-style-three-way-summary.md`
- Rows JSON: `/home/dev/goblinbench/runs/maintainability-style-prose-guided-matrix-logs/prompt-style-three-way-rows.json`

Reusable findings:
- Report tokens as separate columns: `input`, `output`, `input+output`, `cacheRead`, `total reported`, and `calls`. Total reported tokens alone can mislead because cache-read/context replay dominates some tool-loop cells.
- Longer prose style guidance is not simply equivalent to terse style guidance. It changed style outcomes in model/language-specific and non-monotonic ways.
- Prose prompt improved GLM52/Qwen/Kimi splitting in aggregate, but DeepSeek Pro and StepFun became more centralized than under terse guidance in aggregate.
- Minimax/Rust flipped from timeout in both previous variants to PASS under prose guidance; Minimax/Go became the lone prose failure (9/10 tests, duplicate error mislabeled as existing customer, then timeout before repair).
- DeepSeek Flash prose passed 4/4; split Python/Go but stayed centralized in TypeScript/Rust.

When running future prompt-style variants, preserve separate scenario JSON files (`*-style-<variant>.json`), run language-at-a-time batches, and generate a three-way comparison rather than replacing prior variants.
