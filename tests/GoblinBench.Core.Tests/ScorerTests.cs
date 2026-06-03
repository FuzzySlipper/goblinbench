using System.Text.Json;
using GoblinBench.Core;
using GoblinBench.Scorers;
using System.Text.Json.Serialization;

namespace GoblinBench.Core.Tests;

public class ScorerTests
{
    private static Scenario MakeScenario(string? scoringConfigJson = null,
        Dictionary<string, object?>? input = null)
    {
        var scenario = new Scenario
        {
            Id = "test-scenario", Version = "1.0.0",
            Name = "Test Scenario", Suite = "test",
            Input = input ?? new Dictionary<string, object?>(),
            TimeoutSeconds = 30
        };
        if (scoringConfigJson != null)
        {
            scenario = scenario with
            {
                Scoring = JsonSerializer.Deserialize<ScoringConfig>(scoringConfigJson,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
            };
        }
        return scenario;
    }

    private static CandidateResult MakeResult(object? output = null,
        string? rawResponse = null, long durationMs = 100) => new()
    {
        CandidateId = "test-candidate", CandidateName = "Test",
        CandidateKind = CandidateKind.Unknown, Success = true,
        DurationMs = durationMs, Output = output, RawResponse = rawResponse
    };

    private static void AssertScore(double expected, ScoreResult score)
    {
        Assert.True(score.Score.HasValue, $"Score is null: {score.Error}");
        Assert.Equal(expected, score.Score!.Value);
    }

    // --- ExactDecisionScorer ---

    [Fact]
    public async Task ExactDecision_MatchesExpectedValue()
    {
        var scorer = new ExactDecisionScorer();
        var scenario = MakeScenario("""{"scorers":["exact-decision"],"parameters":{"exact-decision":{"field":"decision","expected":"retry_required"}}}""");
        var result = MakeResult(new { decision = "retry_required" });
        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result,
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        Assert.True(score.Success);
        AssertScore(1.0, score);
        Assert.True(score.Passed!.Value);
        Assert.Contains("PASS", score.HumanSummary);
        Assert.Equal("deterministic", score.ScoringKind);
    }

    [Fact]
    public async Task ExactDecision_MismatchReturnsZero()
    {
        var scorer = new ExactDecisionScorer();
        var scenario = MakeScenario("""{"scorers":["exact-decision"],"parameters":{"exact-decision":{"field":"decision","expected":"retry_required"}}}""");
        var result = MakeResult(new { decision = "continue" });
        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result,
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        Assert.True(score.Success);
        AssertScore(0.0, score);
        Assert.False(score.Passed!.Value);
        Assert.Contains("FAIL", score.HumanSummary);
    }

    // --- HeuristicTextScorer ---

    [Fact]
    public async Task HeuristicText_NoForbidden()
    {
        var scorer = new HeuristicTextScorer();
        var result = MakeResult(rawResponse: "Clean response.");
        var score = await scorer.ScoreAsync(MakeScenario(), new() { Id = "c1" }, result,
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        AssertScore(1.0, score);
        Assert.True(score.Passed!.Value);
        Assert.Contains("no violations", score.HumanSummary);
    }

    [Fact]
    public async Task HeuristicText_FindsForbidden()
    {
        var scorer = new HeuristicTextScorer();
        var result = MakeResult(rawResponse: "// TODO: fix\nthrow new NotImplementedException();");
        var score = await scorer.ScoreAsync(MakeScenario(), new() { Id = "c1" }, result,
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        Assert.True(score.Score!.Value < 1.0);
        Assert.Contains("forbidden marker", score.HumanSummary);
    }

    [Fact]
    public async Task HeuristicText_CustomForbidden()
    {
        var scorer = new HeuristicTextScorer();
        var scenario = MakeScenario("""{"scorers":["heuristic-text"],"parameters":{"heuristic-text":{"forbidden":["BAD"]}}}""");
        var result = MakeResult(rawResponse: "Contains BAD word.");
        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result,
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        Assert.True(score.Score!.Value < 1.0);
    }

    // --- SchemaComplianceScorer ---

    [Fact]
    public async Task SchemaCompliance_Valid()
    {
        var scorer = new SchemaComplianceScorer();
        var scenario = MakeScenario("""{"scorers":["schema-compliance"],"parameters":{"schema-compliance":{"schema":{"required":["id","name"],"properties":{"id":{"type":"string"},"name":{"type":"string"}}}}}}""");
        var result = MakeResult(new { id = "abc", name = "test" });
        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result,
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        AssertScore(1.0, score);
        Assert.True(score.Passed!.Value);
    }

    [Fact]
    public async Task SchemaCompliance_MissingField()
    {
        var scorer = new SchemaComplianceScorer();
        var scenario = MakeScenario("""{"scorers":["schema-compliance"],"parameters":{"schema-compliance":{"schema":{"required":["id","name","extra"],"properties":{}}}}}""");
        var result = MakeResult(new { id = "abc" });
        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result,
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        Assert.True(score.Score!.Value < 1.0);
        Assert.False(score.Passed!.Value);
    }

    // --- LatencyScorer ---

    [Fact]
    public async Task Latency_RecordsMetadata()
    {
        var scorer = new LatencyScorer();
        var result = MakeResult(durationMs: 1500);
        var score = await scorer.ScoreAsync(MakeScenario(), new() { Id = "c1" }, result,
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        Assert.True(score.Success);
        Assert.True(score.Passed!.Value);
        Assert.Equal("metadata", score.ScoringKind);
        Assert.Contains("1500ms", score.HumanSummary);
        Assert.Equal(1500L, (long)(score.Detail["duration_ms"]!));
    }

    // --- CommandScorer ---

    [Fact]
    public async Task CommandScorer_EchoSucceeds()
    {
        var scorer = new CommandScorer();
        var scenario = MakeScenario("""{"scorers":["command"],"parameters":{"command":{"command":"echo hello"}}}""");
        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, MakeResult(),
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        Assert.True(score.Success, score.Error ?? "unknown error");
        Assert.True(score.Passed!.Value, score.HumanSummary ?? "no summary");
        Assert.Equal("command", score.ScoringKind);
    }

    [Fact]
    public async Task CommandScorer_ExpectStdoutContains()
    {
        var scorer = new CommandScorer();
        var scenario = MakeScenario("""{"scorers":["command"],"parameters":{"command":{"command":"echo hello world"}}}""");
        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, MakeResult(),
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        Assert.True(score.Success, score.Error ?? "unknown error");
        // echo always exits 0
        Assert.True(score.Passed!.Value, $"Expected passed, summary: {score.HumanSummary}");
    }

    [Fact]
    public async Task CommandScorer_ExpectStdoutFails()
    {
        var scorer = new CommandScorer();
        var scenario = MakeScenario("""{"scorers":["command"],"parameters":{"command":{"command":"echo hello","expect_stdout_contains":"goodbye"}}}""");
        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, MakeResult(),
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        Assert.True(score.Success, score.Error ?? "unknown error");
        Assert.False(score.Passed!.Value);
    }

    // --- LlmJudgeScorer ---

    [Fact]
    public async Task LlmJudge_NoConfig()
    {
        var scorer = new LlmJudgeScorer();
        var score = await scorer.ScoreAsync(MakeScenario(), new() { Id = "c1" }, MakeResult(),
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        Assert.False(score.Success);
        Assert.Equal("llm_judge", score.ScoringKind);
        Assert.Contains("not configured", score.HumanSummary);
    }

    [Fact]
    public async Task LlmJudge_WithConfig()
    {
        var scorer = new LlmJudgeScorer();
        var scenario = MakeScenario("""{"scorers":["llm-judge"],"judges":{"llm-judge":{"model":"gpt-4o","provider":"openai","prompt_version":"v2"}}}""");
        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, MakeResult(),
            new RunContext { RunId = "r1", RunDirectory = "/tmp" });
        Assert.True(score.Success);
        Assert.Equal("gpt-4o", score.JudgeModel);
        Assert.Equal("v2", score.JudgePromptVersion);
    }

    // --- ScoreResult / ScoringConfig ---

    [Fact]
    public void ScoreResult_NewFields_Serialize()
    {
        var score = new ScoreResult
        {
            ScorerId = "exact-decision", ScorerName = "Exact",
            ScoringKind = "deterministic", Success = true,
            Score = 1.0, Passed = true, HumanSummary = "PASS"
        };
        var json = JsonSerializer.Serialize(score, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
        });
        Assert.Contains("scoring_kind", json);
        Assert.Contains("human_summary", json);
        Assert.DoesNotContain("judge_model", json);
    }

    [Fact]
    public void ScoringConfig_ThresholdsAndJudges()
    {
        var json = """{"scorers":["e","j"],"thresholds":{"e":0.5,"j":0.7},"judges":{"j":{"model":"gpt-4o","provider":"openai","prompt_version":"v1","max_tokens":2048}}}""";
        var config = JsonSerializer.Deserialize<ScoringConfig>(json,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
        Assert.NotNull(config);
        Assert.Equal(0.5, config!.Thresholds["e"]);
        Assert.Equal("gpt-4o", config.Judges["j"].Model);
        Assert.Equal(2048, config.Judges["j"].MaxTokens);
    }
}
