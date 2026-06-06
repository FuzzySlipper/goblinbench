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

    [Fact]
    public void RenderMarkdown_CodingTestSummary_ShowsRunnerAndTestCounts()
    {
        var run = new RunResult
        {
            RunId = "run-coding",
            StartedAt = DateTime.UtcNow.AddMinutes(-2),
            CompletedAt = DateTime.UtcNow,
            Scenarios = new() { "coding.retry-policy" },
            Results = new()
            {
                new PerScenarioResult
                {
                    ScenarioId = "coding.retry-policy",
                    ScenarioVersion = "1.0.0",
                    CandidateResults = new()
                    {
                        new CandidateResult
                        {
                            CandidateId = "pi-coding-qwen-local",
                            CandidateName = "Qwen local",
                            CandidateKind = CandidateKind.CodingAgent,
                            Success = false,
                            Error = "agent exited 137",
                            DurationMs = 20000,
                            Scores = new()
                            {
                                new ScoreResult
                                {
                                    ScorerId = "coding-tests",
                                    ScorerName = "Coding Test Scorer",
                                    ScoringKind = "command",
                                    Success = true,
                                    Score = 0.8,
                                    Passed = false,
                                    HumanSummary = "FAIL: visible 2/2, strict 1/2, markers 0 (0.80)",
                                    Detail = new Dictionary<string, object?>
                                    {
                                        ["visible_pass"] = 2,
                                        ["visible_total"] = 2,
                                        ["strict_pass"] = 1,
                                        ["strict_total"] = 2,
                                        ["marker_count"] = 0
                                    }
                                }
                            }
                        }
                    }
                }
            }
        };
        var data = BuildDataFromRun(run, suiteFilter: "coding");

        var md = ReportGenerator.RenderMarkdown(data);

        Assert.Contains("## Coding Test Summary", md);
        Assert.Contains("retry-policy", md);
        Assert.Contains("pi-coding-qwen-local", md);
        Assert.Contains("FAIL", md);
        Assert.Contains("2/2", md);
        Assert.Contains("1/2", md);
        Assert.Contains("0", md);
    }

    [Fact]
    public void RenderJson_CodingTestDetails_PreservesVisibleStrictCounts()
    {
        var run = new RunResult
        {
            RunId = "run-coding-json",
            StartedAt = DateTime.UtcNow,
            CompletedAt = DateTime.UtcNow,
            Scenarios = new() { "coding.retry-policy" },
            Results = new()
            {
                new PerScenarioResult
                {
                    ScenarioId = "coding.retry-policy",
                    ScenarioVersion = "1.0.0",
                    CandidateResults = new()
                    {
                        new CandidateResult
                        {
                            CandidateId = "coding-scripted",
                            CandidateName = "Scripted",
                            CandidateKind = CandidateKind.CodingAgent,
                            Success = true,
                            DurationMs = 100,
                            Scores = new()
                            {
                                new ScoreResult
                                {
                                    ScorerId = "coding-tests",
                                    ScorerName = "Coding Test Scorer",
                                    Success = true,
                                    Score = 1.0,
                                    Passed = true,
                                    Detail = new Dictionary<string, object?>
                                    {
                                        ["visible_pass"] = 2,
                                        ["visible_total"] = 2,
                                        ["strict_pass"] = 2,
                                        ["strict_total"] = 2,
                                        ["marker_count"] = 0
                                    }
                                }
                            }
                        }
                    }
                }
            }
        };
        var data = BuildDataFromRun(run, suiteFilter: "coding");

        var json = ReportGenerator.RenderJson(data);
        using var doc = JsonDocument.Parse(json);

        var detail = doc.RootElement
            .GetProperty("scenarios")[0]
            .GetProperty("candidate_scores")
            .GetProperty("coding-scripted")
            .GetProperty("scorer_details")[0]
            .GetProperty("detail");
        Assert.Equal(2, detail.GetProperty("visible_pass").GetInt32());
        Assert.Equal(2, detail.GetProperty("strict_pass").GetInt32());
        Assert.Equal(0, detail.GetProperty("marker_count").GetInt32());
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

    [Fact]
    public void RenderMarkdown_McpToolUseSummary_ShowsTraceArtifactCounts()
    {
        var run = new RunResult
        {
            RunId = "run-mcp",
            StartedAt = DateTime.UtcNow,
            CompletedAt = DateTime.UtcNow,
            Scenarios = new() { "mcp-tools.customer-case-summary" },
            Results = new()
            {
                new PerScenarioResult
                {
                    ScenarioId = "mcp-tools.customer-case-summary",
                    ScenarioVersion = "1.0.0",
                    CandidateResults = new()
                    {
                        new CandidateResult
                        {
                            CandidateId = "fake-mcp-scripted",
                            CandidateName = "Fake MCP",
                            CandidateKind = CandidateKind.Unknown,
                            Success = true,
                            DurationMs = 12,
                            ArtifactDirectory = "/tmp/run/scenarios/mcp-tools.customer-case-summary/candidates/fake-mcp-scripted/artifacts",
                            Scores = new()
                            {
                                new ScoreResult
                                {
                                    ScorerId = "mcp-tool-use",
                                    ScorerName = "MCP Tool Use",
                                    Success = true,
                                    Score = 1.0,
                                    Passed = true,
                                    HumanSummary = "PASS: mcp-tool-use: matched 2/2 expected calls (1.00)",
                                    Detail = new Dictionary<string, object?>
                                    {
                                        ["matched_call_count"] = 2,
                                        ["expected_call_count"] = 2,
                                        ["actual_call_count"] = 2,
                                        ["bypass_attempt_count"] = 0
                                    }
                                }
                            }
                        }
                    }
                }
            }
        };
        var data = BuildDataFromRun(run, suiteFilter: "mcp-tools");

        var md = ReportGenerator.RenderMarkdown(data);

        Assert.Contains("## MCP Tool-Use Summary", md);
        Assert.Contains("customer-case-summary", md);
        Assert.Contains("2/2", md);
        Assert.Contains("tool_calls.json", md);
    }

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
