using System.Text.Json.Serialization;

namespace GoblinBench.Core;

/// <summary>
/// What is being evaluated: a raw model, Hermes profile,
/// service endpoint, or external agent CLI.
/// </summary>
public sealed class CandidateConfig
{
    /// <summary>Unique identifier for this candidate within a run.</summary>
    [JsonPropertyName("id")]
    public string Id { get; init; } = string.Empty;

    /// <summary>Human-readable label for reports.</summary>
    [JsonPropertyName("name")]
    public string Name { get; init; } = string.Empty;

    /// <summary>
    /// The kind of candidate: "openai-model", "hermes-profile",
    /// "service-endpoint", "external-cli", "local-model".
    /// </summary>
    [JsonPropertyName("kind")]
    public CandidateKind Kind { get; init; }

    /// <summary>Model identifier (e.g. "gpt-4o", "claude-sonnet-4").</summary>
    [JsonPropertyName("model")]
    public string? Model { get; init; }

    /// <summary>Provider name (e.g. "openai", "anthropic", "deepseek").</summary>
    [JsonPropertyName("provider")]
    public string? Provider { get; init; }

    /// <summary>API endpoint URL for service-endpoint kind.</summary>
    [JsonPropertyName("endpoint")]
    public string? Endpoint { get; init; }

    /// <summary>Hermes profile name for hermes-profile kind.</summary>
    [JsonPropertyName("profile")]
    public string? Profile { get; init; }

    /// <summary>CLI command for external-cli kind (e.g. "codex", "claude").</summary>
    [JsonPropertyName("cli_command")]
    public string? CliCommand { get; init; }

    /// <summary>Additional CLI arguments.</summary>
    [JsonPropertyName("cli_args")]
    public List<string> CliArgs { get; init; } = new();

    /// <summary>System prompt override for chat-model candidates.</summary>
    [JsonPropertyName("system_prompt")]
    public string? SystemPrompt { get; init; }

    /// <summary>
    /// Extra configuration key-value pairs for runner-specific use.
    /// </summary>
    [JsonPropertyName("config")]
    public Dictionary<string, object?> Config { get; init; } = new();
}

/// <summary>
/// Classification of a candidate's runtime shape.
/// </summary>
[JsonConverter(typeof(JsonStringEnumConverter))]
public enum CandidateKind
{
    /// <summary>Not yet classified.</summary>
    Unknown,

    /// <summary>An OpenAI-compatible chat model endpoint.</summary>
    OpenAiModel,

    /// <summary>A Hermes profile launched via spawned Hermes.</summary>
    HermesProfile,

    /// <summary>A Den capability service endpoint.</summary>
    ServiceEndpoint,

    /// <summary>An external coding CLI (Codex, Claude Code, OpenCode).</summary>
    ExternalCli,

    /// <summary>A local model endpoint (vLLM, llama.cpp, etc.).</summary>
    LocalModel
}
