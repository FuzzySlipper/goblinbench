# CraftSurvive room variety: five further direct implementations

All five completed, and independent Release procgen checks passed in every worktree. This extends the [first five-model comparison](craftsurvive-room-variety-comparison-20260922.md). The new batch does not show a uniform improvement in code taste or durability: restrained solutions still hide costs or limit variety, while the most ambitious patch repeats a quota regression already found in a cheaper candidate.

These are direct implementations, not stronger-model orchestration of cheaper workers. All began at `0bd77f8407ac49c758b4d6db4da0c538c97b5f64`, with prompt revision 2 explicitly naming the offline catalog pipeline, existing repository instructions, and refreshed Den guidance. MiMo Flash and Qwen also used revision 2; Luna, GLM, and DeepSeek used the earlier ambiguous prompt. No prior patches or review feedback were supplied to these candidates.

| Candidate | Configuration | Delivered approach |
| --- | --- | --- |
| MiMo v2.6 Pro | DSH, default | Seven shapes; filter compatibility, seed-select, score four rotations |
| Muse Spark 1.3 Contributor | DSH, xhigh | Four shapes; seed-rotate sorted catalog and stop at first match |
| Gemini 3.8 Flash | DSH, high | Four shapes; construct compatible matches, then select one |
| GPT-6 Sol | Codex, high | Three shapes; offset sorted catalog by seed plus region hash |
| GPT-6 Astra | Codex, low, explicitly confirmed by owner | Three shapes; hash-prioritize shapes per seed and region |

Review is calibrated to the owner's stated preferences: readable decomposition, explicit computation/allocation costs, and responsibility-based file names. Dense existing code is not an endorsed style. LINQ is allowed. Correctness defects are separated below from optional style changes.

## Sol: restrained, but variety is shallower than it looks

**Outcome: approved for the literal task in this bounded review; variety quality remains a design concern.** Sol delivers square, diamond, and cross shapes with a small production change. It fixes the old outer-loop overwrite using explicit breaks, preserves quota accounting, and adds meaningful connectivity, repeatability, and compatibility checks to the existing production probe.

Its seed choice is unusually simple. From [DungeonGenerator.cs](/home/dev/worktrees/craftsurvive-room-variety-sol-20260922/src/CraftSurvive.Procgen/Generation/DungeonGenerator.cs:187):

```csharp
var hash = offset;
foreach (var character in regionId) hash = unchecked((hash ^ character) * prime);
return unchecked(seed + hash);
```

The caller takes this modulo the number of shapes. With three mutually compatible defaults, ordinary consecutive seeds cycle through three global room assignments: each room advances through the same catalog with its fixed region offset. An external 32-seed probe produced exactly three assignments, all accepted. This satisfies “different seeds should be able to produce different room choices”; it does not provide the richer independent-looking room variation suggested by a general seeded-selection description. The simplicity is real, but so is the limitation. No universal three-assignment claim is needed across unsigned overflow boundaries or other catalogs.

The patch is smaller in concept than Qwen's ranking/fallback system, but it is not especially polished C#. It retains a deeply nested matcher and adds hard-coded shape dimensions despite the repository's named-tuning guidance. Its predicate-based `DefaultRoom` construction avoids repeated exit declarations. Tests live in one larger `DefaultRoomVariety` method rather than a feature-specific test file. Compared with Luna, this is similarly direct, but without the misleading allocating property; compared with DeepSeek, it sacrifices decomposition for minimal disturbance.

## Astra: focused scope, compact expressions conceal real work

**Outcome: approved within the bounded review.** Astra adds only diamond and plus shapes beside the preserved original square. It names room size/center constants, shares construction through `DefaultRoom`, and puts checks in a separate `RoomShapeChecks.cs`. The test file is easy to find, although most checks remain in one long `Verify` method. It covers all three policies, 32 seeds, catalog-order independence, exits, connected room floors, and missing-exit/missing-content alternatives.

From [DungeonGenerator.cs](/home/dev/worktrees/craftsurvive-room-variety-astra-20260922/src/CraftSurvive.Procgen/Generation/DungeonGenerator.cs:187):

```csharp
private static string ShapePriority(ulong seed, string regionId, string shapeId) =>
    Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes($"{seed:X16}|{regionId.Length}:{regionId}|{shapeId}")));
```

The matcher sorts all shapes by this priority for every region, with a shape-ID tie-break. This gives deterministic selection independent of input enumeration order without a custom random mixer. However, UTF-8 encoding, digest allocation, hex-string allocation, and sorting are a lot of work inside a short expression. There is no demonstrated performance problem with three shapes. Relative to the owner's preference, the issue is that brevity makes these costs easy to skim past.

