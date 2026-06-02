using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Core.Tests;

public class ResultsTests
{
    [Fact]
    public void RunResult_SerializesRoundTrip()
    {
        var result = new RunResult
        {
            RunId = "run-20260601-001",
            StartedAt = new DateTime(2026, 6, 1, 12, 0, 0, DateTimeKind.Utc),
            CompletedAt = new DateTime(2026, 6, 1, 12, 1, 0, DateTimeKind.Utc),
            Label = "test run",
            Scenarios = new List<string> { "demo-noop" },
            Results = new List<PerScenarioResult>
            {
                new()
                {
                    ScenarioId = "demo-noop",
                    ScenarioVersion = "1.0.0",
                    CandidateResults = new List<CandidateResult>
                    {
                        new()
                        {
                            CandidateId = "noop-demo",
                            CandidateName = "Demo",
                            CandidateKind = CandidateKind.Unknown,
                            Success = true,
                            DurationMs = 15,
                            Output = new { status = "ok" },
                            Scores = new List<ScoreResult>
                            {
                                new()
                                {
                                    ScorerId = "noop",
                                    ScorerName = "No-Op",
                                    Success = true,
                                    Score = 1.0,
                                    Passed = true,
                                    Explanation = "passed"
                                }
                            }
                        }
                    }
                }
            }
        };

        var json = JsonSerializer.Serialize(result,
            new JsonSerializerOptions
            {
                PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
                WriteIndented = true
            });

        Assert.Contains("run-20260601-001", json);
        Assert.Contains("demo-noop", json);
        Assert.Contains("noop-demo", json);

        var deserialized = JsonSerializer.Deserialize<RunResult>(json,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });

        Assert.NotNull(deserialized);
        Assert.Equal("run-20260601-001", deserialized!.RunId);
        Assert.Single(deserialized.Results);
        Assert.Single(deserialized.Results[0].CandidateResults);
    }

    [Fact]
    public void ScoreResult_Defaults_AreSane()
    {
        var score = new ScoreResult();

        Assert.Empty(score.ScorerId);
        Assert.Empty(score.ScorerName);
        Assert.False(score.Success);
        Assert.Null(score.Score);
        Assert.Null(score.Passed);
        Assert.Empty(score.Detail);
    }

    [Fact]
    public void TraceEvent_SerializesCorrectly()
    {
        var evt = new TraceEvent
        {
            Timestamp = new DateTime(2026, 6, 1, 12, 0, 0, DateTimeKind.Utc),
            Event = "candidate.started",
            Data = new { candidate = "gpt4o" }
        };

        var json = JsonSerializer.Serialize(evt,
            new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });

        Assert.Contains("candidate.started", json);
        Assert.Contains("gpt4o", json);
    }
}
