# CraftSurvive: Sol medium orchestrating Luna max

**Outcome: changes requested before adoption.** Nested native Codex delegation worked. Sol delegated the whole feature to one fresh Luna max worker, reviewed the result, and reran checks. It requested no corrections and made no source edits. The final tracked diff and changed source files match the preserved first handoff byte for byte.

The independent Release procgen suite passes, but the existing singleton-square quota probe fails: a valid policy with `MaxCatalogCandidatesPerRequirement = 1` and two regions is accepted at baseline and rejected here at `matching / catalog_candidate_quota_exhausted`, with the counter reaching 3. This is a code finding, not an orchestration infrastructure failure.

## What orchestration actually contributed

The log records approximately 09:20–09:29 UTC on September 23, with Luna's first handoff around 09:27. Sol assigned the complete implementation and focused tests rather than decomposing the feature into bounded subtasks. It preserved the handoff, inspected the patch and existing identity references, and independently reran procgen and offline-tool checks plus `git diff --check`.

Those are real coordination and review activities, but no observed code improvement followed. Sol's log explicitly notices that Tight's candidate allowance rose from 12 to 16 and accepts it. The worker's initial patch is the final patch. This run therefore measures whole-task delegation followed by review, not a stronger model supplying a detailed design or iteratively correcting a worker.

## Code choices and the review miss

Luna adds square, cross, clipped-octagon, and rectangular rooms. The matcher collects a complete `MatchedShape` for every compatible shape and every quarter turn before selecting one. Exit/socket maps and wrappers are constructed for options then discarded. The new default needs sixteen trials per region, and the patch raises Tight's allowance accordingly.

The key difference from the original matcher is the removed rotation-loop break:

```csharp
compatible.Add(new MatchedShape(requirement.RegionId, shape.Id, turns,
    new ReadOnlyDictionary<string, CatalogExit>(exitMap),
    new ReadOnlyDictionary<string, CatalogSocket>(transformed.Sockets.ToDictionary(socket => socket.Id, StringComparer.Ordinal))));
```

A singleton square previously needed one trial per region; now it evaluates all four rotations. Increasing a preset does not preserve behavior for an existing caller supplying a valid smaller budget. Closure requires keeping that valid bounded case working while adding seeded choice. The retained external quota probe is the smallest useful regression check. No candidate implementation was repaired.

This resembles Gemini's eager construction of discarded matches, with four rotations per compatible shape instead of its first compatible rotation. It also resembles Qwen's budget accommodation, but here the increase follows directly from exhaustive enumeration. More compatibility trials are an implementation choice, not a requirement of room variety.

The selection helper uses a SHA-256 digest of a length-prefixed binary encoding of seed, candidate ID, and region ID. This makes encoding boundaries and byte order explicit. Compared with Astra's compact string expression, its allocations and buffer construction are more visible, which aligns with the owner's preference. It is still fairly elaborate for selecting a room from a short list, with three input arrays plus the digest and substantial matching work before selection.

Geometry is expressed through named shape helpers, but dense LINQ and literal dimensions remain. Tests are added as one larger method with connectivity and preservation helpers in `Program.cs`, rather than a feature-specific file with separately named behaviors. They cover repeatability, 24 seeds, exits, sockets, and continuous routes. They exercise the increased Tight preset, not the older valid low-budget behavior. That explains how both worker and orchestrator could get green checks without establishing preservation of this contract.

## Comparison with direct implementations

The result is not demonstrably better than direct Sol or the stronger standalone candidates. Direct Sol passed this quota probe and kept the algorithm smaller, though its seed formula gave shallow cyclic variety. The orchestrated result uses a more thoroughly mixed choice but spends more work on unselected options and introduces a regression. Those are concrete tradeoffs rather than a numerical ranking.

Direct Luna changed the live game terrain under the original ambiguous prompt, while this worker received the clarified offline target. Its different implementation cannot be attributed solely to orchestration. Direct Sol also ran at high effort, while this orchestrator used medium. These differences prevent treating this as a controlled measurement of orchestration benefit.

Most importantly, this run has no before/after correction to examine: Sol approved Luna's first result unchanged. It supplies useful evidence about this review process's limits, especially accepting a preset increase without checking the caller-facing quota behavior. It does not establish that stronger orchestration cannot help, nor does it test a careful decomposition into the bounded tasks where the owner finds Luna especially effective.

## Evidence and preservation

- Native agent tree: `/root/orchestrator_sol_luna` → `/root/orchestrator_sol_luna/luna_impl`, configured as Sol medium → Luna max.
- Same base commit `0bd77f8407ac49c758b4d6db4da0c538c97b5f64`, clarified prompt revision 2, fresh worktree, no prior candidate patches or review feedback.
- Independent `dotnet run --project tests/Procgen/Procgen.csproj -c Release`: passed.
- Independent singleton quota probe: valid policy, rejected at matching, counter 3. Baseline acceptance was established by the retained original probe.
- First-handoff diff and every copied changed source file were compared with the final worktree: identical.
- Orchestrator reports its procgen, offline-tool, and diff checks passed. This review did not repeat every reported lane or perform a visual playtest.

Artifacts: `/home/dev/goblinbench/artifacts/model-comparisons/craftsurvive-room-variety-sol-luna-20260923/`, including `orchestration.md`, `response.md`, `first-handoff/`, final patch/ZIP, independent logs, and quota probe. Worktree: `/home/dev/worktrees/craftsurvive-room-variety-sol-luna-20260923`. Candidate code remains uncommitted and untouched by the comparison reviewer. These are experimental prose-comparison artifacts, **not canonical GoblinBench DB results**.
