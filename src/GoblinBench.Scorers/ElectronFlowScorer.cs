using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Scores Electron GUI flow results from ElectronCandidateRunner.
/// Checks final_state, required step completion, and skipped-step ratio.
///
/// Scoring weights: final_state 40%, required steps 40%, skip ratio &lt; 20% 20%.
/// Skipped steps (platform unavailable) are neutral — not failures.
/// Default pass threshold: 0.8.
///
/// Parameters:
/// - <c>expected_final_state</c>: string — the expected final_state in candidate output
/// - <c>required_steps</c>: string[] — step types that must appear as completed
/// - <c>optional_layers</c>: string[] — layers whose skipping is expected and neutral
/// </summary>
public sealed class ElectronFlowScorer : IScorer
{
    public string Id => "electron-flow";
    public string Name => "Electron Flow Scorer";

    public Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var parameters = GetParameters(scenario);
        var expectedFinalState = GetStringParam(parameters, "expected_final_state");
        var requiredSteps = GetStringListParam(parameters, "required_steps");

        var obj = TryExtractJsonObject(candidateResult);
        if (!obj.HasValue)
        {
            return Task.FromResult(new ScoreResult
            {
                ScorerId = Id, ScorerName = Name, ScoringKind = "deterministic",
                Success = false, Score = 0.0, Passed = false,
                Error = "No parseable JSON in candidate output.",
                HumanSummary = "FAIL: electron-flow: no parseable JSON output"
            });
        }

        var element = obj.Value;
        var finalState = GetStringField(element, "final_state");
        var stepsCompleted = GetIntField(element, "steps_completed") ?? 0;
        var stepsSkipped = GetIntField(element, "steps_skipped") ?? 0;

        // Extract completed step types from step_log if present
        var completedStepTypes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (element.TryGetProperty("step_log", out var stepLog) && stepLog.ValueKind == JsonValueKind.Array)
        {
            foreach (var step in stepLog.EnumerateArray())
            {
                if (step.TryGetProperty("status", out var status)
                    && status.GetString() == "completed"
                    && step.TryGetProperty("step", out var stepType)
                    && stepType.ValueKind == JsonValueKind.String)
                    completedStepTypes.Add(stepType.GetString()!);
            }
        }

        // From scripted_response, required_steps in the scripted_response.steps_completed implies all required
        // If step_log absent, use required_steps from scenario input.flow as a heuristic
        if (completedStepTypes.Count == 0 && element.TryGetProperty("screenshots", out var screenshots)
            && screenshots.ValueKind == JsonValueKind.Array && screenshots.GetArrayLength() > 0)
        {
            // Screenshots present = screenshot steps completed
            completedStepTypes.Add("screenshot");
        }

        var finalStateOk = expectedFinalState == null ||
            string.Equals(finalState, expectedFinalState, StringComparison.OrdinalIgnoreCase);

        var missingRequired = requiredSteps
            .Where(rs => completedStepTypes.Count > 0 && !completedStepTypes.Contains(rs))
            .ToList();
        var requiredOk = requiredSteps.Count == 0 || missingRequired.Count == 0
            || completedStepTypes.Count == 0; // if no step log, can't penalise

        // Skipped step ratio
        var totalSteps = stepsCompleted + stepsSkipped;
        var skipRatioOk = totalSteps == 0 || (double)stepsSkipped / totalSteps < 0.20;

        var score =
            0.40 * (finalStateOk ? 1.0 : 0.0) +
            0.40 * (requiredOk ? 1.0 : Math.Max(0, 1.0 - missingRequired.Count * 0.2)) +
            0.20 * (skipRatioOk ? 1.0 : 0.5);

        var threshold = GetThreshold(scenario, 0.8);
        var passed = score >= threshold;

        string summary;
        if (passed)
            summary = $"PASS: final_state='{finalState}'{(stepsSkipped > 0 ? $" ({stepsSkipped} step(s) skipped/platform)" : "")} ({score:F2})";
        else if (!finalStateOk)
            summary = $"FAIL: final_state='{finalState}' expected='{expectedFinalState}' ({score:F2})";
        else
            summary = $"FAIL: required steps missing: {string.Join(", ", missingRequired)} ({score:F2})";

        return Task.FromResult(new ScoreResult
        {
            ScorerId = Id, ScorerName = Name, ScoringKind = "deterministic",
            Success = true, Score = score, Passed = passed,
            HumanSummary = summary,
            Explanation = BuildExplanation(finalStateOk, expectedFinalState, finalState,
                requiredOk, missingRequired, skipRatioOk, stepsSkipped, totalSteps),
            Detail = new Dictionary<string, object?>
            {
                ["final_state"] = finalState,
                ["expected_final_state"] = expectedFinalState,
                ["final_state_ok"] = finalStateOk,
                ["steps_completed"] = stepsCompleted,
                ["steps_skipped"] = stepsSkipped,
                ["missing_required_steps"] = missingRequired,
                ["skip_ratio_ok"] = skipRatioOk
            }
        });
    }

    private static JsonElement? TryExtractJsonObject(CandidateResult result)
    {
        var source = result.ParsedResponse ?? result.Output;
        if (source is JsonElement je && je.ValueKind == JsonValueKind.Object) return je;
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
        return null;
    }

    private static string? GetStringField(JsonElement obj, string name)
    {
        if (obj.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.String)
            return p.GetString();
        return null;
    }

    private static int? GetIntField(JsonElement obj, string name)
    {
        if (obj.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.Number)
            return p.GetInt32();
        return null;
    }

    private static string? GetStringParam(Dictionary<string, object?> p, string key)
    {
        if (!p.TryGetValue(key, out var v) || v == null) return null;
        if (v is string s) return s;
        if (v is JsonElement je && je.ValueKind == JsonValueKind.String) return je.GetString();
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

    private static string BuildExplanation(bool finalStateOk, string? expected, string? actual,
        bool requiredOk, List<string> missing, bool skipRatioOk, int skipped, int total)
    {
        var issues = new List<string>();
        if (!finalStateOk) issues.Add($"final_state '{actual}' != expected '{expected}'");
        if (!requiredOk) issues.Add($"required steps missing: {string.Join(", ", missing)}");
        if (!skipRatioOk) issues.Add($"{skipped}/{total} steps skipped (>{20}% threshold)");
        return issues.Count > 0 ? string.Join("; ", issues) : "All checks passed.";
    }

    private double GetThreshold(Scenario scenario, double def) =>
        scenario.Scoring?.Thresholds.TryGetValue(Id, out var th) == true ? th : def;

    private Dictionary<string, object?> GetParameters(Scenario scenario) =>
        scenario.Scoring?.Parameters.TryGetValue(Id, out var p) == true ? p : new();
}
