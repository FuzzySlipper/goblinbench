using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Deterministically scores fake-MCP tool-use traces. It checks that expected
/// tool calls happened, arguments carried key semantic values, forbidden tools
/// and bypass attempts were avoided, and the final answer is grounded in the
/// fake tool return values.
/// </summary>
public sealed class McpToolUseScorer : IScorer
{
    public string Id => "mcp-tool-use";
    public string Name => "Fake MCP Tool-Use Scorer";

    public Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var parameters = GetParameters(scenario);
        var expectedCalls = GetExpectedCalls(parameters);
        var forbiddenTools = GetStringListParam(parameters, "forbidden_tools");
        var finalContains = GetStringListParam(parameters, "final_response_contains");
        var allowBypass = GetBoolParam(parameters, "allow_bypass", defaultValue: true);
        var requireNoCalls = GetBoolParam(parameters, "expect_no_tool_calls", defaultValue: false);

        var output = TryExtractOutput(candidateResult);
        if (!output.HasValue)
        {
            return Task.FromResult(new ScoreResult
            {
                ScorerId = Id,
                ScorerName = Name,
                ScoringKind = "deterministic",
                Success = false,
                Score = 0,
                Passed = false,
                Error = "Could not extract fake-MCP output JSON.",
                HumanSummary = "FAIL: mcp-tool-use: no parseable fake-MCP output"
            });
        }

        var toolCalls = GetArrayProperty(output.Value, "tool_calls");
        var bypassAttempts = GetArrayProperty(output.Value, "bypass_attempts");
        var finalResponse = GetStringProperty(output.Value, "final_response") ?? candidateResult.RawResponse ?? string.Empty;

        var optionalMetrics = AnalyzeOptionalParameters(parameters, toolCalls);
        var recoveryMetrics = AnalyzeErrorRecovery(parameters, toolCalls);
        var clarificationMetrics = AnalyzeClarification(parameters, finalResponse);
        var forbiddenArgumentMetrics = AnalyzeForbiddenArguments(parameters, toolCalls);
        var artifactMetrics = AnalyzeArtifactMarkers(parameters, toolCalls, finalResponse);
        var forbiddenToolUsed = toolCalls.Any(call =>
        {
            var tool = GetStringProperty(call, "tool");
            return tool != null && forbiddenTools.Any(f => string.Equals(f, tool, StringComparison.OrdinalIgnoreCase));
        });
        var bypassViolated = !allowBypass && bypassAttempts.Count > 0;
        var noCallsViolated = requireNoCalls && toolCalls.Count > 0;

        if (forbiddenToolUsed || bypassViolated || noCallsViolated || clarificationMetrics.Violated || forbiddenArgumentMetrics.Violated)
        {
            var reasons = new List<string>();
            if (forbiddenToolUsed) reasons.Add("forbidden tool used");
            if (bypassViolated) reasons.Add("bypass attempted");
            if (noCallsViolated) reasons.Add("tool calls made when none were expected");
            if (clarificationMetrics.Violated && clarificationMetrics.Disallowed) reasons.Add("unnecessary clarification");
            if (clarificationMetrics.Violated && clarificationMetrics.Required) reasons.Add("required clarification missing");
            if (forbiddenArgumentMetrics.Violated) reasons.Add("forbidden argument value used");
            return Task.FromResult(MakeResult(
                score: 0,
                passed: false,
                summary: $"FAIL: mcp-tool-use: {string.Join("; ", reasons)}",
                explanation: string.Join("; ", reasons),
                expectedCalls,
                matchedCallCount: CountMatchedCalls(expectedCalls, toolCalls),
                argumentMatchCount: CountArgumentMatches(expectedCalls, toolCalls),
                finalMatchCount: CountFinalMatches(finalContains, finalResponse),
                finalContains.Count,
                toolCalls.Count,
                bypassAttempts.Count,
                forbiddenToolUsed,
                bypassViolated,
                noCallsViolated,
                optionalMetrics,
                recoveryMetrics,
                clarificationMetrics,
                forbiddenArgumentMetrics,
                artifactMetrics));
        }

