using System.Text.Json;
using GoblinBench.Core;
using GoblinBench.Runner;

namespace GoblinBench.Core.Tests;

public class ReportGeneratorTests
{
    private static RunResult MakeRun(string runId, string scenarioSuite, string[] candidateIds,
        double score = 1.0, bool passed = true, long latencyMs = 100)
    {
        var scenario = new PerScenarioResult
        {
            ScenarioId = $"{scenarioSuite}.test-scenario",
            ScenarioVersion = "1.0.0",
            CandidateResults = candidateIds.Select(cid => new CandidateResult
            {
                CandidateId = cid,
                CandidateName = cid,
                CandidateKind = CandidateKind.OpenAiModel,
                ModelIdentity = new ModelIdentity { Model = $"model-{cid}", Provider = "test" },
                Success = true,
                DurationMs = latencyMs,
                Scores = new List<ScoreResult>
                {
                    new()
                    {
                        ScorerId = "orchestrator-decision", ScorerName = "Orchestrator Decision",
                        ScoringKind = "deterministic", Success = true,
                        Score = score, Passed = passed,
                        HumanSummary = passed ? $"PASS: action matched (1.00)" : $"FAIL: wrong action (0.00)"
                    },
                    new()
                    {
                        ScorerId = "latency", ScorerName = "Latency",
                        ScoringKind = "metadata", Success = true,
                        Score = 1.0, Passed = true,
                        HumanSummary = $"{latencyMs}ms"
                    }
                }
            }).ToList()
        };

        return new RunResult
        {
            RunId = runId,
            StartedAt = DateTime.UtcNow.AddMinutes(-5),
            CompletedAt = DateTime.UtcNow,
            Label = $"test run {runId}",
            Scenarios = new List<string> { scenario.ScenarioId },
            Results = new List<PerScenarioResult> { scenario }
        };
    }

    // ── LoadRunsAsync ───────────────────────────────────────────────────────

    [Fact]
    public async Task LoadRunsAsync_MissingPath_ReturnsEmptyData()
    {
        var data = await ReportGenerator.LoadRunsAsync(new[] { "/nonexistent/run.json" });
        Assert.Empty(data.Candidates);
        Assert.Empty(data.Scenarios);
    }

    [Fact]
    public async Task LoadRunsAsync_ValidRunJson_LoadsData()
    {
        // Write a temp run.json
        var dir = Path.Combine(Path.GetTempPath(), $"goblinbench-report-test-{Guid.NewGuid()}");
        Directory.CreateDirectory(dir);
        var run = MakeRun("test-run-001", "orchestrator", new[] { "qwen3", "gemma4" });
        await File.WriteAllTextAsync(Path.Combine(dir, "run.json"),
            JsonSerializer.Serialize(run, new JsonSerializerOptions
            {
                PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
            }));

        var data = await ReportGenerator.LoadRunsAsync(new[] { dir });

        Assert.Contains("test-run-001", data.RunIds);
        Assert.Equal(2, data.Candidates.Count);
        Assert.Single(data.Scenarios);
        Assert.Contains("orchestrator.test-scenario", data.Scenarios[0].ScenarioId);
    }

    // ── RenderMarkdown ──────────────────────────────────────────────────────

    [Fact]
    public void RenderMarkdown_ContainsExpectedSections()
    {
        var run = MakeRun("run-abc", "orchestrator", new[] { "qwen3", "gemma4" });
        var data = BuildDataFromRun(run);

        var md = ReportGenerator.RenderMarkdown(data);

        Assert.Contains("# GoblinBench Comparison Report", md);
        Assert.Contains("## Candidate Overview", md);
        Assert.Contains("## Scenario Scores", md);
        Assert.Contains("qwen3", md);
        Assert.Contains("gemma4", md);
    }

    [Fact]
    public void RenderMarkdown_ShowsPassRateAndLatency()
    {
        var run = MakeRun("run-abc", "orchestrator", new[] { "qwen3" }, latencyMs: 45000);
        var data = BuildDataFromRun(run);

        var md = ReportGenerator.RenderMarkdown(data);

        Assert.Contains("100%", md);
        Assert.Contains("45.0s", md);
    }

