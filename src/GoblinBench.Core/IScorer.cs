namespace GoblinBench.Core;

/// <summary>
/// Pluggable evaluation that consumes a candidate result
/// and produces one or more scores.
/// </summary>
public interface IScorer
{
    /// <summary>Unique scorer identifier (e.g. "exact-match", "llm-judge", "latency").</summary>
    string Id { get; }

    /// <summary>Human-readable label for reports.</summary>
    string Name { get; }

    /// <summary>
    /// Score a candidate's result against the scenario's expected behavior.
    /// </summary>
    Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default);
}
