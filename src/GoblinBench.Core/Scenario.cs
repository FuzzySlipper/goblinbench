using System.Text.Json.Serialization;

namespace GoblinBench.Core;

/// <summary>
/// A versioned evaluation case with inputs, fixture setup,
/// expected behavior, and scoring configuration.
/// </summary>
public sealed record Scenario
{
    /// <summary>Unique identifier for this scenario (e.g. "vision-ui.login-error-banner").</summary>
    [JsonPropertyName("id")]
    public string Id { get; init; } = string.Empty;

    /// <summary>Semantic version of the scenario definition.</summary>
    [JsonPropertyName("version")]
    public string Version { get; init; } = "1.0.0";

    /// <summary>Human-readable display name.</summary>
    [JsonPropertyName("name")]
    public string Name { get; init; } = string.Empty;

    /// <summary>Longer description of what this scenario evaluates.</summary>
    [JsonPropertyName("description")]
    public string Description { get; init; } = string.Empty;

    /// <summary>Suite this scenario belongs to (e.g. "vision", "orchestrator").</summary>
    [JsonPropertyName("suite")]
    public string Suite { get; init; } = string.Empty;

    /// <summary>
    /// Arbitrary input data for the scenario. Structure is scenario-defined;
    /// may include prompts, file paths, expected outputs, etc.
    /// </summary>
    [JsonPropertyName("input")]
    public Dictionary<string, object?> Input { get; init; } = new();

    /// <summary>
    /// Fixture configuration: setup/teardown commands, file provisioning, service dependencies.
    /// </summary>
    [JsonPropertyName("fixture")]
    public FixtureConfig? Fixture { get; init; }

    /// <summary>
    /// Scoring configuration: which scorers to apply and their parameters.
    /// </summary>
    [JsonPropertyName("scoring")]
    public ScoringConfig? Scoring { get; init; }

    /// <summary>Upper-bound timeout for a single candidate run, in seconds. 0 = no limit.</summary>
    [JsonPropertyName("timeout_seconds")]
    public int TimeoutSeconds { get; init; }
}

/// <summary>
/// Describes fixture setup and teardown for a scenario.
/// </summary>
public sealed class FixtureConfig
{
    /// <summary>Optional shell commands to run before scenario execution.</summary>
    [JsonPropertyName("setup_commands")]
    public List<string> SetupCommands { get; init; } = new();

    /// <summary>Optional shell commands to run after scenario execution.</summary>
    [JsonPropertyName("teardown_commands")]
    public List<string> TeardownCommands { get; init; } = new();

    /// <summary>Files or directories to provision before the run.</summary>
    [JsonPropertyName("provision_files")]
    public Dictionary<string, string> ProvisionFiles { get; init; } = new();
}

/// <summary>
/// Which scorers to apply to a scenario and their configuration.
/// </summary>
public sealed class ScoringConfig
{
    /// <summary>Scorer IDs to apply, in order.</summary>
    [JsonPropertyName("scorers")]
    public List<string> Scorers { get; init; } = new();

    /// <summary>Per-scorer parameter overrides.</summary>
    [JsonPropertyName("parameters")]
    public Dictionary<string, Dictionary<string, object?>> Parameters { get; init; } = new();

    /// <summary>
    /// Per-scorer pass/fail threshold. When a scorer produces a numeric score,
    /// it is compared against this threshold. Default: 0.0 (any positive score passes).
    /// </summary>
    [JsonPropertyName("thresholds")]
    public Dictionary<string, double> Thresholds { get; init; } = new();

    /// <summary>
    /// Configuration for LLM-judge scorers. Maps scorer ID to judge config
    /// (model, prompt_version, temperature, etc.).
    /// </summary>
    [JsonPropertyName("judges")]
    public Dictionary<string, JudgeConfig> Judges { get; init; } = new();
}

/// <summary>
/// Configuration for an LLM judge scorer.
/// </summary>
public sealed class JudgeConfig
{
    /// <summary>Model to use as judge (e.g. "gpt-4o", "claude-sonnet-4").</summary>
    [JsonPropertyName("model")]
    public string? Model { get; init; }

    /// <summary>Provider for the judge model.</summary>
    [JsonPropertyName("provider")]
    public string? Provider { get; init; }

    /// <summary>Prompt template version identifier.</summary>
    [JsonPropertyName("prompt_version")]
    public string PromptVersion { get; init; } = "v1";

    /// <summary>Temperature for judge calls (0.0 = deterministic).</summary>
    [JsonPropertyName("temperature")]
    public double Temperature { get; init; } = 0.0;

    /// <summary>Max tokens for judge response.</summary>
    [JsonPropertyName("max_tokens")]
    public int MaxTokens { get; init; } = 1024;
}
