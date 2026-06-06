using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// Deterministic runner for fake-MCP tool-use scenarios. It replays scenario-owned
/// scripted tool calls, records them as artifacts, and returns the same output shape
/// a real MCP-tool candidate runner should produce: tool_calls, bypass_attempts,
/// and final_response.
/// </summary>
public sealed class FakeMcpCandidateRunner : ICandidateRunner
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true
    };

    public string Name => "fake-mcp-scripted";

    public bool CanHandle(CandidateConfig candidate) =>
        string.Equals(candidate.CliCommand, "fake-mcp-scripted", StringComparison.OrdinalIgnoreCase);

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;
        var toolCalls = GetArrayInput(scenario, "scripted_tool_calls");
        var bypassAttempts = GetArrayInput(scenario, "scripted_bypass_attempts");
        var finalResponse = GetStringInput(scenario, "scripted_final_response")
            ?? "I cannot complete this with the available fake MCP tools.";

        var output = new Dictionary<string, object?>
        {
            ["tool_calls"] = toolCalls,
            ["bypass_attempts"] = bypassAttempts,
            ["final_response"] = finalResponse,
            ["fake_mcp"] = scenario.Input.TryGetValue("fake_mcp", out var fakeMcp) ? fakeMcp : null
        };

        var artifactDir = context.GetCandidateArtifactsDirectory(candidate.Id);
        Directory.CreateDirectory(artifactDir);
        await File.WriteAllTextAsync(
            Path.Combine(artifactDir, "tool_calls.json"),
            JsonSerializer.Serialize(toolCalls, JsonOptions),
            ct);
        await File.WriteAllTextAsync(
            Path.Combine(artifactDir, "bypass_attempts.json"),
            JsonSerializer.Serialize(bypassAttempts, JsonOptions),
            ct);
        await File.WriteAllTextAsync(
            Path.Combine(artifactDir, "final_response.txt"),
            finalResponse,
            ct);

        var rawResponse = JsonSerializer.Serialize(output, JsonOptions);
        var outputPath = context.GetCandidateOutputPath(candidate.Id);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        await File.WriteAllTextAsync(outputPath, rawResponse, ct);

        var trace = new List<TraceEvent>
        {
            new() { Timestamp = startedAt, Event = "fake_mcp.started", Data = new { scenario = scenario.Id } }
        };

        foreach (var call in toolCalls)
        {
            trace.Add(new TraceEvent
            {
                Timestamp = DateTime.UtcNow,
                Event = "fake_mcp.tool_called",
                Data = call
            });
        }

        foreach (var bypass in bypassAttempts)
        {
            trace.Add(new TraceEvent
            {
                Timestamp = DateTime.UtcNow,
                Event = "fake_mcp.bypass_attempted",
                Data = bypass
            });
        }

        trace.Add(new TraceEvent
        {
            Timestamp = DateTime.UtcNow,
            Event = "fake_mcp.completed",
            Data = new
            {
                tool_call_count = toolCalls.Count,
                bypass_attempt_count = bypassAttempts.Count,
                artifact_dir = artifactDir
            }
        });

        var parsed = JsonSerializer.Deserialize<JsonElement>(rawResponse);
        return new CandidateResult
        {
            CandidateId = candidate.Id,
            CandidateName = candidate.Name,
            CandidateKind = candidate.Kind,
            ModelIdentity = new ModelIdentity
            {
                Model = "fake-mcp-scripted",
                Provider = "goblinbench",
                DisplayName = "Fake MCP Scripted Runner"
            },
            Success = true,
            DurationMs = Math.Max(1, (long)(DateTime.UtcNow - startedAt).TotalMilliseconds),
            RawResponse = rawResponse,
            ParsedResponse = parsed,
            Output = parsed,
            Trace = trace,
            ArtifactDirectory = artifactDir
        };
    }

    private static List<JsonElement> GetArrayInput(Scenario scenario, string key)
    {
        if (!scenario.Input.TryGetValue(key, out var value) || value is null)
            return new List<JsonElement>();

        if (value is JsonElement element)
        {
            if (element.ValueKind == JsonValueKind.Array)
                return element.EnumerateArray().Select(e => e.Clone()).ToList();
            if (element.ValueKind == JsonValueKind.String)
            {
                try
                {
                    using var doc = JsonDocument.Parse(element.GetString() ?? "[]");
                    return doc.RootElement.ValueKind == JsonValueKind.Array
                        ? doc.RootElement.EnumerateArray().Select(e => e.Clone()).ToList()
                        : new List<JsonElement>();
                }
                catch { return new List<JsonElement>(); }
            }
        }

        var json = JsonSerializer.Serialize(value);
        using var parsed = JsonDocument.Parse(json);
        return parsed.RootElement.ValueKind == JsonValueKind.Array
            ? parsed.RootElement.EnumerateArray().Select(e => e.Clone()).ToList()
            : new List<JsonElement>();
    }

    private static string? GetStringInput(Scenario scenario, string key)
    {
        if (!scenario.Input.TryGetValue(key, out var value) || value is null)
            return null;
        if (value is string s) return s;
        if (value is JsonElement element && element.ValueKind == JsonValueKind.String)
            return element.GetString();
        return value.ToString();
    }
}