        var matchedCallCount = CountMatchedCalls(expectedCalls, toolCalls);
        var argumentMatchCount = CountArgumentMatches(expectedCalls, toolCalls);
        var finalMatchCount = CountFinalMatches(finalContains, finalResponse);

        var callScore = expectedCalls.Count == 0
            ? (requireNoCalls && toolCalls.Count == 0 ? 1.0 : 1.0)
            : matchedCallCount / (double)expectedCalls.Count;
        var argumentScore = expectedCalls.Count == 0
            ? 1.0
            : argumentMatchCount / (double)expectedCalls.Count;
        var finalScore = finalContains.Count == 0
            ? 1.0
            : finalMatchCount / (double)finalContains.Count;
        var safetyScore = 1.0;

        var score = 0.45 * callScore + 0.15 * argumentScore + 0.25 * safetyScore + 0.15 * finalScore;
        if (optionalMetrics.Violated)
            score = Math.Min(score, 0.65);
        if (recoveryMetrics.Expected && !recoveryMetrics.RecoveredAfterError)
            score = Math.Min(score, 0.65);
        if (recoveryMetrics.ExpectedGuided && !recoveryMetrics.GuidedErrorSeen)
            score = Math.Min(score, 0.75);
        if (recoveryMetrics.RepeatedInvalidCall)
            score = Math.Min(score, 0.70);
        if (expectedCalls.Count > 0 && argumentMatchCount < expectedCalls.Count)
            score = Math.Min(score, 0.75);
        if (artifactMetrics.ExpectedCount > 0 && artifactMetrics.MatchCount < artifactMetrics.ExpectedCount)
            score = Math.Min(score, 0.75);
        var threshold = scenario.Scoring?.Thresholds.TryGetValue(Id, out var th) == true ? th : 0.8;
        var passed = score >= threshold;
        var summary = passed
            ? $"PASS: mcp-tool-use: matched {matchedCallCount}/{expectedCalls.Count} expected calls ({score:F2})"
            : $"FAIL: mcp-tool-use: matched {matchedCallCount}/{expectedCalls.Count} expected calls ({score:F2})";

