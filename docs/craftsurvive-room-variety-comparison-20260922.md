# CraftSurvive room-variety comparison — 2026-09-22

The comparison now covers ten direct candidates. This page preserves the first five;
[the next five and cross-batch synthesis](craftsurvive-room-variety-direct-comparison-20260922.md) cover MiMo Pro, Muse, Gemini, Sol, and Astra.

All five candidates completed, and I independently reran their Release procgen checks successfully. They produced useful code to discuss, but chose different feature paths. Luna changed the game's live dungeon terrain; GLM and DeepSeek changed the separate catalog-based procgen library. The first prompt allowed both interpretations. MiMo and Qwen subsequently received an explicit offline catalog target and both used it. That limits direct comparison of completeness, while still exposing code-style choices and care with existing behavior.

No candidate implementation was corrected, committed, merged, or deployed during review. There are no scores or rankings. These observations concern this run, not general model capability.

## What each implementation changes

| Candidate | Delivered behavior | Approach |
| --- | --- | --- |
| GPT-6 Luna, Codex, max | Four room silhouettes in the game's dungeon terrain studies | Enum, room volumes, existing keyed Engine draw, terrain unions |
| GLM-5.3 Flash, DSH, max | Five catalog shapes selected per region in `DungeonGenerator` | Rotate the sorted catalog from a seed-derived offset; retain existing matching |
| DeepSeek V41 Flash, DSH, max | Five catalog shapes selected per region in `DungeonGenerator` | Filter compatible shapes first, then seed-select; extract matching helpers |
| MiMo v2.6 Flash, DSH, default | Four catalog shapes, including a two-exit corridor | Seeded starting offset through shape/orientation pairs |
| Local Qwen Flash Next pwilkin IQ4, DSH, xhigh | Five catalog shapes sharing four exit lanes | Hash-rank variants, split matching helpers, add footprint preference/fallback |

All began at `0bd77f8407ac49c758b4d6db4da0c538c97b5f64` with existing repository instructions and live Den guidance. The first three shared prompt revision 1; MiMo and Qwen shared revision 2, adding only the explicit target sentence to the feature assignment. Each had a separate branch/worktree. DSH request headers record both requested routes at `max`, and both logs contain automatic repository-instruction baselines. Luna was explicitly launched as `gpt-6-luna` at `max` with a fresh context and a reminder to read its worktree's guidance.

## The task needs one more sentence

The game's `GeneratedDungeonRecipe.Plan` uses `DungeonLevelPlan` and `engine.Random.DrawKeyed`. It does not call catalog-based `DungeonGenerator` for the `dungeon`, `dungeon-layout`, and `dungeon-split` studies. The latter has real callers in the offline artifact generator and procgen tool; it is not unused code.

Luna therefore changes the in-game terrain path. GLM and DeepSeek change generated library artifacts but leave those game studies unchanged. Both DSH transcripts explicitly noticed the separate game path and chose the library interpretation. This was not simply a failure to find the other code.

Our preparation intended the catalog task, but the candidate prompt never named `ShapeCatalog` or `DungeonGenerator`. Luna should not be penalized for that hidden intention. For a repeat, add only: **“This task targets the catalog-based CraftSurvive.Procgen.Generation pipeline used by the offline generation tool.”** Alternatively name the visible dungeon study if that is wanted. Neither clarification prescribes code style or architecture.

A correction to the preliminary scouting: the old matcher does not reliably stop at the first compatible shape in a multi-shape catalog. Its `break` exits only the rotation loop, allowing a later shape to overwrite the selection. Both DSH patches prevent that overwrite.

## Luna: direct product composition

Luna adds an enum and a small volume value type, puts geometry on the existing room record, and extends the terrain recipe to union those volumes. It also updates masonry detail to follow the new shape instead of retaining the old rectangular cuts. That shows attention to the consumer, beyond adding a data declaration.

From [DungeonLevelPlan.cs](/home/dev/worktrees/craftsurvive-room-variety-luna-20260922/src/CraftSurvive.Game/Modules/LevelGeneration/DungeonLevelPlan.cs:40):

