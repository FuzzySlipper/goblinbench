using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// Deterministic runner for fuzzy autonomy/groundedness scenarios. It replays the
/// scenario-owned scripted decision packet so scorer/report plumbing can be
/// verified before spending model time.
/// </summary>
public sealed class FakeFuzzyCandidateRunner : ICandidateRunner
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true
    };

    public string Name => "fuzzy-scripted";

    public bool CanHandle(CandidateConfig candidate) =>
        string.Equals(candidate.CliCommand, "fuzzy-scripted", StringComparison.OrdinalIgnoreCase);

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;
        var artifactDir = context.GetCandidateArtifactsDirectory(candidate.Id);
        Directory.CreateDirectory(artifactDir);

        var packet = GetObjectInput(scenario, "scripted_decision_packet")
            ?? JsonSerializer.SerializeToElement(new Dictionary<string, object?>
            {
                ["decision_label"] = "answer_with_unknowns",
                ["question"] = null,
                ["actions_taken"] = Array.Empty<string>(),
                ["claims"] = Array.Empty<object>(),
                ["unknowns"] = new[] { "scripted decision packet missing" },
                ["final_response"] = "No scripted decision packet was provided."
            });
        var toolCalls = GetArrayInput(scenario, "scripted_tool_calls");
        var finalResponse = GetStringProperty(packet, "final_response") ?? packet.GetRawText();

        var output = new Dictionary<string, object?>
        {
            ["decision_packet"] = packet,
            ["tool_calls"] = toolCalls,
            ["final_response"] = finalResponse
        };
        var rawResponse = JsonSerializer.Serialize(output, JsonOptions);
        var parsed = JsonSerializer.Deserialize<JsonElement>(rawResponse);

        await File.WriteAllTextAsync(Path.Combine(artifactDir, "decision_packet.json"), packet.GetRawText(), ct);
        await File.WriteAllTextAsync(Path.Combine(artifactDir, "tool_calls.json"), JsonSerializer.Serialize(toolCalls, JsonOptions), ct);
        await File.WriteAllTextAsync(Path.Combine(artifactDir, "final_response.txt"), finalResponse, ct);

        var outputPath = context.GetCandidateOutputPath(candidate.Id);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        await File.WriteAllTextAsync(outputPath, rawResponse, ct);

        var trace = new List<TraceEvent>
        {
            new() { Timestamp = startedAt, Event = "fuzzy_scripted.started", Data = new { scenario = scenario.Id } },
            new() { Timestamp = DateTime.UtcNow, Event = "fuzzy_scripted.completed", Data = new { artifact_dir = artifactDir } }
        };

        return new CandidateResult
        {
            CandidateId = candidate.Id,
            CandidateName = candidate.Name,
            CandidateKind = candidate.Kind,
            ModelIdentity = new ModelIdentity
            {
                Model = "fuzzy-scripted",
                Provider = "goblinbench",
                DisplayName = "Fuzzy Scripted Runner"
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

    internal static JsonElement? GetObjectInput(Scenario scenario, string key)
    {
        if (!scenario.Input.TryGetValue(key, out var value) || value is null)
            return null;
        var element = ToJsonElement(value);
        return element.ValueKind == JsonValueKind.Object ? element.Clone() : null;
    }

    internal static List<JsonElement> GetArrayInput(Scenario scenario, string key)
    {
        if (!scenario.Input.TryGetValue(key, out var value) || value is null)
            return new List<JsonElement>();
        var element = ToJsonElement(value);
        return element.ValueKind == JsonValueKind.Array
            ? element.EnumerateArray().Select(e => e.Clone()).ToList()
            : new List<JsonElement>();
    }

    internal static JsonElement ToJsonElement(object value)
    {
        if (value is JsonElement element)
            return element.Clone();
        return JsonSerializer.SerializeToElement(value, JsonOptions);
    }

    private static string? GetStringProperty(JsonElement obj, string name) =>
        obj.ValueKind == JsonValueKind.Object &&
        obj.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.String
            ? prop.GetString()
            : null;
}
