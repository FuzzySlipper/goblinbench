using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Scorer that checks candidate output against expected values using
/// JSON path expressions or exact field matching.
/// </summary>
public sealed class ExactDecisionScorer : IScorer
{
    public string Id => "exact-decision";
    public string Name => "Exact Decision Scorer";

    public Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var parameters = GetParameters(scenario);
        var expected = parameters.GetValueOrDefault("expected");

        if (expected == null)
        {
            return Task.FromResult(new ScoreResult
            {
                ScorerId = Id,
                ScorerName = Name,
                ScoringKind = "deterministic",
                Success = false,
                Error = "No 'expected' value configured in scorer parameters.",
                HumanSummary = "FAIL: exact-decision: no expected value configured"
            });
        }

        // Try to extract the decision from candidate output
        var fieldName = GetStringParam(parameters, "field") ?? "decision";
        object? actual = ExtractField(candidateResult, fieldName);

        var expectedJson = JsonSerializer.Serialize(expected);
        var actualJson = actual != null ? JsonSerializer.Serialize(actual) : "null";

        // Normalise both for comparison
        var expectedNormalised = Normalise(expected);
        var actualNormalised = actual != null ? Normalise(actual) : null;

        var match = JsonElement.DeepEquals(
            JsonSerializer.SerializeToElement(expectedNormalised),
            actualNormalised != null
                ? JsonSerializer.SerializeToElement(actualNormalised)
                : JsonSerializer.SerializeToElement("null"));

        var threshold = GetThreshold(scenario, 0.5);
        var score = match ? 1.0 : 0.0;
        var passed = score >= threshold;
        var summary = match
            ? $"PASS: decision matched expected '{expectedJson}' (1.0)"
            : $"FAIL: decision '{actualJson}' did not match expected '{expectedJson}' (0.0)";

        return Task.FromResult(new ScoreResult
        {
            ScorerId = Id,
            ScorerName = Name,
            ScoringKind = "deterministic",
            Success = true,
            Score = score,
            Passed = passed,
            Explanation = match
                ? $"Output field matched expected value."
                : $"Output field '{actualJson}' != expected '{expectedJson}'.",
            HumanSummary = summary,
            Detail = new Dictionary<string, object?>
            {
                ["expected"] = expected,
                ["actual"] = actual,
                ["field"] = parameters.GetValueOrDefault("field", "decision"),
                ["match"] = match
            }
        });
    }

    private static object? ExtractField(CandidateResult result, string field)
    {
        // Try parsed_response first, then output, then raw_response
        var source = result.ParsedResponse ?? result.Output;
        if (source == null)
            return result.RawResponse;

        if (source is JsonElement je)
        {
            if (je.ValueKind == JsonValueKind.Object && je.TryGetProperty(field, out var prop))
                return JsonSerializer.Deserialize<object>(prop.GetRawText());
            return JsonSerializer.Deserialize<object>(je.GetRawText());
        }

        // Try dictionary access
        if (source is Dictionary<string, object?> dict && dict.TryGetValue(field, out var val))
            return val;

        // For anonymous types and other objects, serialize to JSON and extract
        try
        {
            var json = JsonSerializer.Serialize(source);
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.TryGetProperty(field, out var el))
                return JsonSerializer.Deserialize<object>(el.GetRawText());
        }
        catch { /* not JSON-serializable, fall through */ }

        return source;
    }

    private static string? GetStringParam(Dictionary<string, object?> parameters, string key)
    {
        if (!parameters.TryGetValue(key, out var val) || val == null)
            return null;
        if (val is string s)
            return s;
        if (val is JsonElement je && je.ValueKind == JsonValueKind.String)
            return je.GetString();
        return val.ToString();
    }

    private static object? Normalise(object? value)
    {
        if (value == null) return null;
        if (value is JsonElement je)
        {
            return je.ValueKind switch
            {
                JsonValueKind.String => je.GetString()?.Trim(),
                JsonValueKind.Number => je.GetDouble(),
                JsonValueKind.True => true,
                JsonValueKind.False => false,
                _ => JsonSerializer.Deserialize<object>(je.GetRawText())
            };
        }
        if (value is string s) return s.Trim();
        return value;
    }

    private double GetThreshold(Scenario scenario, double defaultThreshold)
    {
        var threshold = (scenario.Scoring?.Thresholds.TryGetValue(Id, out var th) == true ? th : defaultThreshold);
        return threshold;
    }

    private Dictionary<string, object?> GetParameters(Scenario scenario) =>
        (scenario.Scoring?.Parameters.TryGetValue(Id, out var p) == true ? p : null) ?? new();
}