```csharp
return Shape switch
{
    DungeonRoomShape.Rectangular => [new(Minimum, Maximum)],
    DungeonRoomShape.Cross => [XAxis(crossHalfDepth), ZAxis(crossHalfWidth)],
    DungeonRoomShape.LongHall => [
        XAxis(depth * HallArmFraction / 2),
        ZAxis(crossHalfWidth)],
    DungeonRoomShape.Chamfered => ChamferedVolumes(width, depth),
    _ => throw new InvalidOperationException($"Unknown dungeon room shape: {Shape}."),
};
```

I find this easy to inspect: the alternatives and geometry are together, there is no strategy hierarchy, and tunable dimensions have local names. Selection adds `Draw("shape")` to the existing path, retaining Engine random authority. Geometry remains ordinary C# product policy using existing implicit-surface primitives.

A style question is `Volumes`: it looks like stored data but computes and allocates a new array on each access. The recipe reads it for carving and again for masonry. With twelve rooms this is not an established performance problem. It is a useful preference to discuss: should construction like this look like a method, or is the compact property acceptable?

The tests are useful but narrower than the final summary suggests. Seed variation uses a synthetic keyed-draw delegate, not a live Engine call. The clearance sweep uses draws `0`, `.5`, and `1`, selecting Rectangular, LongHall, and Chamfered; Cross is selected elsewhere but misses that clearance sweep. I found no demonstrated geometry failure. I did not render or play the game, so appearance and in-game collision are not visually certified.

## GLM: conservative integration and a named selector

GLM keeps the matcher largely intact, adds one selector file, and introduces named shape helpers such as `Plus`, `Diamond`, and `MidpointExits`. It preserves the old square's ID and geometry, even though `room.cross.5` was already a misleading name. This favors limited disturbance over cleanup.

From [RoomShapeSelector.cs](/home/dev/worktrees/craftsurvive-room-variety-glm-20260922/src/CraftSurvive.Procgen/Generation/RoomShapeSelector.cs:16):

```csharp
public static IReadOnlyList<CatalogShape> Rotate(IReadOnlyList<CatalogShape> shapes, ulong seed, string regionId)
{
    ArgumentNullException.ThrowIfNull(shapes);
    ArgumentNullException.ThrowIfNull(regionId);
    if (shapes.Count <= 1) return shapes;
    var offset = Index(seed, regionId, shapes.Count);
    return shapes.Skip(offset).Concat(shapes.Take(offset)).ToArray();
}
```

The helper gives the new responsibility a clear name. Its SHA-256 index uses invariant formatting and explicit byte assembly, avoiding process-randomized string hashes. A cryptographic digest is more machinery than room choice intrinsically needs, but also avoids maintaining a custom mixing algorithm. That is a tradeoff, not a defect.

The [matching change](/home/dev/worktrees/craftsurvive-room-variety-glm-20260922/src/CraftSurvive.Procgen/Generation/DungeonGenerator.cs:159) is small:

```csharp
foreach (var shape in RoomShapeSelector.Rotate(orderedShapes, seed, requirement.RegionId))
for (var turns = 0; turns < 4 && selected is null; turns++)
```

It fixes the overwrite, but termination is carried by the inner loop while the outer loop still walks its remaining entries. Correct here, though less immediately readable than stopping the outer search explicitly. The method otherwise retains the existing dense LINQ lines.

There is a documentation mismatch: the catalog comment describes filtering before seeded choice, while the code rotates the full catalog and then skips incompatible shapes. It still meets the requested behavior, but incompatible entries can influence which valid shape is encountered first. Uniform sampling was not requested, so this is not a failed requirement.

GLM extends the existing production `GenerationProbe` verification surface. That follows a local pattern; it also puts several concerns into one larger routine. The checks cover seeded variety, required sockets/exits, skipping incompatible shapes, and rejection of a socket-less catalog. They passed in the independent rerun.

## DeepSeek: clearer decomposition, with a real regression

DeepSeek makes compatibility a distinct phase and separates exit binding into another method. The algorithm is easier to explain: collect compatible shapes, choose a starting index, then bind a shape.

From [DungeonGenerator.cs](/home/dev/worktrees/craftsurvive-room-variety-deepseek-20260922/src/CraftSurvive.Procgen/Generation/DungeonGenerator.cs:186):

```csharp
private static bool Supports(CatalogShape shape, PieceRequirement requirement) =>
    shape.Exits.Count >= requirement.Connections.Count &&
    requirement.RequiredSockets.All(required => (shape.Sockets ?? Array.Empty<CatalogSocket>()).Any(socket => string.Equals(socket.Kind, required, StringComparison.Ordinal)));
```

