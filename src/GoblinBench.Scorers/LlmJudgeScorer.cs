using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Placeholder scorer for LLM/rubric judge evaluation.
/// Records judge model identity and prompt version in the score result.
/// Actual LLM invocation will be implemented in a follow-up task
/// (currently delegates to the candidate adapter system).
///
/// The judge model, provider, and prompt version are read from the
/// scenario's ScoringConfig.Judges entry for this scorer.
/// </summary>
public sealed class LlmJudgeScorer : IScorer
{
    public string Id => "llm-judge";
    public string Name => "LLM / Rubric Judge Scorer";

    public Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var judgeConfig = scenario.Scoring?.Judges.TryGetValue(Id, out var jc) == true ? jc : null;
        var parameters = GetParams(scenario);

        // For now, this is a placeholder that records judge identity.
        // Future implementation will invoke the judge model via OpenAiChatRunner
        // or a similar adapter.

        var judgeModel = judgeConfig?.Model ?? parameters.GetValueOrDefault("judge_model")?.ToString();
        var judgePromptVersion = judgeConfig?.PromptVersion ??
                                 parameters.GetValueOrDefault("judge_prompt_version")?.ToString() ?? "v1";

        var hasJudgeConfig = judgeConfig != null ||
                             (parameters.ContainsKey("judge_model") && parameters.ContainsKey("judge_prompt_version"));

        if (!hasJudgeConfig)
        {
            return Task.FromResult(new ScoreResult
            {
                ScorerId = Id,
                ScorerName = Name,
                ScoringKind = "llm_judge",
                Success = false,
                Error = "LLM judge not yet configured (no judge model/prompt_version in scoring config). " +
                        "This is a placeholder — implement LLM invocation in a follow-up task.",
                HumanSummary = "INFO: llm-judge: not configured (placeholder)"
            });
        }

        // Return placeholder score with judge metadata
        return Task.FromResult(new ScoreResult
        {
            ScorerId = Id,
            ScorerName = Name,
            ScoringKind = "llm_judge",
            Success = true,
            Score = null, // not evaluated yet
            Passed = null, // not evaluated yet
            Explanation = "LLM judge evaluation not yet implemented. " +
                          "Judge metadata recorded for future scoring.",
            HumanSummary = $"INFO: llm-judge: placeholder (judge: {judgeModel}, prompt: {judgePromptVersion})",
            JudgeModel = judgeModel,
            JudgePromptVersion = judgePromptVersion,
            Detail = new Dictionary<string, object?>
            {
                ["status"] = "placeholder",
                ["judge_model"] = judgeModel,
                ["judge_prompt_version"] = judgePromptVersion,
                ["judge_provider"] = judgeConfig?.Provider,
                ["judge_temperature"] = judgeConfig?.Temperature
            }
        });
    }

    private Dictionary<string, object?> GetParams(Scenario scenario) =>
        (scenario.Scoring?.Parameters.TryGetValue(Id, out var sp) == true ? sp : null) ?? new();
}
