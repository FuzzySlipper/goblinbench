using System.Text.Json.Serialization;

namespace GoblinBench.Core;

/// <summary>
/// Execution context for a benchmark run — carries the run identity,
/// artifact directory paths, and metadata.
/// </summary>
public sealed class RunContext
{
    /// <summary>Unique run identifier (UUID or timestamp-based).</summary>
    [JsonPropertyName("run_id")]
    public string RunId { get; init; } = string.Empty;

    /// <summary>When the run started (UTC).</summary>
    [JsonPropertyName("started_at")]
    public DateTime StartedAt { get; init; } = DateTime.UtcNow;

    /// <summary>Absolute path to the run's artifact directory (runs/<run-id>/).</summary>
    [JsonPropertyName("run_directory")]
    public string RunDirectory { get; init; } = string.Empty;

    /// <summary>Absolute path to the runs/ root directory.</summary>
    [JsonPropertyName("runs_root")]
    public string RunsRoot { get; init; } = string.Empty;

    /// <summary>User-supplied run label for identification.</summary>
    [JsonPropertyName("label")]
    public string? Label { get; init; }

    /// <summary>Arbitrary metadata for this run.</summary>
    [JsonPropertyName("metadata")]
    public Dictionary<string, object?> Metadata { get; init; } = new();

    /// <summary>Get the per-candidate artifact directory for a candidate.</summary>
    public string GetCandidateDirectory(string candidateId) =>
        Path.Combine(RunDirectory, "candidates", SanitizeFileName(candidateId));

    /// <summary>Get the path to a candidate's output file.</summary>
    public string GetCandidateOutputPath(string candidateId) =>
        Path.Combine(GetCandidateDirectory(candidateId), "output.json");

    /// <summary>Get the path to a candidate's trace file.</summary>
    public string GetCandidateTracePath(string candidateId) =>
        Path.Combine(GetCandidateDirectory(candidateId), "trace.jsonl");

    /// <summary>Get the path to a candidate's scores file.</summary>
    public string GetCandidateScoresPath(string candidateId) =>
        Path.Combine(GetCandidateDirectory(candidateId), "scores.json");

    /// <summary>Get the path to a candidate's artifacts directory.</summary>
    public string GetCandidateArtifactsDirectory(string candidateId) =>
        Path.Combine(GetCandidateDirectory(candidateId), "artifacts");

    private static string SanitizeFileName(string name)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var sanitized = new string(name.Select(c => invalid.Contains(c) ? '_' : c).ToArray());
        return string.IsNullOrWhiteSpace(sanitized) ? "candidate" : sanitized;
    }
}
