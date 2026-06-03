using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Scores vision analysis output from the Den Vision Analyzer output schema.
/// Validates answer text, elements found, hallucination risk, and field structure.
///
/// Scoring weights: answer 40%, hallucination 30%, elements 20%, structure 10%.
/// Default pass threshold: 0.8.
///
/// Parameters (from scenario scoring config):
/// - <c>expected_answer_contains</c>: string — answer must contain this (case-insensitive)
/// - <c>expected_elements</c>: string[] — all must appear in elements_found
/// - <c>forbidden_elements</c>: string[] — none may appear in elements_found (hallucination guard)
/// - <c>max_hallucination_risk</c>: "low"|"medium"|"high" (default "high" = any risk accepted)
/// - <c>min_confidence</c>: number (default 0.0)
/// </summary>
public sealed class VisionCorrectnessScorer : IScorer
{
    private static readonly Dictionary<string, int> RiskOrder = new(StringComparer.OrdinalIgnoreCase)
    {
        ["low"] = 0, ["medium"] = 1, ["high"] = 2
    };

    public string Id => "vision-correctness";
    public string Name => "Vision Correctness Scorer";

    public Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var parameters = GetParameters(scenario);
        var expectedAnswerContains = GetStringParam(parameters, "expected_answer_contains");
        var expectedElements = GetStringListParam(parameters, "expected_elements");
        var forbiddenElements = GetStringListParam(parameters, "forbidden_elements");
        var maxHallucinationRisk = GetStringParam(parameters, "max_hallucination_risk") ?? "high";
        var minConfidence = GetDoubleParam(parameters, "min_confidence") ?? 0.0;

        var obj = TryExtractJsonObject(candidateResult);
        if (!obj.HasValue)
        {
            return Task.FromResult(new ScoreResult
            {
                ScorerId = Id, ScorerName = Name, ScoringKind = "deterministic",
                Success = false, Score = 0.0, Passed = false,
                Error = "Could not extract a JSON object from candidate output.",
                HumanSummary = "FAIL: vision-correctness: no parseable JSON object in output"
            });
        }

        var element = obj.Value;
        var answer = GetStringField(element, "answer");
        var hallucinationRisk = GetStringField(element, "hallucination_risk");
        var confidence = GetDoubleField(element, "confidence");
        var actionability = GetDoubleField(element, "actionability");
        var elementsFound = GetStringArrayField(element, "elements_found");

        // Hard fail: forbidden element claimed as found (hallucination)
        var hallucinatedElement = forbiddenElements.FirstOrDefault(fe =>
            elementsFound.Any(ef => ef.Contains(fe, StringComparison.OrdinalIgnoreCase)));
        if (hallucinatedElement != null)
        {
            return Task.FromResult(new ScoreResult
            {
                ScorerId = Id, ScorerName = Name, ScoringKind = "deterministic",
                Success = true, Score = 0.0, Passed = false,
                HumanSummary = $"FAIL: vision hallucination — model claimed to see '{hallucinatedElement}' which is absent",
                Explanation = $"Element '{hallucinatedElement}' appears in elements_found but is in the forbidden list.",
                Detail = MakeDetail(answer, hallucinationRisk, confidence, actionability,
                    elementsFound, hallucinatedElement)
            });
        }

        // Evaluate answer
        var answerOk = !string.IsNullOrWhiteSpace(answer) &&
            (expectedAnswerContains == null ||
             answer.Contains(expectedAnswerContains, StringComparison.OrdinalIgnoreCase));

        // Evaluate hallucination risk
        var riskLevel = RiskOrder.GetValueOrDefault(hallucinationRisk ?? "", 2);
        var maxRiskLevel = RiskOrder.GetValueOrDefault(maxHallucinationRisk, 2);
        var hallucinationOk = riskLevel <= maxRiskLevel;

        // Evaluate elements
        var missingExpected = expectedElements
            .Where(ee => !elementsFound.Any(ef => ef.Contains(ee, StringComparison.OrdinalIgnoreCase)))
            .ToList();
        var elementsOk = missingExpected.Count == 0;

        // Structural check
        var structureOk = !string.IsNullOrWhiteSpace(answer)
            && hallucinationRisk != null
            && confidence.HasValue
            && element.TryGetProperty("elements_found", out _);

        var score =
            0.40 * (answerOk ? 1.0 : 0.0) +
            0.30 * (hallucinationOk ? 1.0 : 0.0) +
            0.20 * (elementsOk ? 1.0 : 0.0) +
            0.10 * (structureOk ? 1.0 : 0.0);

        var threshold = GetThreshold(scenario, 0.8);
        var passed = score >= threshold;

        var summary = passed
            ? $"PASS: vision analysis valid ({score:F2}){(expectedAnswerContains != null ? $", answer contains '{expectedAnswerContains}'" : "")}"
            : BuildFailSummary(answerOk, hallucinationOk, elementsOk, structureOk,
                expectedAnswerContains, missingExpected, hallucinationRisk, maxHallucinationRisk, score);