Astra's scope is more restrained than Qwen's: no changed budgets, footprint preference, or oversized fallback. It also avoids Sol's simple cyclic seed behavior. It does not deliver DeepSeek-style matching decomposition or GLM's dedicated selector file. I would describe it as a focused, usable patch with an identifiable cost-visibility tradeoff, not an unambiguous style leader.

## MiMo Pro: more ambition, and a confirmed regression

**Outcome: changes requested before adoption because of quota regression.** Pro expands to seven shapes, including a ring with eight exits, a tee, an elbow, and a corridor. It separates exit assignment and candidate counting into named helpers and adds a well-organized `RoomShapeVarietyChecks.cs`. Those responsibilities and named tests are easier to navigate than Flash's large test routine.

It also takes on more behavior. After choosing a compatible shape, it constructs exit assignments for all four rotations, scores their directional alignment, and uses the seed to break ties. From [DungeonGenerator.cs](/home/dev/worktrees/craftsurvive-room-variety-mimo_pro-20260922/src/CraftSurvive.Procgen/Generation/DungeonGenerator.cs:165):

```csharp
var scoredTurns = new List<(int Turns, int Score, Dictionary<string, CatalogExit> ExitMap)>(QuarterTurns);
for (var turns = 0; turns < QuarterTurns; turns++)
{
    CountCatalogCandidate(policy, requirements.Count, counters);
    if (!cache.TryGetValue((chosen.Id, turns), out var transformed)) cache[(chosen.Id, turns)] = transformed = Transform(chosen, turns);
    scoredTurns.Add((turns, AssignExits(requirement, rooms, transformed, out var exitMap), exitMap));
}
```

This is understandable work for asymmetric rooms, but it introduces rotation optimization and temporary maps beyond the simpler catalog extension. Seven shapes and eight-exit support are not automatically wrong; they increase the surface the reviewer has to understand. Numerous catalog coordinates are still literal, and the generic `SeededSelection` helper lives in the mixed-purpose models file rather than a feature-specific file.

**Confirmed failure:** a valid policy with `MaxCatalogCandidatesPerRequirement = 1`, one compatible square, and two regions is accepted by baseline and all four other new candidates. Pro rejects it at `matching / catalog_candidate_quota_exhausted`, with the counter reaching 3. It counts each shape during filtering and each rotation afterward. This is the same class of problem found in DeepSeek, made more pronounced by evaluating four turns.

The candidate notes that large catalogs can exhaust the budget, but this reproduction needs only one shape. Its test instead asserts that the new defaults fit the existing Tight budget (`shape count + four turns`); that does not preserve the prior valid-policy behavior. Closure requires preserving the quota contract while adding selection, verified with this singleton probe. No implementation was changed during review.

Compared directly with MiMo Flash, Pro offers better decomposition and richer shapes but a larger conceptual change and a demonstrated regression. This run gives no basis for assuming the Pro patch is preferable merely because of model tier.

## Muse: conventional integration, little movement toward the preferred style

**Outcome: approved within the bounded review.** Muse adds a bar, a notched room, and a compact square. The catalog helpers have useful names and named dimension constants. Matching rotates the sorted shape array from a seed-derived offset, retains ordered rotations, and stops both loops explicitly once a match exists.

From [DungeonGenerator.cs](/home/dev/worktrees/craftsurvive-room-variety-muse-20260922/src/CraftSurvive.Procgen/Generation/DungeonGenerator.cs:155):

```csharp
var startShape = (int)(StableRegionDraw(seed, requirement.RegionId) % (ulong)orderedShapes.Length);
for (var shapeOffset = 0; shapeOffset < orderedShapes.Length && selected is null; shapeOffset++)
```

This is a fairly conventional extension, close to the GLM/MiMo Flash family of solutions. It avoids allocating a rotated catalog but keeps the dense existing matching body. Its hash helper gives constants names yet compresses several mixing operations onto one line; naming constants is not the same as making the operation readable. Names such as `SplitMixConstantOne/Two` label the numbers but do little to explain the choice of mixer.

The large production `RoomVariety` test checks accepted layouts thoroughly but skips rejected seeds and only insists some succeed. That could weaken regression detection. A narrow independent rerun of its exact 200–231 seed range found all 32 accepted, versus all 32 at baseline, so this review found no concealed rejection in that range. It produced 31 distinct room assignments, versus Sol's three on the same fixture. These are diagnostic observations, not model scores or a requirement to maximize that number.

Muse is less elaborate than Qwen and Pro, but does not materially improve on the earlier candidates' dense-code tendency or DeepSeek's clearer decomposition. No new correctness defect was demonstrated.

## Gemini: simple selection boundary, unnecessary work before selection

