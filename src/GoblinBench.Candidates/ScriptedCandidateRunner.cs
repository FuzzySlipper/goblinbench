using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// Returns a canned JSON response read from the scenario's <c>input.scripted_response</c> field.
/// Enables deterministic smoke-testing of the full harness pipeline without a real model or service.
/// </summary>
public sealed class ScriptedCandidateRunner : ICandidateRunner
{
    public string Name => "scripted";

    public bool CanHandle(CandidateConfig candidate) =>
        string.Equals(candidate.CliCommand, "scripted", StringComparison.OrdinalIgnoreCase);

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;
        await Task.Delay(1, ct);

        // Extract scripted_response from scenario input
        var rawResponse = string.Empty;
        JsonElement? parsed = null;

        if (scenario.Input.TryGetValue("scripted_response", out var responseObj) && responseObj != null)
        {
            if (responseObj is JsonElement je)
            {
                rawResponse = je.GetRawText();
                parsed = je.ValueKind == JsonValueKind.Object ? je : null;
            }
            else if (responseObj is string s)
            {
                rawResponse = s;
                try
                {
                    var el = JsonSerializer.Deserialize<JsonElement>(s);
                    if (el.ValueKind == JsonValueKind.Object)
                        parsed = el;
                }
                catch { }
            }
            else
            {
                rawResponse = JsonSerializer.Serialize(responseObj);
                try
                {
                    var el = JsonSerializer.Deserialize<JsonElement>(rawResponse);
                    if (el.ValueKind == JsonValueKind.Object)
                        parsed = el;
                }
                catch { }
            }
        }

        var outputPath = context.GetCandidateOutputPath(candidate.Id);
        if (!string.IsNullOrEmpty(outputPath))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
            await File.WriteAllTextAsync(outputPath, rawResponse, ct);
        }

        var tracePath = context.GetCandidateTracePath(candidate.Id);
        if (!string.IsNullOrEmpty(tracePath))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(tracePath)!);
            var traceLine = JsonSerializer.Serialize(new TraceEvent
            {
                Timestamp = DateTime.UtcNow,
                Event = "scripted.response_returned",
                Data = new { scenario = scenario.Id, candidate = candidate.Id }
            });
            await File.AppendAllTextAsync(tracePath, traceLine + Environment.NewLine, ct);
        }

        var durationMs = (long)(DateTime.UtcNow - startedAt).TotalMilliseconds;

        return new CandidateResult
        {
            CandidateId = candidate.Id,
            CandidateName = candidate.Name,
            CandidateKind = candidate.Kind,
            ModelIdentity = new ModelIdentity
            {
                Model = "scripted",
                Provider = "goblinbench",
                DisplayName = "Scripted Deterministic Runner"
            },
            Success = true,
            DurationMs = durationMs,
            RawResponse = rawResponse,
            ParsedResponse = parsed.HasValue ? (object)parsed.Value : null,
            Output = parsed.HasValue ? (object)parsed.Value : null,
            Trace = new List<TraceEvent>
            {
                new() { Timestamp = startedAt, Event = "scripted.started" },
                new() { Timestamp = DateTime.UtcNow, Event = "scripted.completed" }
            },
            ArtifactDirectory = context.GetCandidateArtifactsDirectory(candidate.Id)
        };
    }
}
