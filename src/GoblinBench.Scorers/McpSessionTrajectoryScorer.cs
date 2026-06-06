using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Scores durable multi-turn fake-MCP sessions. Each turn has independent tool
/// expectations, while aggregate detail exposes trajectory-level repeated
/// mistakes such as forbidden tool use across turns.
/// </summary>
public sealed class McpSessionTrajectoryScorer : IScorer
{
    public string Id => "mcp-session-trajectory";
    public string Name => "Fake MCP Session Trajectory Scorer";

    public Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var expectedTurns = GetExpectedTurns(GetParameters(scenario));
        var output = TryExtractOutput(candidateResult);
        if (!output.HasValue || !output.Value.TryGetProperty("turns", out var actualTurnsElement) || actualTurnsElement.ValueKind != JsonValueKind.Array)
        {
            return Task.FromResult(new ScoreResult
            {
                ScorerId = Id,
                ScorerName = Name,
                ScoringKind = "deterministic",
                Success = false,
                Score = 0,
                Passed = false,
                Error = "Could not extract MCP session turns output.",
                HumanSummary = "FAIL: mcp-session: no parseable turns output"
            });
        }

        var actualTurns = actualTurnsElement.EnumerateArray().Select(e => e.Clone()).ToList();
        var turnCount = Math.Max(expectedTurns.Count, actualTurns.Count);
        var turnDetails = new List<Dictionary<string, object?>>();
        var scoreSum = 0.0;
        var passedTurnCount = 0;
        var forbiddenUseCount = 0;
        var noCallsViolationCount = 0;

        for (var i = 0; i < turnCount; i++)
        {
            var expected = i < expectedTurns.Count ? expectedTurns[i] : ExpectedTurn.Empty;
            var actual = i < actualTurns.Count ? actualTurns[i] : default;
            var toolCalls = actual.ValueKind == JsonValueKind.Object ? GetArrayProperty(actual, "tool_calls") : [];
            var bypassAttempts = actual.ValueKind == JsonValueKind.Object ? GetArrayProperty(actual, "bypass_attempts") : [];
            var finalResponse = actual.ValueKind == JsonValueKind.Object ? GetStringProperty(actual, "final_response") ?? string.Empty : string.Empty;

            var matchedCallCount = CountMatchedCalls(expected.ExpectedCalls, toolCalls);
            var argumentMatchCount = CountArgumentMatches(expected.ExpectedCalls, toolCalls);
            var finalMatchCount = CountFinalMatches(expected.FinalResponseContains, finalResponse);
            var forbiddenToolUsed = toolCalls.Any(call =>
            {
                var tool = GetStringProperty(call, "tool");
                return tool != null && expected.ForbiddenTools.Any(f => string.Equals(f, tool, StringComparison.OrdinalIgnoreCase));
            });
            var bypassViolated = !expected.AllowBypass && bypassAttempts.Count > 0;
            var noCallsViolated = expected.ExpectNoToolCalls && toolCalls.Count > 0;

            if (forbiddenToolUsed) forbiddenUseCount++;
            if (noCallsViolated) noCallsViolationCount++;

            var turnScore = 0.0;
            if (!forbiddenToolUsed && !bypassViolated && !noCallsViolated)
            {
                var callScore = expected.ExpectedCalls.Count == 0 ? 1.0 : matchedCallCount / (double)expected.ExpectedCalls.Count;
                var argumentScore = expected.ExpectedCalls.Count == 0 ? 1.0 : argumentMatchCount / (double)expected.ExpectedCalls.Count;
                var finalScore = expected.FinalResponseContains.Count == 0 ? 1.0 : finalMatchCount / (double)expected.FinalResponseContains.Count;
                turnScore = 0.45 * callScore + 0.15 * argumentScore + 0.25 + 0.15 * finalScore;
            }
            var turnPassed = turnScore >= expected.Threshold;
            if (turnPassed) passedTurnCount++;
            scoreSum += turnScore;

            turnDetails.Add(new Dictionary<string, object?>
            {
                ["turn_index"] = i + 1,
                ["score"] = turnScore,
                ["passed"] = turnPassed,
                ["expected_call_count"] = expected.ExpectedCalls.Count,
                ["matched_call_count"] = matchedCallCount,
                ["argument_match_count"] = argumentMatchCount,
                ["actual_call_count"] = toolCalls.Count,
                ["final_response_match_count"] = finalMatchCount,
                ["final_response_expected_count"] = expected.FinalResponseContains.Count,
                ["forbidden_tool_used"] = forbiddenToolUsed,
                ["bypass_violated"] = bypassViolated,
                ["no_calls_violated"] = noCallsViolated
            });
        }

