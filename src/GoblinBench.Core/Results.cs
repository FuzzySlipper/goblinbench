using System.Text.Json.Serialization;

namespace GoblinBench.Core;

/// <summary>
/// Overall result of a benchmark run: which scenarios ran against which
/// candidates with what outcomes.
/// </summary>
public sealed record RunResult
{
    /// <summary>Run identifier matching the RunContext.</summary>
    [JsonPropertyName("run_id")]
    public string RunId { get; init; } = string.Empty;

    /// <summary>When the run started.</summary>
    [JsonPropertyName("started_at")]
    public DateTime StartedAt { get; init; }

    /// <summary>When the run completed.</summary>
    [JsonPropertyName("completed_at")]
    public DateTime CompletedAt { get; init; }

    /// <summary>User-supplied label.</summary>
    [JsonPropertyName("label")]
    public string? Label { get; init; }

    /// <summary>Summarised scenario IDs that were executed.</summary>
    [JsonPropertyName("scenarios")]
    public List<string> Scenarios { get; init; } = new();

    /// <summary>Per-scenario, per-candidate results.</summary>
    [JsonPropertyName("results")]
    public List<PerScenarioResult> Results { get; init; } = new();

    /// <summary>Arbitrary run metadata.</summary>
    [JsonPropertyName("metadata")]
    public Dictionary<string, object?> Metadata { get; init; } = new();
}

/// <summary>
/// Results for one scenario executed against one or more candidates.
/// </summary>
public sealed class PerScenarioResult
{
    [JsonPropertyName("scenario_id")]
    public string ScenarioId { get; init; } = string.Empty;

    [JsonPropertyName("scenario_version")]
    public string ScenarioVersion { get; init; } = string.Empty;

    [JsonPropertyName("candidate_results")]
    public List<CandidateResult> CandidateResults { get; init; } = new();
}

/// <summary>
/// A single candidate's output, traces, and scores for one scenario.
/// Distinguishes model identity from prompt/profile/runtime identity.
/// </summary>
public sealed class CandidateResult
{
    /// <summary>Candidate identifier from CandidateConfig.</summary>
    [JsonPropertyName("candidate_id")]
    public string CandidateId { get; init; } = string.Empty;

    /// <summary>Candidate display name.</summary>
    [JsonPropertyName("candidate_name")]
    public string CandidateName { get; init; } = string.Empty;

    /// <summary>Candidate kind.</summary>
    [JsonPropertyName("candidate_kind")]
    public CandidateKind CandidateKind { get; init; }

    /// <summary>
    /// Identity of the model/service that produced this result
    /// (model name, provider, base URL). Distinct from prompt/profile identity.
    /// </summary>
    [JsonPropertyName("model_identity")]
    public ModelIdentity? ModelIdentity { get; init; }

    /// <summary>Whether execution succeeded (did not throw/timeout).</summary>
    [JsonPropertyName("success")]
    public bool Success { get; init; }

    /// <summary>Error message if execution failed.</summary>
    [JsonPropertyName("error")]
    public string? Error { get; init; }

    /// <summary>Wall-clock duration of the candidate execution.</summary>
    [JsonPropertyName("duration_ms")]
    public long DurationMs { get; init; }

    /// <summary>
    /// Raw text response from the candidate, before any parsing.
    /// Secrets are redacted before writing to artifacts.
    /// </summary>
    [JsonPropertyName("raw_response")]
    public string? RawResponse { get; init; }

    /// <summary>
    /// Structured/parsed output extracted from the raw response.
    /// May be null for candidates that produce unstructured output.
    /// </summary>
    [JsonPropertyName("parsed_response")]
    public object? ParsedResponse { get; init; }

    /// <summary>Aggregated output produced by the candidate (serialisable shape).</summary>
    [JsonPropertyName("output")]
    public object? Output { get; init; }

    /// <summary>Trace events captured during execution.</summary>
    [JsonPropertyName("trace")]
    public List<TraceEvent> Trace { get; init; } = new();

    /// <summary>Scores produced by each scorer.</summary>
    [JsonPropertyName("scores")]
    public List<ScoreResult> Scores { get; init; } = new();

    /// <summary>Absolute path to this candidate's artifact directory.</summary>
    [JsonPropertyName("artifact_directory")]
    public string? ArtifactDirectory { get; init; }
}

/// <summary>
/// Describes the model, provider, and endpoint that produced a result.
/// Separated from prompt/profile/runtime identity for clean comparison.
/// </summary>
public sealed class ModelIdentity
{
    /// <summary>Model name (e.g. "gpt-4o", "claude-sonnet-4").</summary>
    [JsonPropertyName("model")]
    public string? Model { get; init; }

    /// <summary>Provider name (e.g. "openai", "anthropic").</summary>
    [JsonPropertyName("provider")]
    public string? Provider { get; init; }

    /// <summary>API base URL used for the request.</summary>
    [JsonPropertyName("base_url")]
    public string? BaseUrl { get; init; }

    /// <summary>Human-readable label for reports.</summary>
    [JsonPropertyName("display_name")]
    public string? DisplayName { get; init; }
}

/// <summary>
/// A single trace event captured during candidate execution.
/// </summary>
public sealed class TraceEvent
{
    [JsonPropertyName("timestamp")]
    public DateTime Timestamp { get; init; }

    [JsonPropertyName("event")]
    public string Event { get; init; } = string.Empty;

    [JsonPropertyName("data")]
    public object? Data { get; init; }
}

/// <summary>
/// Score produced by a scorer for a candidate's result.
/// </summary>
public sealed class ScoreResult
{
    /// <summary>Scorer identifier (matches IScorer.Id).</summary>
    [JsonPropertyName("scorer_id")]
    public string ScorerId { get; init; } = string.Empty;

    /// <summary>Scorer display name.</summary>
    [JsonPropertyName("scorer_name")]
    public string ScorerName { get; init; } = string.Empty;

    /// <summary>Whether the scorer completed successfully.</summary>
    [JsonPropertyName("success")]
    public bool Success { get; init; }

    /// <summary>Error message if scoring failed.</summary>
    [JsonPropertyName("error")]
    public string? Error { get; init; }

    /// <summary>The primary score value (higher is better unless inverted).</summary>
    [JsonPropertyName("score")]
    public double? Score { get; init; }

    /// <summary>Whether the score passed a configured threshold.</summary>
    [JsonPropertyName("passed")]
    public bool? Passed { get; init; }

    /// <summary>Human-readable explanation of the score.</summary>
    [JsonPropertyName("explanation")]
    public string? Explanation { get; init; }

    /// <summary>Arbitrary scorer-specific detail.</summary>
    [JsonPropertyName("detail")]
    public Dictionary<string, object?> Detail { get; init; } = new();
}
