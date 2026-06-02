using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Heuristic text scorer that checks candidate output for
/// forbidden markers (TODO, FIXME, HACK, NotImplementedException, etc.)
/// and required mentions/patterns.
/// </summary>
public sealed class HeuristicTextScorer : IScorer
{
    // Default forbidden patterns — markers of unfinished or sloppy work
    private static readonly string[] DefaultForbidden = [
        "TODO", "FIXME", "HACK", "NotImplementedException",
        "NotSupportedException", "throw new Exception", "placeholder",
        "TBD", "stub", "workaround"
    ];

    public string Id => "heuristic-text";
    public string Name => "Heuristic Text Scorer";

    public Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var text = candidateResult.RawResponse ?? string.Empty;
        var parameters = GetParams(scenario);

        // Get custom forbidden patterns
        var forbidden = DefaultForbidden.ToList();
        if (parameters.TryGetValue("forbidden", out var fb) && fb is JsonElement fbArr &&
            fbArr.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in fbArr.EnumerateArray())
                forbidden.Add(item.GetString() ?? string.Empty);
        }

        // Get required patterns
        var required = new List<string>();
        if (parameters.TryGetValue("required", out var rq) && rq is JsonElement rqArr &&
            rqArr.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in rqArr.EnumerateArray())
                required.Add(item.GetString() ?? string.Empty);
        }

        // Check for forbidden markers
        var foundForbidden = new List<string>();
        foreach (var pattern in forbidden)
        {
            if (string.IsNullOrEmpty(pattern)) continue;
            if (text.Contains(pattern, StringComparison.OrdinalIgnoreCase))
                foundForbidden.Add(pattern);
        }

        // Check for required patterns
        var missingRequired = new List<string>();
        foreach (var pattern in required)
        {
            if (string.IsNullOrEmpty(pattern)) continue;
            if (!text.Contains(pattern, StringComparison.OrdinalIgnoreCase))
                missingRequired.Add(pattern);
        }

        var totalChecks = forbidden.Count + required.Count;
        var violations = foundForbidden.Count + missingRequired.Count;
        var score = totalChecks > 0
            ? Math.Max(0.0, 1.0 - ((double)violations / totalChecks))
            : 1.0;

        var threshold = GetThreshold(scenario, 0.8);
        var passed = score >= threshold;

        var parts = new List<string>();
        if (foundForbidden.Count > 0)
            parts.Add($"{foundForbidden.Count} forbidden marker(s) found: [{string.Join(", ", foundForbidden)}]");
        if (missingRequired.Count > 0)
            parts.Add($"{missingRequired.Count} required pattern(s) missing: [{string.Join(", ", missingRequired)}]");
        if (parts.Count == 0)
            parts.Add("no violations");

        var summary = passed
            ? $"PASS: heuristic-text: {string.Join("; ", parts)} ({score:F2})"
            : $"FAIL: heuristic-text: {string.Join("; ", parts)} ({score:F2})";

        return Task.FromResult(new ScoreResult
        {
            ScorerId = Id,
            ScorerName = Name,
            ScoringKind = "heuristic",
            Success = true,
            Score = score,
            Passed = passed,
            Explanation = $"Checked {totalChecks} patterns: {foundForbidden.Count} forbidden found, " +
                          $"{missingRequired.Count} required missing.",
            HumanSummary = summary,
            Detail = new Dictionary<string, object?>
            {
                ["forbidden_found"] = foundForbidden,
                ["required_missing"] = missingRequired,
                ["total_checks"] = totalChecks,
                ["violations"] = violations,
                ["text_length"] = text.Length
            }
        });
    }

    private Dictionary<string, object?> GetParams(Scenario scenario) =>
        scenario.Scoring?.Parameters.GetValueOrDefault(Id) ?? new();

    private double GetThreshold(Scenario scenario, double defaultThreshold) =>
        scenario.Scoring?.Thresholds.GetValueOrDefault(Id, defaultThreshold) ?? defaultThreshold;
}
