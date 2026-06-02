using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Scorer that records latency and estimated cost metadata.
/// Always succeeds — this is a measurement scorer, not a pass/fail scorer.
/// </summary>
public sealed class LatencyScorer : IScorer
{
    public string Id => "latency";
    public string Name => "Latency / Cost Metadata Scorer";

    public Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var durationMs = candidateResult.DurationMs;
        var parameters = GetParams(scenario);

        // Calculate cost estimate if pricing config is provided
        double? estimatedCost = null;
        if (parameters.TryGetValue("input_cost_per_1k", out var inputCostObj) &&
            parameters.TryGetValue("output_cost_per_1k", out var outputCostObj) &&
            inputCostObj is JsonElement ice &&
            outputCostObj is JsonElement oce)
        {
            var inputTokens = EstimateTokens(candidateResult.RawResponse ?? string.Empty);
            var outputTokens = EstimateTokens(ExtractPrompt(scenario));
            estimatedCost = (inputTokens / 1000.0 * ice.GetDouble()) +
                            (outputTokens / 1000.0 * oce.GetDouble());
        }

        // Score: lower latency is better. Normalise against a max budget.
        var maxBudgetMs = parameters.TryGetValue("max_budget_ms", out var budget) && budget is JsonElement be
            ? be.GetDouble()
            : 30000.0;

        var latencyScore = Math.Max(0.0, 1.0 - (durationMs / maxBudgetMs));
        var threshold = GetThreshold(scenario, 0.0); // latency scoring always "passes"

        var costStr = estimatedCost.HasValue
            ? $", estimated cost ${estimatedCost.Value:F4}"
            : "";

        var summary = $"INFO: latency: {durationMs}ms{costStr} (score {latencyScore:F2})";

        return Task.FromResult(new ScoreResult
        {
            ScorerId = Id,
            ScorerName = Name,
            ScoringKind = "metadata",
            Success = true,
            Score = latencyScore,
            Passed = true, // latency is always informational
            Explanation = $"Candidate completed in {durationMs}ms." +
                          (estimatedCost.HasValue ? $" Estimated cost: ${estimatedCost.Value:F4}." : ""),
            HumanSummary = summary,
            Detail = new Dictionary<string, object?>
            {
                ["duration_ms"] = durationMs,
                ["latency_score"] = latencyScore,
                ["max_budget_ms"] = maxBudgetMs,
                ["estimated_cost_usd"] = estimatedCost
            }
        });
    }

    private static int EstimateTokens(string text) =>
        string.IsNullOrEmpty(text) ? 0 : (int)Math.Ceiling(text.Length / 4.0);

    private static string ExtractPrompt(Scenario scenario)
    {
        if (scenario.Input.TryGetValue("prompt", out var p) && p is string ps)
            return ps;
        return JsonSerializer.Serialize(scenario.Input);
    }

    private Dictionary<string, object?> GetParams(Scenario scenario) =>
        scenario.Scoring?.Parameters.GetValueOrDefault(Id) ?? new();

    private double GetThreshold(Scenario scenario, double defaultThreshold) =>
        scenario.Scoring?.Thresholds.GetValueOrDefault(Id, defaultThreshold) ?? defaultThreshold;
}
