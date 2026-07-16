# Agent-lab → GoblinBench coding-suite port

Session-specific detail from restoring the old FuzzySlipper/agent-lab coding evals in GoblinBench.

## Source layout observed upstream

`agent-lab` keeps cases in a regular C# structure:

```text
EvalCases/<slug>.md                         # ticket/prompt text
EvalLab.Core/Cases/<CaseDir>/*.cs           # broken starter implementation
EvalLab.Tests/Visible/<Case>VisibleTests.cs # visible tests
EvalLab.Tests/Strict/<Case>StrictTests.cs   # strict tests
EvalLab.Tests/Support/*.cs                  # shared test helpers
```

Useful slugs and core directories:

| slug | core dir | visible test | strict test |
| --- | --- | --- | --- |
| `cache-key` | `CacheKeys` | `FilterCacheKeyVisibleTests.cs` | `FilterCacheKeyStrictTests.cs` |
| `export-report` | `ExportReport` | `ExportReportVisibleTests.cs` | `ExportReportStrictTests.cs` |
| `expression-evaluator` | `ExpressionEvaluator` | `ExpressionEvaluatorVisibleTests.cs` | `ExpressionEvaluatorStrictTests.cs` |
| `kth-selection` | `KthSelection` | `KthSelectionVisibleTests.cs` | `KthSelectionStrictTests.cs` |
| `roman-numerals` | `RomanNumerals` | `RomanNumeralsVisibleTests.cs` | `RomanNumeralsStrictTests.cs` |
| `tree-prune` | `TreePrune` | `TreePruneVisibleTests.cs` | `TreePruneStrictTests.cs` |
| `weighted-split` | `WeightedSplit` | `WeightedSplitVisibleTests.cs` | `WeightedSplitStrictTests.cs` |

`retry-policy` was already present in GoblinBench but should use the same threshold semantics as the imported agent-lab tasks.

## GoblinBench fixture shape that worked

Preserve the upstream `EvalLab.Core` / `EvalLab.Tests` path shape inside each fixture so original ticket target paths remain meaningful:

```text
fixtures/coding/<slug>/
  EvalLab.Core/Cases/<CaseDir>/*.cs
  EvalLab.Tests/Visible/<Case>VisibleTests.cs
  EvalLab.Tests/Strict/<Case>StrictTests.cs
  EvalLab.Tests/Support/PlaceholderScanPatterns.cs
  EvalLab.Tests/Support/TreeSerialize.cs      # only for tree-prune
  <Case>Tests.csproj
```

Use a single self-contained test project rather than project references:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <IsPackable>false</IsPackable>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
  </PropertyGroup>
  <ItemGroup>
    <Compile Include="EvalLab.Core/**/*.cs" />
    <Compile Include="EvalLab.Tests/**/*.cs" />
  </ItemGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.14.1" />
    <PackageReference Include="xunit" Version="2.9.3" />
    <PackageReference Include="xunit.runner.visualstudio" Version="3.1.4" />
    <Using Include="Xunit" />
  </ItemGroup>
</Project>
```

Pitfall: do not copy `TreeSerialize.cs` into non-`tree-prune` fixtures unless all fixtures also include `TreePrune` source; otherwise non-tree builds fail because the helper imports `EvalLab.Core.Cases.TreePrune`.

## Scenario JSON conventions

For each imported case:

- `id`: `coding.<slug>`
- `input.task`: exact text from `EvalCases/<slug>.md`
- `input.fixture_case`: `<slug>`
- `input.agent_lab_source`: upstream prompt URL
- `input.agent_lab_fixture_source`: upstream fixture URL
- `scoring.parameters.coding-tests.test_project`: explicit `<Case>Tests.csproj`
- `visible_filter`: `FullyQualifiedName~EvalLab.Tests.Visible`
- `strict_filter`: `FullyQualifiedName~EvalLab.Tests.Strict`
- `scan_dir`: `EvalLab.Core/Cases/<CaseDir>`
- `thresholds.coding-tests`: `1.0` for all-pass success semantics

The `1.0` threshold is important: old agent-lab coding tasks should not pass just because visible tests and most strict tests passed. During this port, `kth-selection` scored ~0.96 with one strict failure under weighted partial scoring; threshold `0.8` would have incorrectly accepted it.

## Verification pattern used

1. Build each generated fixture project.
2. Run visible and strict filters directly to confirm the expected broken-starter baseline shape.
3. Use the first-class candidate filter (`--candidate coding-scripted`) to avoid accidentally launching real model candidates while still exercising normal candidate discovery.
4. Run GoblinBench scenario/suite with that deterministic candidate.
5. Inspect `run.json` coding-test scores and per-scenario artifacts.
6. Run full repo tests.

Commands:

```bash
dotnet build fixtures/coding/<slug>/<Case>Tests.csproj -v quiet
dotnet test fixtures/coding/<slug>/<Case>Tests.csproj --no-build --filter FullyQualifiedName~EvalLab.Tests.Visible -v quiet || true
dotnet test fixtures/coding/<slug>/<Case>Tests.csproj --no-build --filter FullyQualifiedName~EvalLab.Tests.Strict -v quiet || true

