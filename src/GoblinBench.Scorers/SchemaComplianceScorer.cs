using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Scorer that validates candidate output against a JSON Schema definition.
/// Checks for structural compliance: required fields, correct types,
/// and optional value constraints.
/// </summary>
public sealed class SchemaComplianceScorer : IScorer
{
    public string Id => "schema-compliance";
    public string Name => "Schema Compliance Scorer";

    public Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var parameters = GetParams(scenario);

        if (!parameters.TryGetValue("schema", out var schemaObj) || schemaObj is not JsonElement schemaEl)
        {
            return Task.FromResult(new ScoreResult
            {
                ScorerId = Id,
                ScorerName = Name,
                ScoringKind = "deterministic",
                Success = false,
                Error = "No JSON schema configured for schema-compliance scorer.",
                HumanSummary = "FAIL: schema-compliance: no schema configured"
            });
        }

        // Get required fields from schema
        var requiredFields = new List<string>();
        var fieldTypes = new Dictionary<string, string>();

        if (schemaEl.TryGetProperty("required", out var reqEl) &&
            reqEl.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in reqEl.EnumerateArray())
                requiredFields.Add(item.GetString() ?? string.Empty);
        }

        if (schemaEl.TryGetProperty("properties", out var propsEl) &&
            propsEl.ValueKind == JsonValueKind.Object)
        {
            foreach (var prop in propsEl.EnumerateObject())
            {
                if (prop.Value.TryGetProperty("type", out var typeEl))
                    fieldTypes[prop.Name] = typeEl.GetString() ?? "any";
            }
        }

        var output = candidateResult.ParsedResponse ?? candidateResult.Output;
        if (output == null)
        {
            return Task.FromResult(new ScoreResult
            {
                ScorerId = Id,
                ScorerName = Name,
                ScoringKind = "deterministic",
                Success = true,
                Score = 0.0,
                Passed = false,
                Explanation = "Candidate produced no parseable output.",
                HumanSummary = "FAIL: schema-compliance: no candidate output (0.0)"
            });
        }

        // Normalise output to JsonElement
        JsonElement outputEl;
        if (output is JsonElement je)
            outputEl = je;
        else
        {
            var json = JsonSerializer.Serialize(output);
            outputEl = JsonSerializer.Deserialize<JsonElement>(json);
        }

        var violations = new List<Dictionary<string, object?>>();

        // Check required fields
        foreach (var field in requiredFields)
        {
            if (!outputEl.TryGetProperty(field, out _))
            {
                violations.Add(new Dictionary<string, object?>
                {
                    ["path"] = field,
                    ["message"] = $"Required field '{field}' is missing."
                });
            }
        }

        // Check field types
        foreach (var (field, expectedType) in fieldTypes)
        {
            if (outputEl.TryGetProperty(field, out var value))
            {
                var actualType = GetJsonType(value);
                if (!TypeMatches(actualType, expectedType))
                {
                    violations.Add(new Dictionary<string, object?>
                    {
                        ["path"] = field,
                        ["message"] = $"Field '{field}' expected type '{expectedType}' but got '{actualType}'."
                    });
                }
            }
        }

        var passed = violations.Count == 0;
        var score = passed ? 1.0 : Math.Max(0.0, 1.0 - (violations.Count * 0.2));
        var threshold = GetThreshold(scenario, 0.8);

        var summary = passed
            ? "PASS: schema-compliance: output matches schema (1.0)"
            : $"FAIL: schema-compliance: {violations.Count} violation(s) ({score:F2})";

        return Task.FromResult(new ScoreResult
        {
            ScorerId = Id,
            ScorerName = Name,
            ScoringKind = "deterministic",
            Success = true,
            Score = score,
            Passed = score >= threshold,
            Explanation = passed
                ? "Candidate output conforms to expected schema."
                : $"{violations.Count} schema violation(s) found.",
            HumanSummary = summary,
            Detail = new Dictionary<string, object?>
            {
                ["violation_count"] = violations.Count,
                ["violations"] = violations,
                ["required_fields"] = requiredFields,
                ["field_types"] = fieldTypes
            }
        });
    }

    private static string GetJsonType(JsonElement element) => element.ValueKind switch
    {
        JsonValueKind.String => "string",
        JsonValueKind.Number => "number",
        JsonValueKind.True or JsonValueKind.False => "boolean",
        JsonValueKind.Object => "object",
        JsonValueKind.Array => "array",
        JsonValueKind.Null => "null",
        _ => "unknown"
    };

    private static bool TypeMatches(string actual, string expected) =>
        (actual, expected) switch
        {
            ("number", "integer") => true,
            ("number", "number") => true,
            ("integer", "number") => true,
            _ => string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase)
        };

    private Dictionary<string, object?> GetParams(Scenario scenario) =>
        (scenario.Scoring?.Parameters.TryGetValue(Id, out var sp) == true ? sp : null) ?? new();

    private double GetThreshold(Scenario scenario, double defaultThreshold) =>
        (scenario.Scoring?.Thresholds.TryGetValue(Id, out var th) == true ? th : defaultThreshold);
}