The responsibility is well named, although the predicate still has a very long line. Room declarations use named cardinal-direction arguments, making coordinates easier to audit. It versions the catalog as `builtin.rooms.v2`, names the square `room.square.5`, and makes `room.cross.5` an actual cross. That is tidier vocabulary but more identity change than GLM chose. Artifact requests carry full catalogs and hashes; I did not find a specific persisted-artifact break from the rename.

Its [new test file](/home/dev/worktrees/craftsurvive-room-variety-deepseek-20260922/tests/Procgen/DungeonGenerationChecks.cs:15) is organized by behavior:

```csharp
DefaultCatalogOffersDistinctCompatibleShapes();
IdenticalInputsRepeatRoomChoices();
DifferentSeedsVaryRoomChoices();
GeneratedRoomsPreserveExitsContentAndTraversal();
IncompatibleShapesAreNeverChosen();
```

I prefer this organization to GLM's larger probe method. It also checks that restricted shapes remain selectable where compatible, rather than merely checking their rejection elsewhere. The candidate reports mutation checks and broader seed sweeps; I reran its test executable, not every scratch experiment.

**The regression:** matching now increments `CatalogCandidates` while filtering a shape and again while trying its transform. That changes quota accounting. I reproduced the consequence using the same valid policy and singleton square catalog on baseline and both library candidates:

```text
MaxCatalogCandidatesPerRequirement = 1; one compatible square; two regions
baseline: accepted
GLM:      accepted
DeepSeek: rejected at matching / catalog_candidate_quota_exhausted
```

The probe is outside the candidate worktrees under `quota-probe/` in the artifact directory. No candidate code was changed. Standard policies have enough headroom and normal tests pass, so this is a bounded regression, not evidence that ordinary generation is broken. Before adopting this patch I would reconcile the quota accounting with the existing contract. Readability alone did not establish durability.

DeepSeek also puts a complete FNV/SplitMix choice helper in the mixed-purpose models file. Its code is explicit and bounded, but a feature-specific name/file like GLM's might be preferable. An existing private stateful workbench RNG is not a directly reusable public keyed-choice API; this is not an obvious missed direct reuse.

## MiMo: restrained integration, dense execution

**Review outcome: approved within the bounded offline-generation review.** No blocking defect was demonstrated. MiMo adds four shapes and changes matching without altering policy budgets, routing, or placement. The two-exit corridor gives the compatibility check real work; the other shapes preserve the existing square's footprint. Its original `room.cross.5` remains a square, deliberately preserving the old identity and geometry.

The central loop is explicit about stopping once a match is found, unlike GLM's nested-loop termination. From [DungeonGenerator.cs](/home/dev/worktrees/craftsurvive-room-variety-mimo-20260922/src/CraftSurvive.Procgen/Generation/DungeonGenerator.cs:159):

```csharp
var start = ShapeChoiceStart(candidates.Length, seed, requirement.RegionId);
for (var probe = 0; probe < candidates.Length && selected is null; probe++)
{
    var (shape, turns) = candidates[(start + probe) % candidates.Length];
```

Candidates are sorted by shape ID and expanded into all four rotations once per matching call. A small FNV helper chooses the starting index per region, after which existing compatibility and exit binding apply. This avoids a new policy or selector abstraction, and the same singleton-catalog quota probe that caught DeepSeek's regression succeeds here.

The patch's restraint does not make it especially close to the owner's preferred readability. The new hash loops compress multiple operations into each line:

```csharp
for (var shift = 0; shift < 64; shift += 8) { hash ^= (seed >> shift) & 0xFFUL; hash *= FnvPrime; }
foreach (var character in regionId) { hash ^= character; hash *= FnvPrime; }
```

Shape helpers also retain dense LINQ, and three catalog entries repeat their four exit declarations. Those are understandable local choices, but not evidence that matching surrounding density is desirable. Unlike Luna's `Volumes`, construction is expressed through methods; the allocation costs are at least located at explicit calls.

