# Comparing coding-model taste in a real C# project
*September 22–23, 2026 — eleven direct implementations and one orchestrated implementation.*

## Why this experiment

The question was practical: which models produce code Patch would want to maintain in his own projects? This was not an attempt to publish a leaderboard or isolate abstract model capability. Each model used its usual coding harness, and the review considered completeness, durability, naming, readability, cost visibility, and unnecessary complexity.

The main observation was how arguable the ordering remained. A local 27B Q4 model delivered work worth discussing alongside cloud models. More capable or expensive models did not uniformly produce cleaner or more durable patches. This does not establish general equivalence: one bounded feature gives limited opportunities for differences to emerge.

## Task and environment

The target was Rusty CraftSurvive, a real Rusty Engine downstream project with ordinary C# gameplay and a separate pure-C# offline procgen library. The task was to add a small set of distinct default room shapes and choose compatible shapes using the generation seed. Identical inputs had to repeat, different seeds had to permit different room choices, and required exits, content sockets, and traversable layouts had to remain valid. Candidates were asked to add focused checks using existing tests.

Every run began at the same commit, `0bd77f8407ac49c758b4d6db4da0c538c97b5f64`, in a separate Git worktree. Existing runtime and dependency directories were supplied as shared read-only inputs. Candidates received repository AGENTS.md guidance and resolved Den guidance, but no elaborate new style rubric, previous implementations, or review findings. Changes were left uncommitted for inspection.

OpenAI candidates ran as fresh native Codex subagents. Other candidates ran through the DSH SDK, using the installed DSH runtime and a dedicated profile refreshed from web provider configuration. That profile used the shipped standard tooling plus the installed thinking-effort plugin; credentials remained in the existing DSH home. DSH request headers were checked for the requested route and effort, and logs showed repository instructions arriving before the first request. Default effort means no explicit override was supplied.

The first three runs had an ambiguous target: Luna modified the live game terrain generator, while GLM and DeepSeek modified the offline catalog generator. Both were plausible readings. Every subsequent run added: **“This task targets the catalog-based CraftSurvive.Procgen.Generation pipeline used by the offline generation tool.”** This is an important limitation when comparing the original Luna run with later work.

Review preserved candidate code, inspected diffs and representative samples, and independently reran the Release procgen checks. A small external quota probe was reused across the catalog implementations. Additional targeted probes resolved particular questions; there was no exhaustive seed campaign or visual playtest. Broader build/UI checks reported by candidates were distinguished from independently repeated checks.

## All runs

Elapsed times are observed whole-session times, including model reasoning and tools. They are not tokens-per-second measurements or cost rankings.

| Candidate | Harness / effort | Main observations | Elapsed |
| --- | --- | --- | --- |
| GPT-6 Luna | Codex / max | Direct enum-and-volume composition in live terrain; followed through into masonry. An allocating `Volumes` getter obscured computation cost. Different feature path limits comparison. | Not uniformly captured |
| GLM-5.3 Flash | DSH / max | Conservative catalog extension; useful feature-specific `RoomShapeSelector.cs`. Dense retained code and awkward nested-loop stopping; comment described filtering differently from implementation. | 19.4 min |
| DeepSeek V41 Flash | DSH / max | Clear compatibility/binding decomposition and behavior-named tests. Confirmed quota regression from counting filtering and transform attempts separately. | 7.5 min |
| MiMo v2.6 Flash | DSH / default | Restrained offset-scan integration, including a limited-exit corridor. Dense hash loops and a large test routine; singleton quota probe passed. | 14.3 min |
| Qwen Flash Next pwilkin IQ4 | DSH / xhigh | Good decomposition and test organization. Eager hash-ranking of every variant, oversized-room fallback, and increased Tight budget added complexity. Quota probe passed. | 52.1 min |
| MiMo v2.6 Pro | DSH / default | Seven shapes, named helpers, organized tests, and rotation-alignment scoring. More ambitious than Flash, but reproduced the singleton quota regression. | 27.1 min |
| Muse Spark 1.3 Contributor | DSH / xhigh | Conventional seeded catalog offset; named dimensions but dense matching/mixing code. Its test skips rejected seeds; an independent check of that 32-seed range found all accepted. | 7.1 min |
| Gemini 3.8 Flash | DSH / high | Simple collect-then-select change, but builds complete bindings for discarded alternatives. Overlapping tests; a helper named “Plus” actually generates a diamond. Quota probe passed. | 14.6 min |
| GPT-6 Sol | Codex / high | Small patch and explicit loop stopping. Seed plus fixed region hash yields shallow cyclic variation: only three assignments in a 32-seed probe with three defaults. Meets literal variation requirement. | Not uniformly captured |
| GPT-6 Astra | Codex / low | Focused scope, named dimensions, separate test file. Hashing each shape to a hex string and sorting is substantial work hidden in a compact expression. Quota probe passed. | Not uniformly captured |
| Qwen3.8-27B-GGUF | DSH / xhigh | Clear collection/compatibility/binding helpers and named tests. Avoided the larger Qwen's fallback and preset increase, but added geometry-string rotation deduplication and changed quota accounting to count shapes. Quota probe passed. | 101.4 min |
| Sol orchestrating Luna | Codex / Sol medium → Luna max | Delegated the complete task to one worker; reviewed and reran checks, with no corrections or source edits. Final code exactly matches first handoff. Independent quota probe exposed a regression Sol missed. | About 9 min |

