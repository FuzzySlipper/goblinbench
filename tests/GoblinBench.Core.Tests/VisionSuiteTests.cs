using System.Text.Json;
using GoblinBench.Candidates;
using GoblinBench.Core;
using GoblinBench.Scorers;

namespace GoblinBench.Core.Tests;

public class VisionSuiteTests
{
    // ── helpers ────────────────────────────────────────────────────────────────

    private static Scenario MakeScenario(
        string? expectedAnswerContains = null,
        string[]? expectedElements = null,
        string[]? forbiddenElements = null,
        string? maxHallucinationRisk = null,
        Dictionary<string, object?>? input = null)
    {
        var scorerParams = new Dictionary<string, object?>();
        if (expectedAnswerContains != null)
            scorerParams["expected_answer_contains"] = expectedAnswerContains;
        if (expectedElements != null)
            scorerParams["expected_elements"] = JsonSerializer.SerializeToElement(expectedElements);
        if (forbiddenElements != null)
            scorerParams["forbidden_elements"] = JsonSerializer.SerializeToElement(forbiddenElements);
        if (maxHallucinationRisk != null)
            scorerParams["max_hallucination_risk"] = maxHallucinationRisk;

        return new Scenario
        {
            Id = "test-vision", Version = "1.0.0",
            Suite = "vision", Name = "Test Vision",
            Input = input ?? new(),
            Scoring = new ScoringConfig
            {
                Scorers = new() { "vision-correctness" },
                Parameters = new() { ["vision-correctness"] = scorerParams },
                Thresholds = new() { ["vision-correctness"] = 0.8 }
            },
            TimeoutSeconds = 60
        };
    }

    private static CandidateResult MakeResultWithParsed(string json)
    {
        var el = JsonSerializer.Deserialize<JsonElement>(json);
        return new CandidateResult
        {
            CandidateId = "c1", CandidateName = "Test",
            CandidateKind = CandidateKind.Unknown, Success = true,
            DurationMs = 200, ParsedResponse = el, RawResponse = json
        };
    }

    private static CandidateResult MakeRawResult(string raw) => new()
    {
        CandidateId = "c1", CandidateName = "Test",
        CandidateKind = CandidateKind.Unknown, Success = true,
        DurationMs = 200, RawResponse = raw
    };

    private static RunContext TestContext => new() { RunId = "r1", RunDirectory = "/tmp/test" };

    private static string ValidVisionOutput(
        string answer = "Yes, an error banner is visible.",
        string risk = "low",
        string[]? elements = null,
        double confidence = 0.92,
        double actionability = 0.5) =>
        JsonSerializer.Serialize(new
        {
            elements_found = elements ?? new[] { "error_banner" },
            answer,
            confidence,
            hallucination_risk = risk,
            suggested_action = (string?)null,
            actionability
        });

    // ── VisionCorrectnessScorer ────────────────────────────────────────────────

    [Fact]
    public async Task VisionCorrectness_ValidOutput_Passes()
    {
        var scorer = new VisionCorrectnessScorer();
        var scenario = MakeScenario(
            expectedAnswerContains: "error",
            expectedElements: new[] { "error_banner" });
        var result = MakeResultWithParsed(ValidVisionOutput());

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.Equal(1.0, score.Score!.Value, precision: 5);
        Assert.True(score.Passed);
        Assert.Contains("PASS", score.HumanSummary);
        Assert.Equal("deterministic", score.ScoringKind);
    }

    [Fact]
    public async Task VisionCorrectness_AnswerMissingExpectedText_Fails()
    {
        var scorer = new VisionCorrectnessScorer();
        var scenario = MakeScenario(expectedAnswerContains: "error");
        var result = MakeResultWithParsed(ValidVisionOutput(answer: "The screen looks normal."));

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.True(score.Score!.Value < 0.8);
        Assert.False(score.Passed);
        Assert.Contains("FAIL", score.HumanSummary);
    }

    [Fact]
    public async Task VisionCorrectness_HallucinationRiskTooHigh_Fails()
    {
        var scorer = new VisionCorrectnessScorer();
        var scenario = MakeScenario(maxHallucinationRisk: "low");
        var result = MakeResultWithParsed(ValidVisionOutput(risk: "high"));

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.True(score.Score!.Value < 0.8);
        Assert.False(score.Passed);
        Assert.Contains("hallucination", score.HumanSummary);
    }

    [Fact]
    public async Task VisionCorrectness_ForbiddenElementPresent_ScoresZero()
    {
        var scorer = new VisionCorrectnessScorer();
        var scenario = MakeScenario(
            forbiddenElements: new[] { "error_banner", "modal" });
        // Model claims to see an error_banner — but the test image has none
        var result = MakeResultWithParsed(ValidVisionOutput(
            answer: "I can see an error banner at the top.",
            elements: new[] { "error_banner", "plain_background" }));

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.Equal(0.0, score.Score!.Value);
        Assert.False(score.Passed);
        Assert.Contains("hallucination", score.HumanSummary);
        Assert.Contains("error_banner", score.HumanSummary);
    }

    [Fact]
    public async Task VisionCorrectness_ExpectedElementsMissing_ReducesScore()
    {
        var scorer = new VisionCorrectnessScorer();
        var scenario = MakeScenario(
            expectedElements: new[] { "error_banner", "notification_icon" });
        var result = MakeResultWithParsed(ValidVisionOutput(
            elements: new[] { "error_banner" })); // notification_icon missing

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.True(score.Score!.Value < 1.0);
        Assert.Contains("notification_icon", score.Explanation ?? "");
    }