MiMo adds one substantial test routine and one preservation helper to [Program.cs](/home/dev/worktrees/craftsurvive-room-variety-mimo-20260922/tests/Procgen/Program.cs:270). It checks distinct geometry, outward exits, content, repeatability, seed variation, and accepted traversable layouts. Useful behavior checks, but less navigable than DeepSeek's or Qwen's named test files. Its source comment that the full candidate cycle never skips a compatible shape is also conditional on the existing quota permitting that scan; quota exhaustion still stops matching. This is wording to tighten, not a demonstrated task failure.

## Qwen: useful decomposition, with extra policy and work

**Review outcome: approved within the bounded offline-generation review, with non-blocking design concerns.** Qwen delivers the feature and passes both its substantial focused checks and the independent singleton quota probe. Its roughly 52-minute session completed normally; elapsed time alone is not an infrastructure failure or evidence of worse code.

`Match`, `SelectShape`, `Serves`, and `BindExits` make the algorithm easier to navigate. Its separate [RoomShapeVarietyChecks.cs](/home/dev/worktrees/craftsurvive-room-variety-qwen-20260922/tests/Procgen/RoomShapeVarietyChecks.cs:15) organizes tests by behavior and checks connected shapes, actual variation, limited-exit compatibility, and preservation across graphs, presets, and seeds. This aligns with the decomposition the owner liked in DeepSeek.

The five room definitions share exits, sockets, and tags; a `RoomFloor` predicate expresses each silhouette without duplicating whole declarations. Those static collection properties are initialized once, unlike Luna's allocating getter. However, named constants coexist with hard-coded `0`, `4`, `2`, and other dimensions inside the predicates. The abstraction is still specifically a five-cell grid, not truly adjustable by changing its footprint constant alone.

Selection adds more machinery than the other candidates. From [DungeonGenerator.cs](/home/dev/worktrees/craftsurvive-room-variety-qwen-20260922/src/CraftSurvive.Procgen/Generation/DungeonGenerator.cs:178):

```csharp
if (!Serves(transformed, requirement)) continue;
if (FitsRoomSlot(transformed, policy)) return BindExits(requirement, rooms, room, variant.Shape.Id, variant.Turns, transformed);
if (oversize is null || variant.CatalogOrder < oversize.CatalogOrder) oversize = variant;
```

If no serving shape fits, it eventually binds the first serving oversized variant in catalog order. This preserves a route to an existing materialized-bounds rejection, but introduces a second selection rule to understand. Footprint fit is therefore a preference, not an invariant enforced by this helper. This is a concrete example of additional compatibility machinery arising even in this task; it does not establish a general overengineering tendency from one run.

`RankedVariants` computes SHA-256 for every shape/orientation pair, sorts all of them, and materializes the result separately for each region before the first candidate quota check. Its digest uses explicit invariant formatting and endianness, and deterministic tie-breaks are present. The cost is bounded and small for this catalog, but more work than an offset scan. The long LINQ expression makes those operations less conspicuous than the owner prefers; the issue is cost visibility and proportionality, not a LINQ ban.