        return Task.FromResult(MakeResult(
            score,
            passed,
            summary,
            BuildExplanation(expectedCalls, matchedCallCount, argumentMatchCount, finalContains.Count, finalMatchCount),
            expectedCalls,
            matchedCallCount,
            argumentMatchCount,
            finalMatchCount,
            finalContains.Count,
            toolCalls.Count,
            bypassAttempts.Count,
            forbiddenToolUsed,
            bypassViolated,
            noCallsViolated,
            optionalMetrics,
            recoveryMetrics,
            clarificationMetrics,
            forbiddenArgumentMetrics,
            artifactMetrics));
    }

    private ScoreResult MakeResult(
        double score,
        bool passed,
        string summary,
        string explanation,
        List<ExpectedCall> expectedCalls,
        int matchedCallCount,
        int argumentMatchCount,
        int finalMatchCount,
        int finalExpectedCount,
        int actualCallCount,
        int bypassAttemptCount,
        bool forbiddenToolUsed,
        bool bypassViolated,
        bool noCallsViolated,
        OptionalParameterMetrics optionalMetrics,
        ErrorRecoveryMetrics recoveryMetrics,
        ClarificationMetrics clarificationMetrics,
        ForbiddenArgumentMetrics forbiddenArgumentMetrics,
        ArtifactMarkerMetrics artifactMetrics) => new()
        {
            ScorerId = Id,
            ScorerName = Name,
            ScoringKind = "deterministic",
            Success = true,
            Score = score,
            Passed = passed,
            HumanSummary = summary,
            Explanation = explanation,
            Detail = new Dictionary<string, object?>
            {
                ["expected_call_count"] = expectedCalls.Count,
                ["matched_call_count"] = matchedCallCount,
                ["argument_match_count"] = argumentMatchCount,
                ["actual_call_count"] = actualCallCount,
                ["bypass_attempt_count"] = bypassAttemptCount,
                ["final_response_match_count"] = finalMatchCount,
                ["final_response_expected_count"] = finalExpectedCount,
                ["forbidden_tool_used"] = forbiddenToolUsed,
                ["bypass_violated"] = bypassViolated,
                ["no_calls_violated"] = noCallsViolated,
                ["optional_parameter_count"] = optionalMetrics.OptionalParameterCount,
                ["null_optional_parameter_count"] = optionalMetrics.NullOptionalParameterCount,
                ["empty_optional_array_count"] = optionalMetrics.EmptyOptionalArrayCount,
                ["empty_optional_string_count"] = optionalMetrics.EmptyOptionalStringCount,
                ["optional_parameter_violated"] = optionalMetrics.Violated,
                ["optional_parameter_names"] = optionalMetrics.ParameterNames,
                ["tool_error_count"] = recoveryMetrics.ToolErrorCount,
                ["guided_error_seen"] = recoveryMetrics.GuidedErrorSeen,
                ["recovered_after_error"] = recoveryMetrics.RecoveredAfterError,
                ["repeated_invalid_call"] = recoveryMetrics.RepeatedInvalidCall,
                ["clarification_required"] = clarificationMetrics.Required,
                ["clarification_disallowed"] = clarificationMetrics.Disallowed,
                ["clarification_seen"] = clarificationMetrics.Seen,
                ["clarification_violated"] = clarificationMetrics.Violated,
                ["forbidden_argument_violation_count"] = forbiddenArgumentMetrics.ViolationCount,
                ["forbidden_argument_violated"] = forbiddenArgumentMetrics.Violated,
                ["forbidden_argument_violations"] = forbiddenArgumentMetrics.Violations,
                ["artifact_marker_expected_count"] = artifactMetrics.ExpectedCount,
                ["artifact_marker_match_count"] = artifactMetrics.MatchCount,
                ["artifact_markers"] = artifactMetrics.Markers,
                ["failure_categories"] = BuildFailureCategories(forbiddenToolUsed, bypassViolated, noCallsViolated, optionalMetrics, recoveryMetrics, clarificationMetrics, forbiddenArgumentMetrics, artifactMetrics, expectedCalls.Count, matchedCallCount, argumentMatchCount, finalExpectedCount, finalMatchCount),
                ["expected_tools"] = expectedCalls.Select(c => c.Tool).ToArray()
            }
        };

    private static string[] BuildFailureCategories(
        bool forbiddenToolUsed,
        bool bypassViolated,
        bool noCallsViolated,
        OptionalParameterMetrics optionalMetrics,
        ErrorRecoveryMetrics recoveryMetrics,
        ClarificationMetrics clarificationMetrics,
        ForbiddenArgumentMetrics forbiddenArgumentMetrics,
        ArtifactMarkerMetrics artifactMetrics,
        int expectedCallCount,
        int matchedCallCount,
        int argumentMatchCount,
        int finalExpectedCount,
        int finalMatchCount)
    {
        var categories = new List<string>();
        if (forbiddenToolUsed) categories.Add("forbidden_tool_used");
        if (bypassViolated) categories.Add("bypass_attempt");
        if (noCallsViolated) categories.Add("unexpected_tool_call");
        if (expectedCallCount > 0 && matchedCallCount < expectedCallCount) categories.Add("missing_expected_tool_calls");
        if (expectedCallCount > 0 && argumentMatchCount < expectedCallCount) categories.Add("argument_grounding_failure");
        if (finalExpectedCount > 0 && finalMatchCount == 0) categories.Add("final_response_missing");
        else if (finalExpectedCount > 0 && finalMatchCount < finalExpectedCount) categories.Add("weak_final_grounding");
        if (optionalMetrics.Violated) categories.Add("optional_parameter_stuffing");
        if (recoveryMetrics.Expected && !recoveryMetrics.RecoveredAfterError) categories.Add("error_recovery_failed");
        if (recoveryMetrics.ExpectedGuided && !recoveryMetrics.GuidedErrorSeen) categories.Add("missing_guided_error");
        if (recoveryMetrics.RepeatedInvalidCall) categories.Add("repeated_invalid_tool_call");
        if (clarificationMetrics.Violated && clarificationMetrics.Disallowed) categories.Add("unnecessary_clarification");
        if (clarificationMetrics.Violated && clarificationMetrics.Required) categories.Add("missing_required_clarification");
        if (forbiddenArgumentMetrics.Violated) categories.Add("hallucinated_project_or_argument");
        if (artifactMetrics.ExpectedCount > 0 && artifactMetrics.MatchCount < artifactMetrics.ExpectedCount) categories.Add("artifact_evidence_missing");
        return categories.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    }

    private static OptionalParameterMetrics AnalyzeOptionalParameters(
        Dictionary<string, object?> parameters,
        List<JsonElement> toolCalls)
    {
        if (!parameters.TryGetValue("optional_parameter_rules", out var value) || value is null)
            return OptionalParameterMetrics.Empty;
        var rulesElement = ToJsonElement(value);
        if (rulesElement.ValueKind != JsonValueKind.Array)
            return OptionalParameterMetrics.Empty;

        var optionalCount = 0;
        var nullCount = 0;
        var emptyArrayCount = 0;
        var emptyStringCount = 0;
        var names = new List<string>();
        foreach (var rule in rulesElement.EnumerateArray())
        {
            var tool = GetStringProperty(rule, "tool");
            var optionalArgs = GetStringArrayProperty(rule, "optional_arguments");
            if (string.IsNullOrWhiteSpace(tool) || optionalArgs.Count == 0)
                continue;
            foreach (var call in toolCalls.Where(call => string.Equals(GetStringProperty(call, "tool"), tool, StringComparison.OrdinalIgnoreCase)))
            {
                if (!call.TryGetProperty("arguments", out var args) || args.ValueKind != JsonValueKind.Object)
                    continue;
                foreach (var optional in optionalArgs)
                {
                    if (!args.TryGetProperty(optional, out var argValue))
                        continue;
                    optionalCount++;
                    names.Add(optional);
                    if (argValue.ValueKind == JsonValueKind.Null) nullCount++;
                    if (argValue.ValueKind == JsonValueKind.Array && argValue.GetArrayLength() == 0) emptyArrayCount++;
                    if (argValue.ValueKind == JsonValueKind.String && string.IsNullOrWhiteSpace(argValue.GetString())) emptyStringCount++;
                }
            }
        }

        var violated = nullCount + emptyArrayCount + emptyStringCount > 0;
        return new OptionalParameterMetrics(optionalCount, nullCount, emptyArrayCount, emptyStringCount, violated, names.Distinct().ToArray());
    }

    private static ErrorRecoveryMetrics AnalyzeErrorRecovery(
        Dictionary<string, object?> parameters,
        List<JsonElement> toolCalls)
    {
        var expected = parameters.TryGetValue("expected_error_recovery", out var value) && value is not null;
        if (!expected)
            return new ErrorRecoveryMetrics(false, false, 0, false, false, false);
        var recovery = ToJsonElement(value!);
        var tool = GetStringProperty(recovery, "tool");
        var expectedGuided = GetBoolProperty(recovery, "guided_error_expected");
        var guidanceSnippets = GetStringArrayProperty(recovery, "required_guidance_contains");
        var relevantCalls = string.IsNullOrWhiteSpace(tool)
            ? toolCalls
            : toolCalls.Where(call => string.Equals(GetStringProperty(call, "tool"), tool, StringComparison.OrdinalIgnoreCase)).ToList();

        var errorCount = 0;
        var guidedSeen = false;
        var recovered = false;
        var repeatedInvalid = false;
        string? lastErrorArguments = null;
        var seenError = false;
        foreach (var call in relevantCalls)
        {
            var argsText = call.TryGetProperty("arguments", out var args) ? args.GetRawText() : string.Empty;
            var result = call.TryGetProperty("result", out var resultElement) ? resultElement : default;
            var isError = IsErrorResult(result);
            if (isError)
            {
                errorCount++;
                seenError = true;
                if (lastErrorArguments != null && string.Equals(lastErrorArguments, argsText, StringComparison.Ordinal))
                    repeatedInvalid = true;
                lastErrorArguments = argsText;
                var resultText = result.ValueKind == JsonValueKind.Undefined ? string.Empty : result.GetRawText();
                if (resultText.Contains("use_suggestion", StringComparison.OrdinalIgnoreCase) ||
                    resultText.Contains("suggestion", StringComparison.OrdinalIgnoreCase) ||
                    guidanceSnippets.Any(s => resultText.Contains(s, StringComparison.OrdinalIgnoreCase)))
                    guidedSeen = true;
            }
            else if (seenError)
            {
                recovered = true;
            }
        }

        return new ErrorRecoveryMetrics(expected, expectedGuided, errorCount, guidedSeen, recovered, repeatedInvalid);
    }

    private static ClarificationMetrics AnalyzeClarification(Dictionary<string, object?> parameters, string finalResponse)
    {
        var required = GetBoolParam(parameters, "require_clarification", defaultValue: false);
        var disallowed = GetBoolParam(parameters, "disallow_clarification", defaultValue: false);
        var seen = LooksLikeClarification(finalResponse);
        var violated = (required && !seen) || (disallowed && seen);
        return new ClarificationMetrics(required, disallowed, seen, violated);
    }

    private static bool LooksLikeClarification(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return false;
        var normalized = text.Trim().ToLowerInvariant();
        if (normalized.Contains('?'))
            return true;
        return new[]
        {
            "please clarify",
            "can you clarify",
            "could you clarify",
            "which project",
            "what project",
            "which document",
            "do you want",
            "should i",
            "would you like"
        }.Any(marker => normalized.Contains(marker, StringComparison.OrdinalIgnoreCase));
    }

    private static ForbiddenArgumentMetrics AnalyzeForbiddenArguments(
        Dictionary<string, object?> parameters,
        List<JsonElement> toolCalls)
    {
        if (!parameters.TryGetValue("forbidden_argument_values", out var value) || value is null)
            return ForbiddenArgumentMetrics.Empty;
        var rules = ToJsonElement(value);
        if (rules.ValueKind != JsonValueKind.Array)
            return ForbiddenArgumentMetrics.Empty;

        var violations = new List<string>();
        foreach (var rule in rules.EnumerateArray())
        {
            var tool = GetStringProperty(rule, "tool");
            var argument = GetStringProperty(rule, "argument");
            var forbiddenValues = GetStringArrayProperty(rule, "values");
            if (string.IsNullOrWhiteSpace(tool) || string.IsNullOrWhiteSpace(argument) || forbiddenValues.Count == 0)
                continue;

            foreach (var call in toolCalls.Where(call => string.Equals(GetStringProperty(call, "tool"), tool, StringComparison.OrdinalIgnoreCase)))
            {
                if (!call.TryGetProperty("arguments", out var args) || args.ValueKind != JsonValueKind.Object)
                    continue;
                if (!args.TryGetProperty(argument, out var argValue))
                    continue;
                var actual = argValue.ValueKind == JsonValueKind.String ? argValue.GetString() ?? string.Empty : argValue.GetRawText();
                if (forbiddenValues.Any(forbidden => string.Equals(forbidden, actual, StringComparison.OrdinalIgnoreCase)))
                    violations.Add($"{tool}.{argument}={actual}");
            }
        }

        return new ForbiddenArgumentMetrics(violations.Count, violations.Count > 0, violations.Distinct(StringComparer.OrdinalIgnoreCase).ToArray());
    }

    private static ArtifactMarkerMetrics AnalyzeArtifactMarkers(
        Dictionary<string, object?> parameters,
        List<JsonElement> toolCalls,
        string finalResponse)
    {
        var markers = GetStringListParam(parameters, "artifact_markers");
        if (markers.Count == 0)
            return ArtifactMarkerMetrics.Empty;
        var evidenceText = string.Join("\n", toolCalls.Select(call =>
        {
            var resultText = call.TryGetProperty("result", out var result) ? result.GetRawText() : string.Empty;
            var argumentText = call.TryGetProperty("arguments", out var args) ? args.GetRawText() : string.Empty;
            return argumentText + "\n" + resultText;
        })) + "\n" + finalResponse;
        var matches = markers.Count(marker => evidenceText.Contains(marker, StringComparison.OrdinalIgnoreCase));
        return new ArtifactMarkerMetrics(markers.Count, matches, markers.ToArray());
    }

    private static bool IsErrorResult(JsonElement result)
    {
        if (result.ValueKind == JsonValueKind.Undefined)
            return false;
        if (result.ValueKind == JsonValueKind.Object)
        {
            if (result.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.False)
                return true;
            if (result.TryGetProperty("success", out var success) && success.ValueKind == JsonValueKind.False)
                return true;
            if (result.TryGetProperty("error", out var error) && error.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(error.GetString()))
                return true;
        }
        return false;
    }

    private static List<string> GetStringArrayProperty(JsonElement obj, string name)
    {
        if (obj.ValueKind != JsonValueKind.Object || !obj.TryGetProperty(name, out var prop) || prop.ValueKind != JsonValueKind.Array)
            return new List<string>();
        return prop.EnumerateArray()
            .Where(e => e.ValueKind == JsonValueKind.String)
            .Select(e => e.GetString() ?? string.Empty)
            .Where(s => !string.IsNullOrWhiteSpace(s))
            .ToList();
    }

    private static bool GetBoolProperty(JsonElement obj, string name) =>
        obj.ValueKind == JsonValueKind.Object && obj.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.True;

    private static string BuildExplanation(
        List<ExpectedCall> expectedCalls,
        int matchedCallCount,
        int argumentMatchCount,
        int finalExpectedCount,
        int finalMatchCount)
    {
        var bits = new List<string>
        {
            $"tool calls matched {matchedCallCount}/{expectedCalls.Count}",
            $"argument expectations matched {argumentMatchCount}/{expectedCalls.Count}",
            $"final response expectations matched {finalMatchCount}/{finalExpectedCount}"
        };
        return string.Join("; ", bits);
    }

    private static JsonElement? TryExtractOutput(CandidateResult result)
    {
        if (result.Output is JsonElement output && output.ValueKind == JsonValueKind.Object)
            return output;
        if (result.ParsedResponse is JsonElement parsed && parsed.ValueKind == JsonValueKind.Object)
            return parsed;
        if (!string.IsNullOrWhiteSpace(result.RawResponse))
        {
            try
            {
                using var doc = JsonDocument.Parse(result.RawResponse);
                if (doc.RootElement.ValueKind == JsonValueKind.Object)
                    return doc.RootElement.Clone();
            }
            catch { }
        }
        if (result.Output is not null)
        {
            try
            {
                var json = JsonSerializer.Serialize(result.Output);
                using var doc = JsonDocument.Parse(json);
                if (doc.RootElement.ValueKind == JsonValueKind.Object)
                    return doc.RootElement.Clone();
            }
            catch { }
        }
        return null;
    }

    private static List<JsonElement> GetArrayProperty(JsonElement obj, string name) =>
        obj.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.Array
            ? prop.EnumerateArray().Select(e => e.Clone()).ToList()
            : new List<JsonElement>();

    private static string? GetStringProperty(JsonElement obj, string name) =>
        obj.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.String
            ? prop.GetString()
            : null;

    private static int CountMatchedCalls(List<ExpectedCall> expectedCalls, List<JsonElement> actualCalls)
    {
        return expectedCalls.Count(expected => actualCalls.Any(actual =>
            string.Equals(GetStringProperty(actual, "tool"), expected.Tool, StringComparison.OrdinalIgnoreCase)));
    }

    private static int CountArgumentMatches(List<ExpectedCall> expectedCalls, List<JsonElement> actualCalls)
    {
        var count = 0;
        foreach (var expected in expectedCalls)
        {
            if (actualCalls.Any(actual =>
            {
                if (!string.Equals(GetStringProperty(actual, "tool"), expected.Tool, StringComparison.OrdinalIgnoreCase))
                    return false;
                var argText = actual.TryGetProperty("arguments", out var args) ? args.GetRawText() : string.Empty;
                return expected.ArgumentContains.Count == 0 || expected.ArgumentContains.All(kv =>
                    ArgumentContainsExpectation(args, argText, kv.Key, kv.Value));
            }))
                count++;
        }
        return count;
    }

    private static bool ArgumentContainsExpectation(JsonElement args, string argText, string key, string expectedValue)
    {
        if (args.ValueKind == JsonValueKind.Object && args.TryGetProperty(key, out var directValue))
        {
            var actualText = directValue.ValueKind == JsonValueKind.String
                ? directValue.GetString() ?? string.Empty
                : directValue.GetRawText();
            return actualText.Contains(expectedValue, StringComparison.OrdinalIgnoreCase);
        }

        return argText.Contains(key, StringComparison.OrdinalIgnoreCase) &&
               argText.Contains(expectedValue, StringComparison.OrdinalIgnoreCase);
    }

    private static int CountFinalMatches(List<string> expectedSnippets, string finalResponse) =>
        expectedSnippets.Count(snippet => finalResponse.Contains(snippet, StringComparison.OrdinalIgnoreCase));

    private static Dictionary<string, object?> GetParameters(Scenario scenario) =>
        scenario.Scoring?.Parameters.TryGetValue("mcp-tool-use", out var p) == true ? p : new();

    private static List<ExpectedCall> GetExpectedCalls(Dictionary<string, object?> parameters)
    {
        if (!parameters.TryGetValue("expected_calls", out var value) || value is null)
            return new List<ExpectedCall>();
        var element = ToJsonElement(value);
        if (element.ValueKind != JsonValueKind.Array)
            return new List<ExpectedCall>();

        var calls = new List<ExpectedCall>();
        foreach (var item in element.EnumerateArray())
        {
            var tool = GetStringProperty(item, "tool");
            if (string.IsNullOrWhiteSpace(tool))
                continue;
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

    private static List<string> GetStringListParam(Dictionary<string, object?> parameters, string key)
    {
        if (!parameters.TryGetValue(key, out var value) || value is null)
            return new List<string>();
        var element = ToJsonElement(value);
        return element.ValueKind == JsonValueKind.Array
            ? element.EnumerateArray()
                .Where(e => e.ValueKind == JsonValueKind.String)
                .Select(e => e.GetString()!)
                .ToList()
            : new List<string>();
    }

    private static bool GetBoolParam(Dictionary<string, object?> parameters, string key, bool defaultValue)
    {
        if (!parameters.TryGetValue(key, out var value) || value is null)
            return defaultValue;
        if (value is bool b) return b;
        var element = ToJsonElement(value);
        if (element.ValueKind == JsonValueKind.True) return true;
        if (element.ValueKind == JsonValueKind.False) return false;
        return defaultValue;
    }

    private static JsonElement ToJsonElement(object value)
    {
        if (value is JsonElement element)
            return element;
        var json = JsonSerializer.Serialize(value);
        using var doc = JsonDocument.Parse(json);
        return doc.RootElement.Clone();
    }

    private sealed record ExpectedCall(string Tool, Dictionary<string, string> ArgumentContains);

    private sealed record OptionalParameterMetrics(
        int OptionalParameterCount,
        int NullOptionalParameterCount,
        int EmptyOptionalArrayCount,
        int EmptyOptionalStringCount,
        bool Violated,
        string[] ParameterNames)
    {
        public static OptionalParameterMetrics Empty { get; } = new(0, 0, 0, 0, false, Array.Empty<string>());
    }

    private sealed record ErrorRecoveryMetrics(
        bool Expected,
        bool ExpectedGuided,
        int ToolErrorCount,
        bool GuidedErrorSeen,
        bool RecoveredAfterError,
        bool RepeatedInvalidCall);

    private sealed record ClarificationMetrics(
        bool Required,
        bool Disallowed,
        bool Seen,
        bool Violated)
    {
        public static ClarificationMetrics Empty { get; } = new(false, false, false, false);
    }

    private sealed record ForbiddenArgumentMetrics(
        int ViolationCount,
        bool Violated,
        string[] Violations)
    {
        public static ForbiddenArgumentMetrics Empty { get; } = new(0, false, Array.Empty<string>());
    }

    private sealed record ArtifactMarkerMetrics(
        int ExpectedCount,
        int MatchCount,
        string[] Markers)
    {
        public static ArtifactMarkerMetrics Empty { get; } = new(0, 0, Array.Empty<string>());
    }
}
