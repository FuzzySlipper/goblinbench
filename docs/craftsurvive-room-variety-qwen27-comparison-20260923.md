# CraftSurvive: local dense Qwen comparison

**Outcome: approved within the bounded feature review, with design concerns.** `local-patch/Qwen3.8-27B-GGUF` at `xhigh` completed normally in 6,082.7 seconds (101.4 minutes). Independent Release procgen checks and the singleton-catalog quota probe both passed. No blocking feature defect was demonstrated; this is not exhaustive generation certification.

This is the eleventh direct implementation. It used the same base commit and clarified offline-generation prompt as the earlier `local/qwen-flash-next-pwilkin-iq4` at `xhigh`. Both ran through the refreshed DSH comparison SDK profile with repository instructions and Den guidance, without earlier implementations or review feedback. See the [first five](craftsurvive-room-variety-comparison-20260922.md) and [next five](craftsurvive-room-variety-direct-comparison-20260922.md) for the surrounding comparison.

## What the smaller model produced

It adds four shapes: the preserved square, a square missing its center cell, a notched square, and a minimal plus. The hollow room's content socket is correctly moved off the missing center to a walkable cell. Shared side exits have a named helper; the catalog remains `builtin.rooms.v1`. There is no schema migration machinery, and changing catalog contents without changing this label was not shown to break artifact identity, which includes catalog data.

Matching is split into `CollectOptions`, `ServesRequirement`, seed selection, and `BoundMatch`. Tests live in a feature-specific `RoomShapeVarietyChecks.cs` with named methods for repeatability, variation, traversal, singleton catalogs, and incompatible catalogs. Those are positive examples of the decomposition and discoverable test organization the owner preferred in DeepSeek and the larger Qwen.

From [DungeonGenerator.cs](/home/dev/worktrees/craftsurvive-room-variety-qwen27-20260923/src/CraftSurvive.Procgen/Generation/DungeonGenerator.cs:153):

```csharp
var options = CollectOptions(requirement, requirements.Count, catalog, policy, counters, cache);
if (options.Count == 0) throw new GenerationFailure("matching", "no_matching_exits", $"No catalog shape has enough exits for '{requirement.RegionId}'.");
var draw = SelectionDraw(seed, requirement.RegionId);
var shape = options[checked((int)(Mix64(draw) % (ulong)options.Count))];
var orientation = shape.Orientations[checked((int)(Mix64(Mix64(draw)) % (ulong)shape.Orientations.Count))];
result.Add(BoundMatch(requirement, shape.ShapeId, orientation.Turns, orientation.Transformed, rooms));
```

Selecting a shape before selecting its orientation avoids weighting asymmetric shapes more heavily merely because they have more retained rotations. Binding only the selected option also avoids Gemini's construction of complete exit maps for discarded matches. However, the nested mixes and checked casts obscure this otherwise simple two-step choice. The patch retains several long expressions and hard-coded shape dimensions; it is not consistently verbose about costs or tuning values.

## The added machinery is rotation deduplication

For every region, `CollectOptions` loops through every shape and all four turns. Transformed geometry is cached, but the code rebuilds option objects and computes sorted string signatures each time:

```csharp
private static string OrientationSignature(TransformedShape transformed) =>
    string.Join(",", transformed.Cells.OrderBy(cell => cell.X)
        .ThenBy(cell => cell.Y).Select(cell => $"{cell.X}:{cell.Y}"));
```

This is explicit method work rather than Luna's allocating property, but its allocations and sorting are still buried in compact LINQ. With four tiny shapes no performance bottleneck is demonstrated. The question is whether deduplication warrants this work and additional types for the requested feature.

The equivalence definition is narrower than the comment suggests: it compares only floor cells, ignoring exit directions/identities and socket positions. The new hollow shape has a symmetric floor but an off-center socket, so its rotated socket placements differ even though deduplication retains only turn zero. This does not violate a requirement to offer every socket orientation—the task had none—and the retained socket remains valid. It does mean “same floor” is not “same complete placed room.” That distinction matters if this helper is later reused or extended. I would simplify the optimization or make its intended equivalence explicit rather than treat the current comment as a durable general contract.

The counter now counts shapes examined, not rotation trials. The singleton-square probe accepts with two total candidates, avoiding the DeepSeek/MiMo Pro failure. That result should not be described as unchanged quota semantics: the code explicitly changes what consumes the budget and performs four transforms/checks within one counted shape. It leaves the preset values untouched, but changes their operational meaning. No resulting task-blocking failure was established in this review.

## Compared with the earlier larger Qwen

| Aspect | Earlier Qwen Flash Next IQ4 | Qwen 27B GGUF |
| --- | --- | --- |
| Decomposition | Named selection, compatibility, binding helpers | Similarly clear collection, compatibility, binding helpers |
| Extra work | Hash and sort every shape/rotation per region | Transform variants, then sort/serialize geometry for deduplication |
| Policy expansion | Doubles Tight budget; adds oversized fallback | Keeps preset values; changes counter unit to shapes |
| Test organization | Separate behavior-named test file, wider graph/preset matrix | Separate behavior-named file, 16 seeds on one richer fixture |
| Independent singleton quota probe | Accepted | Accepted |
| Observed elapsed time | 52.1 minutes | 101.4 minutes |

The smaller model did not show a clear collapse in code organization or completion. Its top-level flow is competitive with the larger model's, and it avoided that patch's footprint fallback and budget increase. It still introduced an optimization whose semantics need care, so it is not an unambiguous improvement in restraint or durability. Both provide concrete examples of useful decomposition paired with extra machinery.

The roughly doubled elapsed time describes these two local runs, not an isolated architecture or model-size effect. Hardware, serving configuration, quantization, context processing, and amount of agent work were not controlled or measured uniformly. No cost or throughput ranking is inferred.

## Evidence retained

- Independently ran `dotnet run --project tests/Procgen/Procgen.csproj -c Release`: passed.
- Independently ran the existing singleton square / quota-one probe: valid policy, accepted, two candidates.
- Session ended with `finish_reason=completed`; the request header records the exact route and `xhigh`, with automatic repository instructions before the request.
- Candidate reports additional offline-tool, Workbench, TerrainResidency, UI, and Release game checks. Those were not all independently repeated. Its deliberately false-assertion check confirms test wiring, not strong mutation coverage of the feature.
- No visible playtest, exhaustive seed sweep, or implementation repair was performed.

Artifacts: `/home/dev/goblinbench/artifacts/model-comparisons/craftsurvive-room-variety-qwen27-20260923/`. The manifest, response, events, tracked patch, new-file ZIP, independent check logs, and quota probe are retained. Candidate source bytes were checked against the snapshot after review. The implementation remains uncommitted in its worktree. These experimental results are **not in the canonical GoblinBench DB**. No orchestrated runs were started.
