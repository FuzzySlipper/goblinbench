using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Scores orchestrator decision output against expected structured fields.
/// Validates <c>next_action</c>, <c>reason</c>, <c>confidence</c>,
/// <c>forbidden_actions_avoided</c>, and <c>required_evidence</c>.
///
/// Scoring weights: action match 50%, confidence in [0,1] 20%,
/// reason present 15%, arrays present 15%.
/// Default pass threshold: 0.8.
/// </summary>
public sealed class OrchestratorDecisionScorer : IScorer
{
    public string Id => "orchestrator-decision";
    public string Name => "Orchestrator Decision Scorer";

    public Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var parameters = GetParameters(scenario);
        var expectedAction = GetStringParam(parameters, "expected_action");
        var forbiddenActions = GetStringListParam(parameters, "forbidden_actions");

        var obj = TryExtractJsonObject(candidateResult);
        if (!obj.HasValue)
        {
            return Task.FromResult(new ScoreResult
            {
                ScorerId = Id, ScorerName = Name, ScoringKind = "deterministic",
                Success = false, Score = 0.0, Passed = false,
                Error = "Could not extract a JSON object from candidate output.",
                HumanSummary = "FAIL: orchestrator-decision: no parseable JSON object in output",
                Detail = new Dictionary<string, object?> { ["expected_action"] = expectedAction }
            });
        }

        var element = obj.Value;
        var nextAction = GetStringField(element, "next_action");
        var reason = GetStringField(element, "reason");
        var confidence = GetDoubleField(element, "confidence");
        var hasArrayForbidden = element.TryGetProperty("forbidden_actions_avoided", out var faProp)
                                && faProp.ValueKind == JsonValueKind.Array;
        var hasArrayEvidence = element.TryGetProperty("required_evidence", out var reProp)
                               && reProp.ValueKind == JsonValueKind.Array;

        // Hard fail: explicitly forbidden action chosen
        if (nextAction != null && forbiddenActions.Any(f =>
                string.Equals(f, nextAction, StringComparison.OrdinalIgnoreCase)))
        {
            return Task.FromResult(new ScoreResult
            {
                ScorerId = Id, ScorerName = Name, ScoringKind = "deterministic",
                Success = true, Score = 0.0, Passed = false,
                HumanSummary = $"FAIL: orchestrator chose forbidden action '{nextAction}'",
                Explanation = $"Action '{nextAction}' is in the forbidden_actions list for this scenario.",
                Detail = MakeDetail(nextAction, expectedAction, confidence, reason,
                    hasArrayForbidden, hasArrayEvidence, forbiddenViolated: true)
            });
        }

        var actionMatch = expectedAction == null ||
            string.Equals(nextAction, expectedAction, StringComparison.OrdinalIgnoreCase);
        var confidenceOk = confidence is >= 0.0 and <= 1.0;
        var reasonOk = !string.IsNullOrWhiteSpace(reason);
        var structureOk = hasArrayForbidden && hasArrayEvidence;

        var score =
            0.50 * (actionMatch ? 1.0 : 0.0) +
            0.20 * (confidenceOk ? 1.0 : 0.0) +
            0.15 * (reasonOk ? 1.0 : 0.0) +
            0.15 * (structureOk ? 1.0 : 0.0);

        var threshold = GetThreshold(scenario, 0.8);
        var passed = score >= threshold;

        string summary;
        if (passed)
            summary = expectedAction != null
                ? $"PASS: action='{nextAction}' matched '{expectedAction}' ({score:F2})"
                : $"PASS: action='{nextAction}' valid ({score:F2})";
        else
            summary = expectedAction != null && !actionMatch
                ? $"FAIL: action='{nextAction}' expected='{expectedAction}' ({score:F2})"
                : $"FAIL: structural issues in orchestrator output ({score:F2})";

        return Task.FromResult(new ScoreResult
        {
            ScorerId = Id, ScorerName = Name, ScoringKind = "deterministic",
            Success = true, Score = score, Passed = passed,
            HumanSummary = summary,
            Explanation = BuildExplanation(nextAction, expectedAction, actionMatch,
                confidenceOk, reasonOk, structureOk, confidence),
            Detail = MakeDetail(nextAction, expectedAction, confidence, reason,
                hasArrayForbidden, hasArrayEvidence, forbiddenViolated: false)
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
                var json = JsonSerializer.Serialize(source);
                using var doc = JsonDocument.Parse(json);
                if (doc.RootElement.ValueKind == JsonValueKind.Object)
                    return doc.RootElement.Clone();
            }
            catch { }
        }

        // Fall back to extracting a JSON object from raw text (real models often wrap JSON in prose)
        if (!string.IsNullOrEmpty(result.RawResponse))
        {
            try
            {
                var raw = result.RawResponse.Trim();
                var start = raw.IndexOf('{');
                var end = raw.LastIndexOf('}');
                if (start >= 0 && end > start)
                {
                    using var doc = JsonDocument.Parse(raw[start..(end + 1)]);
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

    private static string? GetStringParam(Dictionary<string, object?> parameters, string key)
    {
        if (!parameters.TryGetValue(key, out var val) || val == null) return null;
        if (val is string s) return s;
        if (val is JsonElement je && je.ValueKind == JsonValueKind.String) return je.GetString();
        return val.ToString();
    }

    private static List<string> GetStringListParam(Dictionary<string, object?> parameters, string key)
    {
        if (!parameters.TryGetValue(key, out var val) || val == null) return new();
        if (val is JsonElement je && je.ValueKind == JsonValueKind.Array)
            return je.EnumerateArray()
                .Where(e => e.ValueKind == JsonValueKind.String)
                .Select(e => e.GetString()!)
                .ToList();
        return new();
    }

    private static string BuildExplanation(string? nextAction, string? expectedAction,
        bool actionMatch, bool confidenceOk, bool reasonOk, bool structureOk, double? confidence)
    {
        var issues = new List<string>();
        if (expectedAction != null && !actionMatch)
            issues.Add($"action '{nextAction}' != expected '{expectedAction}'");
        if (!confidenceOk)
            issues.Add(confidence.HasValue
                ? $"confidence {confidence:F2} out of range [0,1]"
                : "confidence field missing or non-numeric");
        if (!reasonOk)
            issues.Add("reason field missing or empty");
        if (!structureOk)
            issues.Add("forbidden_actions_avoided or required_evidence arrays missing");
        return issues.Count > 0 ? string.Join("; ", issues) : "All checks passed.";
    }

    private static Dictionary<string, object?> MakeDetail(string? nextAction, string? expectedAction,
        double? confidence, string? reason, bool hasArrayForbidden, bool hasArrayEvidence,
        bool forbiddenViolated) =>
        new()
        {
            ["next_action"] = nextAction,
            ["expected_action"] = expectedAction,
            ["action_match"] = expectedAction == null ||
                               string.Equals(nextAction, expectedAction, StringComparison.OrdinalIgnoreCase),
            ["confidence"] = confidence,
            ["reason_present"] = !string.IsNullOrWhiteSpace(reason),
            ["forbidden_actions_avoided_present"] = hasArrayForbidden,
            ["required_evidence_present"] = hasArrayEvidence,
            ["forbidden_violated"] = forbiddenViolated
        };

    private double GetThreshold(Scenario scenario, double defaultThreshold) =>
        scenario.Scoring?.Thresholds.TryGetValue(Id, out var th) == true ? th : defaultThreshold;

    private Dictionary<string, object?> GetParameters(Scenario scenario) =>
        scenario.Scoring?.Parameters.TryGetValue(Id, out var p) == true ? p : new();
}