Exact DSH routes: `zai/glm-5.3-flash`, `deepseek-official/deepseek-flash` (displayed as DeepSeek-V41-Flash), `xiaomi/mimo-v2.6-flash`, `local/qwen-flash-next-pwilkin-iq4`, `xiaomi/mimo-v2.6-pro`, `meta/muse-spark-1.3-contributor`, `openrouter/google/gemini-3.8-flash`, and `local-patch/Qwen3.8-27B-GGUF`.

All twelve implementations passed their independently rerun focused procgen checks. That did not mean they preserved every relevant behavior.

## Three concrete examples

### Readable code can still change a contract

The external quota probe uses one compatible square, two regions, and the valid policy setting `MaxCatalogCandidatesPerRequirement = 1`. Baseline accepts it. DeepSeek, MiMo Pro, and orchestrated Luna reject it with `catalog_candidate_quota_exhausted`.

DeepSeek and Pro count compatibility filtering plus later trials. Orchestrated Luna exhaustively evaluates all four rotations even for the singleton square. Its default Tight budget was raised from 12 to 16, so normal checks stayed green, but an existing caller's smaller valid budget stopped working.

These are bounded regressions, not claims that ordinary default generation is broken. They are good examples of why test success and clean-looking decomposition are insufficient evidence of durability.

### Brevity can hide work

Luna's live-game `Volumes` property allocates on each access, including separate terrain and masonry uses. Astra compresses encoding, SHA-256, hex allocation, and sorting into a small selection expression. Gemini constructs maps and wrappers for compatible shapes it then discards.

None was demonstrated to be a performance bottleneck. Patch's preference is that the cost should be obvious even when it is small. LINQ is not banned; verbose C# can be preferable when it exposes materially different work.

### “Equivalent rotations” may not mean equivalent rooms

The 27B Qwen deduplicates rotations using only sorted floor-cell coordinates:

```csharp
private static string OrientationSignature(TransformedShape transformed) =>
    string.Join(",", transformed.Cells.OrderBy(cell => cell.X)
        .ThenBy(cell => cell.Y).Select(cell => $"{cell.X}:{cell.Y}"));
```

That ignores rotated exits and sockets. Its hollow room has symmetric floor geometry but an off-center content socket; deduplication discards rotations with different socket positions. The retained room remains valid, and the task did not require every orientation, so this was not classified as a blocking feature failure. It is a narrower equivalence than the comment implies and extra machinery a maintainer would need to understand.

## The two local Qwens

Patch reports that the larger Qwen ran on Strix Halo and the dense 27B on an RTX 5090; both were Q4 quantizations. The smaller dense model took about twice as long in this agent run, despite the expectation that its hardware/model combination would offer much faster inference.

We did not record token totals, generation throughput, time to first token, context-processing time, or aggregate tool time. Therefore elapsed time cannot distinguish slower inference from more reasoning/output, more agent steps, or serving delays. It is not evidence that the 5090 setup has lower token throughput.

In code terms, the smaller model did not show a clear drop in organization or completion. Both supplied useful decomposition and focused test files; both introduced extra machinery. The larger added ranking and footprint accommodations; the smaller added rotation deduplication and changed the counter's unit. Neither was an unambiguous winner for maintainability.

Future runs would benefit from per-request token counts, first-token latency, generation duration, and tool time. Exact quantization and serving configuration should also be recorded rather than inferred from route names.

## What the orchestrator test established

Nested delegation worked directly: Sol medium spawned Luna max. Sol assigned the whole task, inspected the result, checked identity references, and reran procgen/offline-tool checks. It made no corrections. First-handoff snapshots were verified byte-for-byte against the final patch.

This establishes a functioning delegation workflow and a concrete review miss, not an observed improvement in the code. It did not test a stronger model decomposing the feature into small bounded assignments or correcting a worker iteratively. It also differs from direct Sol's high effort and original Luna's ambiguous prompt.

## What was useful despite the lack of a clear ranking

The discussion clarified project-specific preferences: explicit costs, readable responsibility boundaries, useful file names, and restraint in policy changes. DeepSeek's decomposition was closer to the owner's preference; GLM's selector file naming was better. Existing dense code was not automatically desirable merely because a model matched it. A loud, reviewer-visible failure may be easier to catch than subtle plausible behavior, but neither is excused.

The runs also showed that “more capable model” did not reliably translate into less review work on this feature. Small implementations could be simplistic; elaborate ones could expand scope or change contracts. This task offered little evidence about broader tendencies toward schema systems or excessive validation.

Longer-horizon tasks might separate the models more clearly, but this experiment does not prove that task length alone is the missing variable. Its useful result is a set of concrete maintenance tradeoffs and review failures, rather than a defensible universal ordering.

## Evidence and scope

Each implementation remains preserved in a separate unmerged worktree, with patches, source snapshots, responses, and available session evidence. Review did not repair candidate implementations. All DSH sessions completed normally; no terminal infrastructure failure was recorded.

Detailed local reports are maintained in GoblinBench:
- `docs/craftsurvive-room-variety-comparison-20260922.md`
- `docs/craftsurvive-room-variety-direct-comparison-20260922.md`
- `docs/craftsurvive-room-variety-qwen27-comparison-20260923.md`
- `docs/craftsurvive-room-variety-sol-luna-comparison-20260923.md`

Artifacts live under `/home/dev/goblinbench/artifacts/model-comparisons/`. These are experimental prose comparisons, **not scored runs in the canonical GoblinBench results database**. This document is self-contained so readers do not need access to those local paths.
