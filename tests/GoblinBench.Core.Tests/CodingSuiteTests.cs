using System.Text.Json;
using GoblinBench.Candidates;
using GoblinBench.Core;
using GoblinBench.Scorers;

namespace GoblinBench.Core.Tests;

public class CodingSuiteTests
{
    private static readonly string RepoRoot = FindRepoRoot();

    private static string FindRepoRoot()
    {
        // Use the assembly's physical location rather than AppContext.BaseDirectory,
        // which may point to a temp dir in some test runner environments.
        var assemblyDir = Path.GetDirectoryName(typeof(CodingSuiteTests).Assembly.Location)
            ?? AppContext.BaseDirectory;
        var dir = assemblyDir;
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir, "suites")) &&
                Directory.Exists(Path.Combine(dir, "src")))
                return dir;
            var parent = Path.GetDirectoryName(dir);
            if (parent == dir) break;
            dir = parent;
        }
        return assemblyDir;
    }

    private static bool FixtureExists =>
        Directory.Exists(Path.Combine(RepoRoot, "fixtures", "coding", "retry-policy"));

    // ── CodingCandidateRunner ───────────────────────────────────────────────

    [Fact]
    public void CodingRunner_CanHandle_CodingScriptedOnly()
    {
        var runner = new CodingCandidateRunner();

        Assert.True(runner.CanHandle(new() { Id = "x", CliCommand = "coding-scripted" }));
        Assert.True(runner.CanHandle(new() { Id = "x", CliCommand = "CODING-SCRIPTED" }));
        Assert.False(runner.CanHandle(new() { Id = "x", CliCommand = "scripted" }));
        Assert.False(runner.CanHandle(new() { Id = "x", CliCommand = "noop" }));
        Assert.False(runner.CanHandle(new() { Id = "x", Kind = CandidateKind.Unknown }));
    }

    [Fact]
    public async Task CodingRunner_MissingFixtureCase_ReturnsFailure()
    {
        var runner = new CodingCandidateRunner();
        var scenario = new Scenario
        {
            Id = "coding.test", Suite = "coding", Version = "1.0.0", Name = "T",
            Input = new Dictionary<string, object?>()
        };
        var candidate = new CandidateConfig { Id = "coding-scripted", CliCommand = "coding-scripted" };
        var context = new RunContext
        {
            RunId = "r1",
            RunsRoot = Path.Combine(Path.GetTempPath(), "goblinbench-test-runs"),
            RunDirectory = Path.Combine(Path.GetTempPath(), "goblinbench-test-runs", "r1")
        };

        var result = await runner.RunAsync(scenario, candidate, context);

        Assert.False(result.Success);
        Assert.Contains("fixture_case", result.Error ?? "");
    }

    [Fact]
    public async Task CodingRunner_CopiesFixtureAndAppliesPatch()
    {
        if (!FixtureExists) return; // fixture not deployed in this environment

        var runner = new CodingCandidateRunner();
        var scenario = new Scenario
        {
            Id = "coding.retry-policy", Suite = "coding", Version = "1.0.0", Name = "T",
            Input = new Dictionary<string, object?>
            {
                ["fixture_case"] = "retry-policy"
            }
        };

        var runsRoot = Path.Combine(Path.GetTempPath(), $"goblinbench-coding-{Guid.NewGuid()}");
        var runDir = Path.Combine(runsRoot, "r1");
        var candidate = new CandidateConfig { Id = "coding-scripted", CliCommand = "coding-scripted" };
        var context = new RunContext
        {
            RunId = "r1", RunsRoot = runsRoot, RunDirectory = runDir, RepoRoot = RepoRoot
        };

        var result = await runner.RunAsync(scenario, candidate, context);

        Assert.True(result.Success, result.Error);
        Assert.NotNull(result.Output);

        var fixtureDir = GetFixtureDir(result);
        Assert.NotNull(fixtureDir);
        Assert.True(Directory.Exists(fixtureDir));

        // The patched parser should not contain the intentional bug comment
        var parserPath = Path.Combine(fixtureDir, "src", "RetryPolicyParser.cs");
        Assert.True(File.Exists(parserPath));
        var content = await File.ReadAllTextAsync(parserPath);
        Assert.DoesNotContain("Intentionally incomplete baseline", content);
        Assert.Contains("for (var i = 0; i < count; i++)", content);
    }

    // ── CodingTestScorer ────────────────────────────────────────────────────

    [Fact]
    public async Task CodingTestScorer_NoFixtureDir_ReturnsFail()
    {
        var scorer = new CodingTestScorer();
        var scenario = MakeScenario();
        var result = new CandidateResult
        {
            CandidateId = "c1", CandidateName = "T", CandidateKind = CandidateKind.Unknown,
            Success = true, DurationMs = 10
        };
        var context = new RunContext { RunId = "r1", RunDirectory = "/tmp/test" };

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, context);

        Assert.False(score.Success);
        Assert.Contains("fixture_dir", score.Error ?? "");
    }

    [Fact]
    public async Task CodingTestScorer_BadFixtureDir_ReturnsFail()
    {
        var scorer = new CodingTestScorer();
        var scenario = MakeScenario();
        var result = new CandidateResult
        {
            CandidateId = "c1", CandidateName = "T", CandidateKind = CandidateKind.Unknown,
            Success = true, DurationMs = 10,
            Output = JsonSerializer.SerializeToElement(new
            {
                fixture_dir = "/nonexistent/path/that/does/not/exist"
            })
        };
        var context = new RunContext { RunId = "r1", RunDirectory = "/tmp/test" };

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, context);

        Assert.False(score.Success);
        Assert.Contains("not exist", score.Error ?? "");
    }

    // ── End-to-end: CodingCandidateRunner → CodingTestScorer ───────────────

    [Fact]
    public async Task EndToEnd_ScriptedPatch_PassesAllTests()
    {
        if (!FixtureExists) return; // fixture not deployed in this environment

        var runner = new CodingCandidateRunner();
        var scorer = new CodingTestScorer();

        var scenario = new Scenario
        {
            Id = "coding.retry-policy", Suite = "coding", Version = "1.0.0", Name = "Retry Policy",
            Input = new Dictionary<string, object?> { ["fixture_case"] = "retry-policy" },
            Scoring = new ScoringConfig
            {
                Scorers = new() { "coding-tests" },
                Parameters = new()
                {
                    ["coding-tests"] = new Dictionary<string, object?>
                    {
                        ["test_project"] = "RetryPolicyTests.csproj",
                        ["visible_filter"] = "FullyQualifiedName~Tests.Visible",
                        ["strict_filter"] = "FullyQualifiedName~Tests.Strict",
                        ["timeout_seconds"] = 120
                    }
                },
                Thresholds = new() { ["coding-tests"] = 0.8 }
            },
            TimeoutSeconds = 300
        };

        var runsRoot = Path.Combine(Path.GetTempPath(), $"goblinbench-e2e-coding-{Guid.NewGuid()}");
        var runDir = Path.Combine(runsRoot, "r1");
        Directory.CreateDirectory(runDir);
        var candidate = new CandidateConfig { Id = "coding-scripted", CliCommand = "coding-scripted" };
        var context = new RunContext
        {
            RunId = "r1", RunsRoot = runsRoot, RunDirectory = runDir, RepoRoot = RepoRoot
        };

        var candidateResult = await runner.RunAsync(scenario, candidate, context);
        Assert.True(candidateResult.Success, candidateResult.Error);

        var scoreResult = await scorer.ScoreAsync(scenario, candidate, candidateResult, context);

        Assert.True(scoreResult.Success, scoreResult.Error);
        Assert.Equal(1.0, scoreResult.Score!.Value, precision: 2);
        Assert.True(scoreResult.Passed);
        Assert.Contains("PASS", scoreResult.HumanSummary);
        Assert.Contains("visible 2/2", scoreResult.HumanSummary);
        Assert.Contains("strict 2/2", scoreResult.HumanSummary);
    }

    // ── helpers ─────────────────────────────────────────────────────────────

    private static Scenario MakeScenario() => new()
    {
        Id = "coding.test", Suite = "coding", Version = "1.0.0", Name = "T",
        Scoring = new ScoringConfig
        {
            Scorers = new() { "coding-tests" },
            Parameters = new() { ["coding-tests"] = new Dictionary<string, object?>() },
            Thresholds = new() { ["coding-tests"] = 0.8 }
        }
    };

    private static string? GetFixtureDir(CandidateResult result)
    {
        if (result.Output is not { } output) return null;
        try
        {
            var json = JsonSerializer.Serialize(output);
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.TryGetProperty("fixture_dir", out var fd))
                return fd.GetString();
        }
        catch { }
        return null;
    }

}