    [Fact]
    public async Task VisionCorrectness_NoOutput_ReturnsFail()
    {
        var scorer = new VisionCorrectnessScorer();
        var scenario = MakeScenario(expectedAnswerContains: "error");
        var result = new CandidateResult
        {
            CandidateId = "c1", CandidateName = "T",
            CandidateKind = CandidateKind.Unknown, Success = true, DurationMs = 10
        };

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.False(score.Success);
        Assert.Equal(0.0, score.Score!.Value);
        Assert.Contains("no parseable JSON", score.HumanSummary);
    }

    [Fact]
    public async Task VisionCorrectness_JsonEmbeddedInProse_Extracts()
    {
        var scorer = new VisionCorrectnessScorer();
        var scenario = MakeScenario(expectedAnswerContains: "error");
        var json = ValidVisionOutput();
        var result = MakeRawResult($"Here is my analysis of the screenshot:\n\n{json}\n\nI hope this is helpful.");

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.Equal(1.0, score.Score!.Value, precision: 5);
        Assert.True(score.Passed);
    }

    [Fact]
    public async Task VisionCorrectness_NoConstraints_ValidStructureScoresFull()
    {
        var scorer = new VisionCorrectnessScorer();
        var scenario = MakeScenario(); // no expected_answer_contains, no elements
        var result = MakeResultWithParsed(ValidVisionOutput());

        var score = await scorer.ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext);

        Assert.True(score.Success);
        Assert.Equal(1.0, score.Score!.Value, precision: 5);
        Assert.True(score.Passed);
    }

    // ── VisionCandidateRunner ──────────────────────────────────────────────────

    [Fact]
    public void VisionRunner_CanHandle_OnlyVisionOpenAiCommand()
    {
        var runner = new VisionCandidateRunner();

        Assert.True(runner.CanHandle(new() { Id = "v", CliCommand = "vision-openai" }));
        Assert.True(runner.CanHandle(new() { Id = "v", CliCommand = "VISION-OPENAI" }));
        Assert.False(runner.CanHandle(new() { Id = "v", Kind = CandidateKind.OpenAiModel }));
        Assert.False(runner.CanHandle(new() { Id = "v", CliCommand = "noop" }));
        Assert.False(runner.CanHandle(new() { Id = "v", CliCommand = "scripted" }));
    }

    // ── End-to-end: scripted runner → vision scorer ────────────────────────────

    [Fact]
    public async Task EndToEnd_ScriptedVisionResponse_PassesVisionScorer()
    {
        var runner = new ScriptedCandidateRunner();
        var scorer = new VisionCorrectnessScorer();

        var scenario = MakeScenario(
            expectedAnswerContains: "error",
            expectedElements: new[] { "error_banner" },
            forbiddenElements: new[] { "modal", "dialog" },
            maxHallucinationRisk: "medium",
            input: new Dictionary<string, object?>
            {
                ["image_paths"] = JsonSerializer.SerializeToElement(new[] { "fixtures/vision/error-banner.png" }),
                ["scripted_response"] = JsonSerializer.SerializeToElement(new
                {
                    elements_found = new[] { "error_banner", "red_banner" },
                    answer = "Yes, there is a visible red error banner at the top of the screen.",
                    confidence = 0.92,
                    hallucination_risk = "low",
                    suggested_action = (string?)null,
                    actionability = 0.3
                })
            });

        var candidate = new CandidateConfig
        {
            Id = "scripted", CliCommand = "scripted", Kind = CandidateKind.Unknown
        };
        var context = new RunContext
        {
            RunId = "r1",
            RunDirectory = Path.Combine(Path.GetTempPath(), "goblinbench-vision-e2e-" + Guid.NewGuid())
        };

        var candidateResult = await runner.RunAsync(scenario, candidate, context);
        var scoreResult = await scorer.ScoreAsync(scenario, candidate, candidateResult, context);

        Assert.True(candidateResult.Success);
        Assert.True(scoreResult.Success);
        Assert.Equal(1.0, scoreResult.Score!.Value, precision: 5);
        Assert.True(scoreResult.Passed);
        Assert.Contains("PASS", scoreResult.HumanSummary);
    }

    [Fact]
    public async Task EndToEnd_HallucinationScenario_HardFailsIfForbiddenElementFound()
    {
        var runner = new ScriptedCandidateRunner();
        var scorer = new VisionCorrectnessScorer();

        // Simulates a bad model that hallucinates an error_banner on a clean screen
        var scenario = MakeScenario(
            expectedAnswerContains: "no",
            forbiddenElements: new[] { "error_banner", "modal", "alert" },
            maxHallucinationRisk: "low",
            input: new Dictionary<string, object?>
            {
                ["image_paths"] = JsonSerializer.SerializeToElement(new[] { "fixtures/vision/absent-element.png" }),
                ["scripted_response"] = JsonSerializer.SerializeToElement(new
                {
                    elements_found = new[] { "error_banner", "plain_background" }, // hallucinated!
                    answer = "I can see a red error banner at the top.",
                    confidence = 0.6,
                    hallucination_risk = "medium",
                    suggested_action = (string?)null,
                    actionability = 0.2
                })
            });

        var candidate = new CandidateConfig { Id = "scripted", CliCommand = "scripted", Kind = CandidateKind.Unknown };
        var context = new RunContext
        {
            RunId = "r1",
            RunDirectory = Path.Combine(Path.GetTempPath(), "goblinbench-vision-hall-" + Guid.NewGuid())
        };

        var candidateResult = await runner.RunAsync(scenario, candidate, context);
        var scoreResult = await scorer.ScoreAsync(scenario, candidate, candidateResult, context);

        Assert.True(candidateResult.Success);
        Assert.True(scoreResult.Success);
        Assert.Equal(0.0, scoreResult.Score!.Value);
        Assert.False(scoreResult.Passed);
        Assert.Contains("hallucination", scoreResult.HumanSummary);
    }
}
