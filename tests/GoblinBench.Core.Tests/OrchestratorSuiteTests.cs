using System.Text.Json;
using GoblinBench.Candidates;
using GoblinBench.Core;
using GoblinBench.Scorers;

namespace GoblinBench.Core.Tests;

public class OrchestratorSuiteTests
{
    // ── helpers ────────────────────────────────────────────────────────────────

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };

    private static Scenario MakeScenario(
        string? expectedAction = null,
        string[]? forbiddenActions = null,
        Dictionary<string, object?>? input = null)
    {
        var scorerParams = new Dictionary<string, object?>();
        if (expectedAction != null)
            scorerParams["expected_action"] = expectedAction;
        if (forbiddenActions != null)
            scorerParams["forbidden_actions"] = JsonSerializer.SerializeToElement(forbiddenActions);

        return new Scenario
        {
            Id = "test-orchestrator", Version = "1.0.0",
            Suite = "orchestrator", Name = "Test",
            Input = input ?? new(),
            Scoring = new ScoringConfig
            {
                Scorers = new() { "orchestrator-decision" },
                Parameters = new() { ["orchestrator-decision"] = scorerParams },
                Thresholds = new() { ["orchestrator-decision"] = 0.8 }
            },
            TimeoutSeconds = 30
        };
    }

    private static CandidateResult MakeResult(object? output = null, string? rawResponse = null) => new()
    {
        CandidateId = "c1", CandidateName = "Test",
        CandidateKind = CandidateKind.Unknown, Success = true,
        DurationMs = 50, Output = output, RawResponse = rawResponse
    };

    private static CandidateResult MakeResultWithParsed(string json)
    {
        var el = JsonSerializer.Deserialize<JsonElement>(json);
        return new CandidateResult
        {
            CandidateId = "c1", CandidateName = "Test",
            CandidateKind = CandidateKind.Unknown, Success = true,
            DurationMs = 50, ParsedResponse = el, RawResponse = json
        };
    }

    private static RunContext TestContext => new() { RunId = "r1", RunDirectory = "/tmp/test" };

    // ── OrchestratorDecisionScorer ─────────────────────────────────────────────

    [Fact]
    public async Task OrchestratorDecision_CorrectActionAndStructure_Passes()
    {
        var scorer = new OrchestratorDecisionScorer();
        var scenario = MakeScenario(expectedAction: "block_task", forbiddenActions: ["approve_pr"]);
        var result = MakeResultWithParsed("""
            {
              "next_action": "block_task",
              "reason": "Critical bug found in hot path.",
              "confidence": 0.95,
              "forbidden_actions_avoided": ["approve_pr"],
              "required_evidence": ["fix_commit"]
            }
            """);

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.Equal(1.0, score.Score!.Value, precision: 5);
        Assert.True(score.Passed);
        Assert.Contains("PASS", score.HumanSummary);
        Assert.Contains("block_task", score.HumanSummary);
        Assert.Equal("deterministic", score.ScoringKind);
    }

    [Fact]
    public async Task OrchestratorDecision_WrongAction_Fails()
    {
        var scorer = new OrchestratorDecisionScorer();
        var scenario = MakeScenario(expectedAction: "block_task");
        var result = MakeResultWithParsed("""
            {
              "next_action": "approve_pr",
              "reason": "Looks fine to me.",
              "confidence": 0.8,
              "forbidden_actions_avoided": [],
              "required_evidence": []
            }
            """);

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.True(score.Score!.Value < 0.8);
        Assert.False(score.Passed);
        Assert.Contains("FAIL", score.HumanSummary);
        Assert.Contains("approve_pr", score.HumanSummary);
    }

    [Fact]
    public async Task OrchestratorDecision_ForbiddenActionChosen_ScoresZero()
    {
        var scorer = new OrchestratorDecisionScorer();
        var scenario = MakeScenario(
            expectedAction: "block_task",
            forbiddenActions: ["approve_pr"]);
        var result = MakeResultWithParsed("""
            {
              "next_action": "approve_pr",
              "reason": "The reviewer is being too strict.",
              "confidence": 0.6,
              "forbidden_actions_avoided": [],
              "required_evidence": []
            }
            """);

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.Equal(0.0, score.Score!.Value);
        Assert.False(score.Passed);
        Assert.Contains("forbidden", score.HumanSummary);
        Assert.True(score.Detail.TryGetValue("forbidden_violated", out var fv) && (bool)fv!);
    }

    [Fact]
    public async Task OrchestratorDecision_MissingConfidence_ReducesScore()
    {
        var scorer = new OrchestratorDecisionScorer();
        var scenario = MakeScenario(expectedAction: "hold_for_dependency");
        var result = MakeResultWithParsed("""
            {
              "next_action": "hold_for_dependency",
              "reason": "Dependency not resolved yet.",
              "forbidden_actions_avoided": ["bypass_dependency"],
              "required_evidence": ["task_a_completion"]
            }
            """);

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        // action(0.50) + confidence(0.0) + reason(0.15) + structure(0.15) = 0.80 — borderline at threshold 0.8
        Assert.True(score.Score!.Value < 1.0);
        Assert.Contains("confidence", score.Explanation);
    }

    [Fact]
    public async Task OrchestratorDecision_MissingArrays_ReducesScore()
    {
        var scorer = new OrchestratorDecisionScorer();
        var scenario = MakeScenario(expectedAction: "request_rebase");
        var result = MakeResultWithParsed("""
            {
              "next_action": "request_rebase",
              "reason": "Worker is behind HEAD.",
              "confidence": 0.88
            }
            """);

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        // action(0.50) + confidence(0.20) + reason(0.15) + structure(0.0) = 0.85 — passes at 0.8
        // but arrays are missing so structure check = 0
        Assert.True(score.Score!.Value < 1.0);
        Assert.False((bool)score.Detail["required_evidence_present"]!);
    }

    [Fact]
    public async Task OrchestratorDecision_NoOutput_ReturnsFail()
    {
        var scorer = new OrchestratorDecisionScorer();
        var scenario = MakeScenario(expectedAction: "block_task");
        var result = MakeResult(); // no output, no raw response

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.False(score.Success);
        Assert.Equal(0.0, score.Score!.Value);
        Assert.False(score.Passed);
        Assert.Contains("no parseable JSON", score.HumanSummary);
    }

    [Fact]
    public async Task OrchestratorDecision_JsonEmbeddedInProse_Extracts()
    {
        var scorer = new OrchestratorDecisionScorer();
        var scenario = MakeScenario(expectedAction: "escalate_retry_loop");
        // Simulate a model wrapping JSON in prose
        var result = MakeResult(rawResponse: """
            Here is my analysis:

            {
              "next_action": "escalate_retry_loop",
              "reason": "Four identical failures exceed policy.",
              "confidence": 0.96,
              "forbidden_actions_avoided": ["retry_again"],
              "required_evidence": ["root_cause_analysis"]
            }

            I hope this helps.
            """);

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.Equal(1.0, score.Score!.Value, precision: 5);
        Assert.True(score.Passed);
    }

    [Fact]
    public async Task OrchestratorDecision_NoExpectedAction_ScoresOnStructure()
    {
        var scorer = new OrchestratorDecisionScorer();
        var scenario = MakeScenario(); // no expected_action
        var result = MakeResultWithParsed("""
            {
              "next_action": "do_anything",
              "reason": "Some reason.",
              "confidence": 0.7,
              "forbidden_actions_avoided": [],
              "required_evidence": []
            }
            """);

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.Equal(1.0, score.Score!.Value, precision: 5);
        Assert.True(score.Passed);
    }

    // ── ScriptedCandidateRunner ────────────────────────────────────────────────

    [Fact]
    public async Task ScriptedRunner_ReturnsScriptedResponse()
    {
        var runner = new ScriptedCandidateRunner();
        var scenario = new Scenario
        {
            Id = "test", Suite = "orchestrator", Version = "1.0.0", Name = "T",
            Input = new Dictionary<string, object?>
            {
                ["scripted_response"] = JsonSerializer.SerializeToElement(new
                {
                    next_action = "block_task",
                    reason = "Critical bug.",
                    confidence = 0.95,
                    forbidden_actions_avoided = new[] { "approve_pr" },
                    required_evidence = new[] { "fix_commit" }
                })
            }
        };

        var candidate = new CandidateConfig { Id = "scripted", CliCommand = "scripted", Kind = CandidateKind.Unknown };
        var context = new RunContext { RunId = "r1", RunDirectory = Path.Combine(Path.GetTempPath(), "goblinbench-test-" + Guid.NewGuid()) };

        var result = await runner.RunAsync(scenario, candidate, context);

        Assert.True(result.Success);
        Assert.NotNull(result.ParsedResponse);
        Assert.NotEmpty(result.RawResponse!);

        var parsed = Assert.IsType<JsonElement>(result.ParsedResponse);
        Assert.Equal("block_task", parsed.GetProperty("next_action").GetString());
        Assert.Equal(0.95, parsed.GetProperty("confidence").GetDouble(), precision: 5);
    }

    [Fact]
    public async Task ScriptedRunner_CanHandle_OnlyScriptedCommand()
    {
        var runner = new ScriptedCandidateRunner();

        Assert.True(runner.CanHandle(new() { Id = "x", CliCommand = "scripted" }));
        Assert.True(runner.CanHandle(new() { Id = "x", CliCommand = "SCRIPTED" }));
        Assert.False(runner.CanHandle(new() { Id = "x", CliCommand = "noop" }));
        Assert.False(runner.CanHandle(new() { Id = "x", Kind = CandidateKind.Unknown }));
    }

    [Fact]
    public async Task ScriptedRunner_MissingScriptedResponse_ReturnsEmptyButSucceeds()
    {
        var runner = new ScriptedCandidateRunner();
        var scenario = new Scenario
        {
            Id = "test", Suite = "orchestrator", Version = "1.0.0", Name = "T",
            Input = new Dictionary<string, object?>()
        };

        var candidate = new CandidateConfig { Id = "scripted", CliCommand = "scripted", Kind = CandidateKind.Unknown };
        var context = new RunContext { RunId = "r1", RunDirectory = Path.Combine(Path.GetTempPath(), "goblinbench-test-" + Guid.NewGuid()) };

        var result = await runner.RunAsync(scenario, candidate, context);

        Assert.True(result.Success);
        Assert.Equal(string.Empty, result.RawResponse);
        Assert.Null(result.ParsedResponse);
    }

    // ── End-to-end: scripted runner → orchestrator scorer ─────────────────────

    [Fact]
    public async Task EndToEnd_ScriptedResponse_PassesOrchestratorScorer()
    {
        var runner = new ScriptedCandidateRunner();
        var scorer = new OrchestratorDecisionScorer();

        var scenario = MakeScenario(
            expectedAction: "escalate_missing_artifacts",
            forbiddenActions: ["mark_complete", "approve_worker"],
            input: new Dictionary<string, object?>
            {
                ["scripted_response"] = JsonSerializer.SerializeToElement(new
                {
                    next_action = "escalate_missing_artifacts",
                    reason = "No test artifacts found despite worker claiming success.",
                    confidence = 0.95,
                    forbidden_actions_avoided = new[] { "mark_complete", "approve_worker" },
                    required_evidence = new[] { "test_output.json", "artifact_manifest.json" }
                })
            });

        var candidate = new CandidateConfig { Id = "scripted", CliCommand = "scripted", Kind = CandidateKind.Unknown };
        var context = new RunContext
        {
            RunId = "r1",
            RunDirectory = Path.Combine(Path.GetTempPath(), "goblinbench-e2e-" + Guid.NewGuid())
        };

        var candidateResult = await runner.RunAsync(scenario, candidate, context);
        var scoreResult = await scorer.ScoreAsync(scenario, candidate, candidateResult, context);

        Assert.True(candidateResult.Success);
        Assert.True(scoreResult.Success);
        Assert.Equal(1.0, scoreResult.Score!.Value, precision: 5);
        Assert.True(scoreResult.Passed);
        Assert.Contains("PASS", scoreResult.HumanSummary);
    }
}