Qwen also raises [Tight's candidate budget](/home/dev/worktrees/craftsurvive-room-variety-qwen-20260922/src/CraftSurvive.Procgen/Generation/GenerationModels.cs:45) from 12 to 24 and adds a test demanding enough budget for every built-in rotation. All five new default shapes have the same four exits, content socket, and fitting footprint, so a compatible default region can accept its first ranked variant. The larger default catalog does not itself require this increase. Custom incompatible catalogs can consume more trials, but no general promise to exhaust an arbitrary catalog was requested. This is unnecessary policy expansion worth discussing, rather than a demonstrated generation failure.

The candidate reports that broader experiments led it to remove initially oversized shapes. That suggests useful self-correction. It also reports a small acceptance difference on an already frequently rejected shortcut graph (255/512 versus 251/512 rejections), so its own evidence is not a claim of universal seed-for-seed acceptance preservation. Those scratch sweeps were not independently repeated; passing accepted-layout checks does not mean every possible input now generates.

## Reading all five against the owner's preferences

The discussion clarified that allocation and computation costs should be plain, even at the cost of more verbose C#. LINQ is allowed; surrounding dense code is not an endorsed style. DeepSeek's decomposition is closer to the owner's preference, and GLM's feature-specific file naming is better. A loud, reviewer-visible failure can be easier to manage than subtle incorrect behavior; neither is excused by good structure.

With that calibration, MiMo adds evidence for restraint but does not displace DeepSeek on readability. Qwen is closer on decomposition and test organization, while introducing more ranking work and policy accommodation than this feature needs. Neither repeats the demonstrated DeepSeek quota defect. Luna remains a useful example of direct composition whose allocating property hides work; its different feature path prevents a direct implementation comparison. GLM still offers the clearest feature-specific selector file, despite awkward retained loop structure.

There is no unambiguous winner here. These examples identify the supervision each patch would benefit from: cost visibility for Luna, loop clarity for GLM, quota preservation for DeepSeek, readable expansion of dense code for MiMo, and restraint around policy/fallback additions for Qwen. These preferences informed review, not new instructions injected into the second pair's prompts.

The task offers little evidence about unnecessary schema/versioning systems. MiMo, DeepSeek, and Qwen bump a catalog ID; that alone is not schema-system overbuilding. Qwen's fallback and budget change do provide a narrower example of defensive scope expansion to discuss. All five runs also ask cheap models to navigate and own a whole feature independently, whereas their usual role may be bounded work under stronger orchestration. A later comparison of standalone cheap, orchestrated cheap, and standalone stronger output would test that actual workflow.

## Verification and retained work

Independently verified:

- `dotnet run --project tests/Procgen/Procgen.csproj --configuration Release` passed in all five worktrees; logs are `{candidate}-review-tests.log`.
- Singleton catalog/quota probe: baseline, GLM, MiMo, and Qwen accepted; DeepSeek rejected. Sources and output are retained under `quota-probe/`.
- DSH model/effort headers and automatic instruction events. The DeepSeek route is `deepseek-official/deepseek-flash`, displayed as DeepSeek-V41-Flash.

MiMo and Qwen request headers confirm the requested routes: MiMo has no effort override; Qwen records `xhigh`. Both have automatic repository-instruction baseline messages before the first request. Both sessions ended with `finish_reason=completed`, with no terminal infrastructure failure.

Candidates reported broader Release/UI checks; their responses retain those claims. This review did not rerun every reported lane, perform a visible playtest, issue a follow-up change request, or repair implementations.

DSH process durations were about 19 minutes for GLM and 7.5 minutes for DeepSeek. MiMo took about 14.3 minutes and local Qwen 52.1 minutes. These are observations from one run, not scores or comparable dollar costs. Luna timing and cost were not uniformly captured, and no cost ranking is inferred.

| Candidate | Branch | Worktree |
| --- | --- | --- |
| Luna | `codex/room-variety-luna-20260922` | `/home/dev/worktrees/craftsurvive-room-variety-luna-20260922` |
| GLM | `codex/room-variety-glm-20260922` | `/home/dev/worktrees/craftsurvive-room-variety-glm-20260922` |
| DeepSeek | `codex/room-variety-deepseek-20260922` | `/home/dev/worktrees/craftsurvive-room-variety-deepseek-20260922` |
| MiMo | `codex/room-variety-mimo-20260922` | `/home/dev/worktrees/craftsurvive-room-variety-mimo-20260922` |
| Qwen | `codex/room-variety-qwen-20260922` | `/home/dev/worktrees/craftsurvive-room-variety-qwen-20260922` |

Artifacts: `/home/dev/goblinbench/artifacts/model-comparisons/craftsurvive-room-variety-20260922/`.
`manifest.json` records setup/completion. Each candidate directory contains its response, tracked-file patch, and `changed-files.zip` including new source/test files. DSH directories additionally contain events, session metadata, and bounded review summaries. `task.txt` is the common assignment; `den-guidance.md` is the live guidance packet. Shared dependency links were excluded from source snapshots.

The additional pair is retained under `/home/dev/goblinbench/artifacts/model-comparisons/craftsurvive-room-variety-extra-20260922/`, including its clarified prompt, refreshed catalog, session responses/events, patches, new-file snapshots, independent test logs, and quota probes. Candidate source snapshots were checked against the worktrees after verification; review did not alter their implementations.

These are prose-comparison artifacts, **not canonical GoblinBench DB results**. No scorer or `runs/goblinbench.sqlite` ingestion was involved.

The eleventh direct candidate, local Qwen 27B at xhigh, completed and passed independent procgen and singleton quota checks. See the [comparison with the earlier local Qwen](craftsurvive-room-variety-qwen27-comparison-20260923.md).
