# Maintainability Style-Prompt Variant Pattern (2026-06-22)

Use this reference when running GoblinBench maintainability mini-service prompt-variant matrices: baseline vs economical explicit style guidance vs prose/verbose clean-code guidance.

## Why this variant matters

The user wants to measure whether extra descriptive style language changes model implementation style, not just whether behavior tests pass. The hypothesis space is intentionally fuzzy:

- Models may treat extra prose as redundant and produce the same code.
- Extra prose may increase perceived importance of maintainability and strengthen seam-splitting.
- Extra prose may nudge different coding patterns (more named helpers, different module boundaries, more/less over-engineering).
- Extra prose may increase token/tool-call cost without materially changing style.

Therefore preserve behavior pass/fail, architecture metrics, and token accounting separately.

## Scenario shape

Create separate scenario JSONs rather than mutating the baseline or existing economical `*-style-guided` scenarios:

```text
suites/coding/maintainability-mini-service-python-style-prose-guided.json
suites/coding/maintainability-mini-service-typescript-style-prose-guided.json
suites/coding/maintainability-mini-service-go-style-prose-guided.json
suites/coding/maintainability-mini-service-rust-style-prose-guided.json
```

Recommended ID suffix:

```text
-style-prose-guided
```

Recommended tags:

```text
style-prose-guided
style-guided
prompt-variant
verbose-style-prompt
```

Append the prose guidance after the existing task, not before it. This keeps the functional task stable and makes the style variable easy to inspect.

## Prose guidance intent

The prose variant should be deliberately less economical than the concise style-guided block. It should talk about:

- behavior tests as the floor, not the definition of done;
- future maintainers extending the import workflow;
- handler as orchestration, not a dumping ground;
- validation, normalization, duplicate detection, persistence, audit payloads, and serialization behind cohesive helpers/modules;
- clear names and boundaries over clever compactness;
- no framework/layer explosion just to look architectural;
- prefer slightly longer clear code over dense central functions.

Keep it language-neutral enough that the same concept can be appended to Python, TypeScript, Go, and Rust scenarios.

## Batch runner pattern

Run language-at-a-time, with candidates sequential inside each `gb-run.py` invocation. Include both the existing 6-model matrix and `pi-coding-deepseek-flash-den-router` when comparing against the earlier baseline/style-guided runs.

Candidate order used for the 7-model prose matrix:

```text
pi-coding-deepseek-flash-den-router
pi-coding-deepseek-pro-den-router
pi-coding-glm52-den-router
pi-coding-stepfun-den-router
pi-coding-minimax-den-router
pi-coding-qwen-max-den-router
pi-coding-kimi-code-den-router
```

Import each completed run with the current store CLI shape:

```bash
python3 scripts/gb-store.py import --run-json runs/<run-id>/run.json
```

Do not use the stale positional form `gb-store.py import <run-id>`.

## Token reporting: do not use one total column alone

For style-prompt comparisons, always split token usage into at least:

```text
input
output
cacheRead
cacheWrite
totalTokens
calls
```

User-facing summaries should highlight:

- `output` tokens: how much the model actually generated;
- `input + output` or uncached input/output: closer to non-cache effort;
- `cacheRead`: repeated context/tool-loop churn, often large;
- `totalTokens`: reported total, useful but easy to misinterpret;
- `calls`: whether cost came from many small tool turns vs long generated reasoning.

This distinction matters: StepFun's economical style-guided matrix looked very expensive by total tokens, but much of the increase was cache-read/tool-loop churn rather than giant generated reasoning. Minimax failures, by contrast, can be dominated by dithering or slow convergence.

## Interpretation pitfalls

- Do not collapse behavior failure and style failure. A model can pass all tests while centralizing code; another can split cleanly but fail behavior.
- Do not treat lower central changed-mass share as automatically better. Check changed files and code shape; over-engineered extra modules are possible.
- Do not judge strong models solely by timeouts. Inspect patch presence, compile/test output, stdout/trace, and whether the model was exploring, editing, or repairing when killed.
- For Minimax Rust specifically, observed failure modes differed by prompt: baseline wrote a plausible split patch but failed Rust type checking after timeout; prose/economical variants may also stall during exploration. Separate these modes.
- StepFun is often reliable and bounded, but many small tool calls can inflate reported total tokens via `cacheRead`.

## Reporting shape

Produce flat scannable tables first:

1. A/B/C table: baseline → economical style-guided → prose style-guided.
2. Per-model aggregate: pass rate, split-cell count, avg central changed-mass share, token columns.
3. Per-language/model table: status, tests, changed files, central share, handler max, duration, token columns.
4. Notes on model-specific style responsiveness.

Keep dense interpretation in an artifact/Den doc, but give the user a short table-first readout in chat.
