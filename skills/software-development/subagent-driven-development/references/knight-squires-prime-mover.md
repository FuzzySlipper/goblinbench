# Knight + squires orchestration pattern

Use this pattern for coding-heavy work where the highest-quality model is also the best coder, and giving it a pure "manager chair" wastes its main advantage.

## Core idea

- The best/expensive coding model is the **knight**: the prime mover that owns architecture, key implementation decisions, and substantive code changes.
- Cheaper/fresher helpers are **squires**: subagents that gather context, inspect files, run narrow checks, summarize findings, and review the knight's work.
- The harness should be at pains to conserve the knight's context and effort. The knight should read less raw repo surface area and consume more condensed reports.

## Default routing

1. **Discovery/context gathering**
   - Do not have the knight manually read directories and many files when avoidable.
   - Send squires to inspect repo structure, locate relevant files, summarize conventions, or compare prior artifacts.
   - Require squires to return concise, source-attributed reports: paths, relevant symbols, commands run, failures, and uncertainty.

2. **Task triage**
   - For trivial/easy/isolated coding work, send a subagent coder with tight instructions and tests.
   - For substantive architecture or implementation work, the knight implements directly after consuming squire reports.

3. **Implementation support**
   - Use squires for narrow gopher jobs: find callers, inspect test fixtures, run targeted command variants, extract failure patterns, or draft migration/checklist notes.
   - Avoid parallel squires touching the same files unless the controller can reconcile overwrites and rerun builds.

4. **Review**
   - For substantive work, the knight should not self-review as the only gate.
   - Send a squire reviewer with exact changed files, spec, and verification commands.
   - The knight fixes issues and runs final verification.

## Model-fit notes from GoblinBench

- Great coders are often good orchestrators; management quality and coding quality are correlated enough that excluding the best coder from implementation can be wasteful.
- Kimi-like models can be sporadically brilliant for review, architecture theory, prose, and roundtable/council analysis, but unreliable for Den/tool discipline.
- Stepfun-like models are often the opposite: solid and reliable, weaker at deep analysis.
- GLM-like models can be strong all-rounders when hosted reliably.
- QwenMax-like models may justify prime-mover placement because coding is the point of many workflows.

## Prompt/harness requirements

- Explicitly instruct the knight to conserve context.
- Prefer "ask a squire to inspect X" over raw directory/file sweeps.
- Require every squire report to be condensed and evidence-linked.
- Treat squire outputs as untrusted summaries for side effects: verify file writes, tests, and external actions before reporting success.
- Preserve durable state/checkpoints outside the knight's context for long jobs.