dotnet run --project src/GoblinBench.Runner --no-build -- \
  --suite coding \
  --candidate coding-scripted

dotnet test --no-restore
```

## Local pi/Lemonade candidate wiring pattern

For local OpenAI-compatible servers used through `@earendil-works/pi-coding-agent`, provider registration can be done with a repo-local pi extension and launched with `--no-extensions --extension <path> --provider <id>`. This is safer than relying on globally installed extensions and keeps benchmark candidate config reproducible.

Verification sequence that worked:

1. Probe the model server endpoint (`/v1/models`) outside the harness.
2. Ask pi to list models through the extension/provider before running a scenario.
3. Run a harmless/smoke scenario and inspect `agent.patch` for scratch-file leakage.
4. Only then run real coding scenarios.

Candidate argv shape used during the port:

```text
pi ... --no-extensions --extension scripts/lemonade-pi-extension.js --provider lemonade
```

If the agent exits nonzero but scoring still produces partial pass counts, report both facts separately: infrastructure launch path may be working while the model/agent behavior still fails the task.

## Local Lemonade/Qwen coding-suite eval readout pattern

When running a full restored coding suite against a local Lemonade model:

1. Confirm the exact model from Lemonade before spending benchmark time:
   - `curl -sS http://<lemonade-host>:<port>/v1/models`
   - pi provider listing through the repo-local extension, e.g. `--no-extensions --extension scripts/lemonade-pi-extension.js --list-models lemonade`.
2. Run a small `coding-smoke` scenario first. If the smoke fails, diagnose provider/sandbox/runtime before running the suite.
3. Run the full suite with a first-class candidate filter, not by editing `candidates.json`:
   - `dotnet run --project src/GoblinBench.Runner --no-build -- --suite coding --candidate <candidate-id>`
4. Always generate both Markdown and JSON reports:
   - `dotnet run --project src/GoblinBench.Runner --no-build -- report <run-dir> --suite coding`
5. Compare to old agent-lab-style baselines using total visible/strict counts, not only per-scenario weighted scores. For the restored agent-lab suite, the old inspected broken-starter baseline was visible `11/22`, strict `16/50`, score about `50.3`.
6. Treat repeated `exit 137`/SIGKILL results as partial-run evidence, not clean model-quality evidence. If scoring still runs, record both:
   - runner/process status (`FAIL 137`, timeout, no stderr, etc.)
   - coding-test status (visible/strict/marker counts from whatever patch/workspace was left behind)

A partial run can be numerically close to a baseline because unchanged starter code already passes some tests. That is useful for sanity checking harness plumbing, but do not overclaim it as a completed-agent quality metric unless the runner status is clean.

## Artifact isolation bug and fix pattern

Problem found: suite runs reused `runs/<run-id>/candidates/<candidate-id>/...` for every scenario. Because `CodingCandidateRunner` copied each new fixture into the same destination, later scenario fixture directories accumulated files from previous scenarios. `CodingTestScorer` then reported cumulative pass counts, e.g. later scenarios counting earlier tests.

Fix pattern:

- Add a scenario id to the run context or equivalent.
- Route candidate directories to scenario-scoped paths when scenario id is present:

```text
runs/<run-id>/scenarios/<scenario-id>/candidates/<candidate-id>/...
```

- Ensure candidate runner, scorer artifacts, `scores.json`, `trace.jsonl`, and final console artifact paths all use the same scenario-scoped context.
- Keep old `runs/<run-id>/candidates/<candidate-id>` behavior for code/tests that do not set a scenario id, to avoid breaking existing single-scenario unit tests.

## Follow-ups and harness ergonomics noted

- Keep non-eval smoke scenarios out of the real legacy coding suite. During this port, `e2e-pi-mock` was moved from suite `coding` to suite `coding-smoke` so `--suite coding` contained exactly the 8 old agent-lab tasks.
- A first-class `--candidate` filter is useful for verification to avoid temporary one-candidate JSON files and accidental real model launches. Support both single ids and comma-separated ids when practical.
- Separate agent process outcome from patch scoring outcome in reports: `agent_exit_ok`, `patch_produced`, `tests_passed`, `score`, `overall_pass`.
- For coding-suite aggregate reports, preserve scorer detail payloads in machine-readable report JSON; do not reduce visible/strict/marker counts to only a human summary string. A useful Markdown table has columns like scenario, candidate, runner status, test status, score, visible pass/total, strict pass/total, marker count, and duration.
- Candidate runners that execute JS/TS agents inside the workspace may create runtime scratch directories (`.tmp`, `.cache`, `.home`, `.dotnet-home`, jiti caches, npm caches). Filter these from candidate diffs and add a regression test so generated cache files cannot become part of `agent.patch`.