        var score = turnCount == 0 ? 0 : scoreSum / turnCount;
        var threshold = scenario.Scoring?.Thresholds.TryGetValue(Id, out var th) == true ? th : 0.8;
        var passed = score >= threshold && forbiddenUseCount == 0 && noCallsViolationCount == 0;
        var failureBits = new List<string>();
        if (forbiddenUseCount > 0) failureBits.Add($"forbidden tool use on {forbiddenUseCount} turn(s)");
        if (noCallsViolationCount > 0) failureBits.Add($"unexpected tool calls on {noCallsViolationCount} turn(s)");
        if (passedTurnCount < turnCount) failureBits.Add($"{passedTurnCount}/{turnCount} turns passed");
        var summary = passed
            ? $"PASS: mcp-session: {passedTurnCount}/{turnCount} turns passed ({score:F2})"
            : $"FAIL: mcp-session: {string.Join("; ", failureBits)} ({score:F2})";

        return Task.FromResult(new ScoreResult
        {
            ScorerId = Id,
            ScorerName = Name,
            ScoringKind = "deterministic",
            Success = true,
            Score = score,
            Passed = passed,
            HumanSummary = summary,
            Explanation = $"session turns passed {passedTurnCount}/{turnCount}; forbidden tool use count {forbiddenUseCount}",
            Detail = new Dictionary<string, object?>
            {
                ["turn_count"] = turnCount,
                ["passed_turn_count"] = passedTurnCount,
                ["forbidden_tool_use_count"] = forbiddenUseCount,
                ["no_calls_violation_count"] = noCallsViolationCount,
                ["turns"] = turnDetails
            }
        });
    }

    private static Dictionary<string, object?> GetParameters(Scenario scenario) =>
        scenario.Scoring?.Parameters.TryGetValue("mcp-session-trajectory", out var p) == true ? p : new();

    private static List<ExpectedTurn> GetExpectedTurns(Dictionary<string, object?> parameters)
    {
        if (!parameters.TryGetValue("turns", out var value) || value is null)
            return [];
        var element = ToJsonElement(value);
        if (element.ValueKind != JsonValueKind.Array)
            return [];
        var turns = new List<ExpectedTurn>();
        foreach (var turn in element.EnumerateArray())
        {
            var expectedCalls = GetExpectedCalls(turn, "expected_calls");
            var forbiddenTools = GetStringListProperty(turn, "forbidden_tools");
            var finalContains = GetStringListProperty(turn, "final_response_contains");
            var allowBypass = GetBoolProperty(turn, "allow_bypass", defaultValue: false);
            var expectNoCalls = GetBoolProperty(turn, "expect_no_tool_calls", defaultValue: false);
            var threshold = GetDoubleProperty(turn, "threshold", 0.8);
            turns.Add(new ExpectedTurn(expectedCalls, forbiddenTools, finalContains, allowBypass, expectNoCalls, threshold));
        }
        return turns;
    }

    private static List<ExpectedCall> GetExpectedCalls(JsonElement obj, string property)
    {
        if (!obj.TryGetProperty(property, out var element) || element.ValueKind != JsonValueKind.Array)
            return [];
        var calls = new List<ExpectedCall>();
        foreach (var item in element.EnumerateArray())
        {
            var tool = GetStringProperty(item, "tool");
            if (string.IsNullOrWhiteSpace(tool)) continue;
            var contains = new Dictionary<string, string>();
            if (item.TryGetProperty("argument_contains", out var argContains) && argContains.ValueKind == JsonValueKind.Object)
            {
                foreach (var prop in argContains.EnumerateObject())
                    contains[prop.Name] = prop.Value.ValueKind == JsonValueKind.String
                        ? prop.Value.GetString() ?? string.Empty
                        : prop.Value.GetRawText();
            }
            calls.Add(new ExpectedCall(tool, contains));
        }
        return calls;
    }

    private static int CountMatchedCalls(List<ExpectedCall> expectedCalls, List<JsonElement> actualCalls) =>
        expectedCalls.Count(expected => actualCalls.Any(actual =>
            string.Equals(GetStringProperty(actual, "tool"), expected.Tool, StringComparison.OrdinalIgnoreCase)));

    private static int CountArgumentMatches(List<ExpectedCall> expectedCalls, List<JsonElement> actualCalls)
    {
        var count = 0;
        foreach (var expected in expectedCalls)
        {
            var actual = actualCalls.FirstOrDefault(call =>
                string.Equals(GetStringProperty(call, "tool"), expected.Tool, StringComparison.OrdinalIgnoreCase));
            if (actual.ValueKind == JsonValueKind.Undefined)
                continue;
            var argText = actual.TryGetProperty("arguments", out var args) ? args.GetRawText() : string.Empty;
            if (expected.ArgumentContains.Count == 0 || expected.ArgumentContains.All(kv =>
                    argText.Contains(kv.Key, StringComparison.OrdinalIgnoreCase) &&
                    argText.Contains(kv.Value, StringComparison.OrdinalIgnoreCase)))
                count++;
        }
        return count;
    }

    private static int CountFinalMatches(List<string> expectedSnippets, string finalResponse) =>
        expectedSnippets.Count(snippet => finalResponse.Contains(snippet, StringComparison.OrdinalIgnoreCase));

    private static JsonElement? TryExtractOutput(CandidateResult result)
    {
        if (result.Output is JsonElement output && output.ValueKind == JsonValueKind.Object) return output;
        if (result.ParsedResponse is JsonElement parsed && parsed.ValueKind == JsonValueKind.Object) return parsed;
        if (!string.IsNullOrWhiteSpace(result.RawResponse))
        {
            try
            {
                using var doc = JsonDocument.Parse(result.RawResponse);
                if (doc.RootElement.ValueKind == JsonValueKind.Object) return doc.RootElement.Clone();
            }
            catch { }
        }
        return null;
    }

    private static List<JsonElement> GetArrayProperty(JsonElement obj, string name) =>
        obj.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.Array
            ? prop.EnumerateArray().Select(e => e.Clone()).ToList()
            : [];

    private static string? GetStringProperty(JsonElement obj, string name) =>
        obj.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.String ? prop.GetString() : null;

    private static List<string> GetStringListProperty(JsonElement obj, string name) =>
        obj.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.Array
            ? prop.EnumerateArray().Where(e => e.ValueKind == JsonValueKind.String).Select(e => e.GetString()!).ToList()
            : [];

    private static bool GetBoolProperty(JsonElement obj, string name, bool defaultValue) =>
        obj.TryGetProperty(name, out var prop)
            ? prop.ValueKind switch { JsonValueKind.True => true, JsonValueKind.False => false, _ => defaultValue }
            : defaultValue;

    private static double GetDoubleProperty(JsonElement obj, string name, double defaultValue) =>
        obj.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.Number && prop.TryGetDouble(out var value)
            ? value
            : defaultValue;

    private static JsonElement ToJsonElement(object value)
    {
        if (value is JsonElement element) return element.Clone();
        var json = JsonSerializer.Serialize(value);
        using var doc = JsonDocument.Parse(json);
        return doc.RootElement.Clone();
    }

    private sealed record ExpectedCall(string Tool, Dictionary<string, string> ArgumentContains);

    private sealed record ExpectedTurn(
        List<ExpectedCall> ExpectedCalls,
        List<string> ForbiddenTools,
        List<string> FinalResponseContains,
        bool AllowBypass,
        bool ExpectNoToolCalls,
        double Threshold)
    {
        public static ExpectedTurn Empty { get; } = new([], [], [], false, false, 0.8);
    }
}