**Outcome: approved within the bounded review, with naming and cost-visibility concerns.** Gemini accumulates a `List<MatchedShape>` and seed-selects from it. This is a small change to the existing loop, and the singleton quota probe passes. Its four silhouettes include a pillared room, a useful kind of variation not present in most other patches.

The relevant sequence in [DungeonGenerator.cs](/home/dev/worktrees/craftsurvive-room-variety-gemini-20260922/src/CraftSurvive.Procgen/Generation/DungeonGenerator.cs:171) is:

```csharp
compatible.Add(new MatchedShape(requirement.RegionId, shape.Id, turns,
    new ReadOnlyDictionary<string, CatalogExit>(exitMap),
    new ReadOnlyDictionary<string, CatalogSocket>(transformed.Sockets.ToDictionary(socket => socket.Id, StringComparer.Ordinal))));
```

Every compatible shape gets a complete exit/socket binding before one is chosen. Unlike DeepSeek's filter-first approach, this builds maps and wrappers for candidates immediately discarded. This follows the original loop structure, but makes work proportional to all compatible shapes. The small catalog does not establish a performance defect; the owner's concern about making computation obvious applies directly.

The new hash helper contains unexplained numeric literals, contrary to the named-values guidance. Its `Plus` helper actually uses a Manhattan-radius predicate: the resulting 13-cell shape is a diamond, despite the plus/cruciform naming in code and final prose. The shapes are still distinct and valid; the mismatch makes future maintenance less clear.

Gemini adds overlapping repeatability/variation checks in both production `GenerationProbe` and test `Program.cs`. Both pass, but this is less tidy than a single behavior-organized feature test file. Its final response also presents different region IDs as guaranteeing mixed shapes; modulo selection permits collisions, so the tests demonstrate examples rather than that general guarantee. No requirement demanded every dungeon contain multiple shapes, and this overstatement is not itself a failure of the requested behavior.

## What the ten examples now suggest

There is still no unambiguous leader for the owner's preferences. The new runs sharpen the distinctions:

- **Restraint:** Sol and Astra keep the feature small. Astra avoids Sol's shallow cyclic variety, but its digest/string/sort path has more hidden cost.
- **Readable decomposition:** DeepSeek, Qwen, and MiMo Pro expose responsibilities more clearly. DeepSeek and Pro nevertheless share a confirmed quota regression; Qwen adds policy/fallback complexity.
- **Feature naming:** GLM's separate selector file remains useful. Astra separates its tests; Pro's named test methods are stronger than its helper placement.
- **Cost visibility:** Luna's getter, Astra's compact hash expression, Qwen's eager ranking, and Gemini's prebuilt discarded matches are different examples of work that deserves clearer presentation. None has been established as a performance bottleneck here.
- **Conservative integration:** MiMo Flash and Muse limit changes without strongly improving dense local style. Gemini also follows local structure, but carries redundant verification and misleading shape naming.

These observations concern the preserved first implementations. They do not establish general model rankings, a price-quality relationship, or what the same candidates would produce after a reviewer corrected them. The stronger-model batch did not automatically solve the problems identified in the cheaper batch. It also remains distinct from testing a stronger orchestrator assigning bounded tasks to a cheaper worker; no such runs were started.

## Evidence and limits

Independently verified: all five Release procgen runs passed; all five singleton quota probes ran, with only MiMo Pro rejecting; baseline/Muse/Sol seed probes each accepted 32/32, with respectively 1/31/3 distinct room assignments. Probe sources and results are outside candidate worktrees. Passing the quota probe means the probe ran successfully; Pro's rejection is the finding, not a failed harness process.

All DSH sessions recorded `finish_reason=completed`, the requested model/effort headers, and repository-instruction baselines before their first request. Sol and Astra reported native subagent completion at their requested settings. No terminal infrastructure failure occurred. Candidates reported additional tool/UI/game checks; those claims are retained separately from the independently rerun procgen checks. No visual playtest or exhaustive seed sweep was performed.

Observed DSH elapsed times: MiMo Pro 27.1 minutes, Muse 7.1 minutes, Gemini 14.6 minutes. Uniform native Codex timing and cost were not captured, so these are not comparable cost measurements.

Artifacts: `/home/dev/goblinbench/artifacts/model-comparisons/craftsurvive-room-variety-direct-20260922/`. The manifest links all five worktrees. Each candidate has a tracked diff and a ZIP including new source/test files; DSH also has full session evidence. Source snapshots were compared with worktree contents after review. Candidate implementations were not repaired, committed, merged, or deployed. These are experimental prose-comparison artifacts, **not canonical GoblinBench DB results**.

The eleventh direct candidate, local Qwen 27B at xhigh, completed and passed independent procgen and singleton quota checks. See the [comparison with the earlier local Qwen](craftsurvive-room-variety-qwen27-comparison-20260923.md).