    [Fact]
    public void RenderMarkdown_SuiteFilterApplied()
    {
        var run = MakeRun("run-abc", "orchestrator", new[] { "qwen3" });
        var data = BuildDataFromRun(run, suiteFilter: "orchestrator");

        var md = ReportGenerator.RenderMarkdown(data);

        Assert.Contains("**Suite:** orchestrator", md);
    }

    [Fact]
    public void RenderMarkdown_FailureShownInScorerSection()
    {
        var run = MakeRun("run-abc", "orchestrator", new[] { "qwen3" },
            score: 0.0, passed: false);
        var data = BuildDataFromRun(run);

        var md = ReportGenerator.RenderMarkdown(data);

        Assert.Contains("✗", md);
        Assert.Contains("FAIL", md);
    }

    // ── RenderJson ──────────────────────────────────────────────────────────

    [Fact]
    public void RenderJson_IsValidJson()
    {
        var run = MakeRun("run-abc", "orchestrator", new[] { "qwen3", "gemma4" });
        var data = BuildDataFromRun(run);

        var json = ReportGenerator.RenderJson(data);

        using var doc = JsonDocument.Parse(json);
        Assert.Equal(JsonValueKind.Object, doc.RootElement.ValueKind);
        Assert.True(doc.RootElement.TryGetProperty("candidates", out _));
        Assert.True(doc.RootElement.TryGetProperty("scenarios", out _));
    }

    [Fact]
    public void RenderJson_ContainsCandidatePassRates()
    {
        var run = MakeRun("run-abc", "orchestrator", new[] { "qwen3" });
        var data = BuildDataFromRun(run);

        var json = ReportGenerator.RenderJson(data);
        using var doc = JsonDocument.Parse(json);

        var candidate = doc.RootElement.GetProperty("candidates")[0];
        Assert.Equal("qwen3", candidate.GetProperty("candidate_id").GetString());
        Assert.Equal(1, candidate.GetProperty("pass_count").GetInt32());
        Assert.Equal(1, candidate.GetProperty("total_scenarios").GetInt32());
    }

    // ── Suite filter ────────────────────────────────────────────────────────

    [Fact]
    public void BuildData_SuiteFilter_ExcludesOtherSuites()
    {
        // Mix orchestrator and vision scenarios in one run
        var orcResult = new PerScenarioResult
        {
            ScenarioId = "orchestrator.scenario-a",
            ScenarioVersion = "1.0.0",
            CandidateResults = new List<CandidateResult>
            {
                new() { CandidateId = "m1", CandidateName = "m1",
                    CandidateKind = CandidateKind.OpenAiModel, Success = true, DurationMs = 100 }
            }
        };
        var visResult = new PerScenarioResult
        {
            ScenarioId = "vision.scenario-b",
            ScenarioVersion = "1.0.0",
            CandidateResults = new List<CandidateResult>
            {
                new() { CandidateId = "m1", CandidateName = "m1",
                    CandidateKind = CandidateKind.OpenAiModel, Success = true, DurationMs = 100 }
            }
        };
        var run = new RunResult
        {
            RunId = "r1", StartedAt = DateTime.UtcNow, CompletedAt = DateTime.UtcNow,
            Scenarios = new() { "orchestrator.scenario-a", "vision.scenario-b" },
            Results = new() { orcResult, visResult }
        };

        var dataFiltered = BuildDataFromRun(run, suiteFilter: "orchestrator");
        var dataAll = BuildDataFromRun(run);

        Assert.Single(dataFiltered.Scenarios);
        Assert.Equal("orchestrator.scenario-a", dataFiltered.Scenarios[0].ScenarioId);
        Assert.Equal(2, dataAll.Scenarios.Count);
    }

    // ── helpers ─────────────────────────────────────────────────────────────

    private static ReportData BuildDataFromRun(RunResult run, string? suiteFilter = null)
    {
        var field = typeof(ReportGenerator).GetMethod(
            "BuildReportData",
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)!;
        return (ReportData)field.Invoke(null, new object?[]
        {
            new List<RunResult> { run },
            new List<string> { "/tmp/run" },
            suiteFilter
        })!;
    }
}
