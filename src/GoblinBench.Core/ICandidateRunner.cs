namespace GoblinBench.Core;

/// <summary>
/// Prepares fixtures, invokes the candidate, collects output/traces/artifacts,
/// and hands the result to scorers.
/// </summary>
public interface ICandidateRunner
{
    /// <summary>Human-readable runner name for logging and reports.</summary>
    string Name { get; }

    /// <summary>
    /// Returns true if this runner can handle the given candidate configuration.
    /// </summary>
    bool CanHandle(CandidateConfig candidate);

    /// <summary>
    /// Execute the candidate against a scenario within a run context.
    /// Returns the candidate's raw output and artifacts.
    /// </summary>
    Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default);
}
