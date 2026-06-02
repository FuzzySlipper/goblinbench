using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// A no-operation scorer that always returns a perfect score.
/// Useful for smoke-testing the harness.
/// </summary>
public sealed class NoOpScorer : IScorer
{
    public string Id => "noop";
    public string Name => "No-Op Scorer";

    public Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        return Task.FromResult(new ScoreResult
        {
            ScorerId = Id,
            ScorerName = Name,
            Success = true,
            Score = 1.0,
            Passed = true,
            Explanation = "NoOp scorer: always passes.",
            Detail = new Dictionary<string, object?>
            {
                ["scenario"] = scenario.Id,
                ["candidate"] = candidate.Id
            }
        });
    }
}