        return Task.FromResult(new ScoreResult
        {
            ScorerId = Id, ScorerName = Name, ScoringKind = "deterministic",
            Success = true, Score = score, Passed = passed,
            HumanSummary = summary,
            Explanation = BuildExplanation(answerOk, hallucinationOk, elementsOk, structureOk,
                expectedAnswerContains, missingExpected, hallucinationRisk, maxHallucinationRisk, confidence, minConfidence),
            Detail = MakeDetail(answer, hallucinationRisk, confidence, actionability,
                elementsFound, null)
        });
    }

    private static JsonElement? TryExtractJsonObject(CandidateResult result)
    {
        var source = result.ParsedResponse ?? result.Output;
        if (source is JsonElement je && je.ValueKind == JsonValueKind.Object)
            return je;

        if (source != null)
        {
            try
            {
                using var doc = JsonDocument.Parse(JsonSerializer.Serialize(source));
                if (doc.RootElement.ValueKind == JsonValueKind.Object)
                    return doc.RootElement.Clone();
            }
            catch { }
        }

        if (!string.IsNullOrEmpty(result.RawResponse))
        {
            try
            {
                var raw = result.RawResponse.Trim();
                var s = raw.IndexOf('{');
                var e = raw.LastIndexOf('}');
                if (s >= 0 && e > s)
                {
                    using var doc = JsonDocument.Parse(raw[s..(e + 1)]);
                    if (doc.RootElement.ValueKind == JsonValueKind.Object)
                        return doc.RootElement.Clone();
                }
            }
            catch { }
        }

        return null;
    }

    private static string? GetStringField(JsonElement obj, string name)
    {
        if (obj.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.String)
            return prop.GetString();
        return null;
    }

    private static double? GetDoubleField(JsonElement obj, string name)
    {
        if (obj.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.Number)
            return prop.GetDouble();
        return null;
    }

    private static List<string> GetStringArrayField(JsonElement obj, string name)
    {
        if (!obj.TryGetProperty(name, out var prop) || prop.ValueKind != JsonValueKind.Array)
            return new();
        return prop.EnumerateArray()
            .Where(e => e.ValueKind == JsonValueKind.String)
            .Select(e => e.GetString()!)
            .ToList();
    }

    private static string? GetStringParam(Dictionary<string, object?> p, string key)
    {
        if (!p.TryGetValue(key, out var v) || v == null) return null;
        if (v is string s) return s;
        if (v is JsonElement je && je.ValueKind == JsonValueKind.String) return je.GetString();
        return v.ToString();
    }

    private static double? GetDoubleParam(Dictionary<string, object?> p, string key)
    {
        if (!p.TryGetValue(key, out var v) || v == null) return null;
        if (v is JsonElement je && je.ValueKind == JsonValueKind.Number) return je.GetDouble();
        if (v is double d) return d;
        return null;
    }

    private static List<string> GetStringListParam(Dictionary<string, object?> p, string key)
    {
        if (!p.TryGetValue(key, out var v) || v == null) return new();
        if (v is JsonElement je && je.ValueKind == JsonValueKind.Array)
            return je.EnumerateArray()
                .Where(e => e.ValueKind == JsonValueKind.String)
                .Select(e => e.GetString()!)
                .ToList();
        return new();
    }

    private static string BuildFailSummary(bool answerOk, bool hallucinationOk, bool elementsOk,
        bool structureOk, string? expectedContains, List<string> missing,
        string? riskLevel, string maxRisk, double score)
    {
        if (!answerOk && expectedContains != null)
            return $"FAIL: answer does not contain '{expectedContains}' ({score:F2})";
        if (!hallucinationOk)
            return $"FAIL: hallucination_risk='{riskLevel}' exceeds max='{maxRisk}' ({score:F2})";
        if (!elementsOk)
            return $"FAIL: expected elements not found: {string.Join(", ", missing)} ({score:F2})";
        return $"FAIL: structural issues in vision output ({score:F2})";
    }

    private static string BuildExplanation(bool answerOk, bool hallucinationOk, bool elementsOk,
        bool structureOk, string? expectedContains, List<string> missing,
        string? riskLevel, string maxRisk, double? confidence, double minConfidence)
    {
        var issues = new List<string>();
        if (!answerOk)
            issues.Add(expectedContains != null
                ? $"answer does not contain '{expectedContains}'"
                : "answer field missing or empty");
        if (!hallucinationOk)
            issues.Add($"hallucination_risk '{riskLevel}' exceeds allowed max '{maxRisk}'");
        if (!elementsOk)
            issues.Add($"expected elements missing from elements_found: {string.Join(", ", missing)}");
        if (!structureOk)
            issues.Add("required output fields missing");
        if (confidence.HasValue && confidence.Value < minConfidence)
            issues.Add($"confidence {confidence:F2} < min {minConfidence:F2}");
        return issues.Count > 0 ? string.Join("; ", issues) : "All checks passed.";
    }

    private static Dictionary<string, object?> MakeDetail(string? answer, string? hallucinationRisk,
        double? confidence, double? actionability, List<string> elementsFound,
        string? hallucinatedElement) =>
        new()
        {
            ["answer_preview"] = answer?.Length > 120 ? answer[..120] + "..." : answer,
            ["hallucination_risk"] = hallucinationRisk,
            ["confidence"] = confidence,
            ["actionability"] = actionability,
            ["elements_found_count"] = elementsFound.Count,
            ["elements_found"] = elementsFound,
            ["hallucinated_element"] = hallucinatedElement
        };

    private double GetThreshold(Scenario scenario, double def) =>
        scenario.Scoring?.Thresholds.TryGetValue(Id, out var th) == true ? th : def;

    private Dictionary<string, object?> GetParameters(Scenario scenario) =>
        scenario.Scoring?.Parameters.TryGetValue(Id, out var p) == true ? p : new();
}
