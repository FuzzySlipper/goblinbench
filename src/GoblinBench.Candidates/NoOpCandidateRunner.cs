using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// A no-operation candidate runner that echoes the scenario input
/// and always succeeds. Useful for smoke-testing the harness.
/// </summary>
public sealed class NoOpCandidateRunner : ICandidateRunner
{
    public string Name => "noop";

    public bool CanHandle(CandidateConfig candidate) =>
        candidate.Kind == CandidateKind.Unknown ||
        string.Equals(candidate.CliCommand, "noop", StringComparison.OrdinalIgnoreCase);

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;

        // Simulate some work
        await Task.Delay(10, ct);

        var output = new Dictionary<string, object?>
        {
            ["echo"] = scenario.Input,
            ["status"] = "noop_ok",
            ["message"] = $"NoOp runner processed scenario '{scenario.Id}' for candidate '{candidate.Id}'"
        };

        // Write output artifact
        var outputPath = context.GetCandidateOutputPath(candidate.Id);
        var artifactDir = context.GetCandidateArtifactsDirectory(candidate.Id);

        if (!string.IsNullOrEmpty(outputPath))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
            await File.WriteAllTextAsync(outputPath,
                JsonSerializer.Serialize(output, new JsonSerializerOptions { WriteIndented = true }),
                ct);
        }

        // Write trace
        var tracePath = context.GetCandidateTracePath(candidate.Id);
        if (!string.IsNullOrEmpty(tracePath))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(tracePath)!);
            var traceLine = JsonSerializer.Serialize(new TraceEvent
            {
                Timestamp = DateTime.UtcNow,
                Event = "noop.executed",
                Data = new { scenario = scenario.Id, candidate = candidate.Id }
            });
            await File.WriteAllTextAsync(tracePath, traceLine + Environment.NewLine, ct);
        }

        var durationMs = (long)(DateTime.UtcNow - startedAt).TotalMilliseconds;

        return new CandidateResult
        {
            CandidateId = candidate.Id,
            CandidateName = candidate.Name,
            CandidateKind = candidate.Kind,
            ModelIdentity = new ModelIdentity
            {
                Model = "noop",
                Provider = "goblinbench",
                DisplayName = "No-Op Runner"
            },
            Success = true,
            DurationMs = durationMs,
            RawResponse = JsonSerializer.Serialize(output, new JsonSerializerOptions { WriteIndented = true }),
            Output = output,
            Trace = new List<TraceEvent>
            {
                new() { Timestamp = startedAt, Event = "noop.started" },
                new() { Timestamp = DateTime.UtcNow, Event = "noop.completed" }
            },
            ArtifactDirectory = artifactDir
        };
    }
}
