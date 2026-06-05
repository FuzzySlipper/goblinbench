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

    /// <summary>API endpoint URL for service-endpoint kind or custom base URL for OpenAI-compatible endpoints.</summary>
    [JsonPropertyName("endpoint")]
    public string? Endpoint { get; init; }

    /// <summary>Base URL for OpenAI-compatible API (e.g. "https://api.openai.com/v1"). Overrides endpoint for chat-model kinds.</summary>
    [JsonPropertyName("base_url")]
    public string? BaseUrl { get; init; }

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
    /// Name of an environment variable holding the API key for this candidate.
    /// Never serialised to run artifacts — only used at runtime.
    /// </summary>
    [JsonIgnore]
    public string? ApiKeyEnv { get; init; }

    /// <summary>
    /// Resolved API key value at runtime. Never serialised.
    /// Populated by runners from the environment variable named by <see cref="ApiKeyEnv"/>.
    /// </summary>
    [JsonIgnore]
    public string? ApiKey { get; init; }

    /// <summary>
    /// Runtime metadata for distinguishing prompt identity, profile identity,
    /// and execution environment from model identity.
    /// Typical keys: "prompt_version", "profile_version", "runner_version", "host".
    /// </summary>
    [JsonPropertyName("runtime_metadata")]
    public Dictionary<string, string> RuntimeMetadata { get; init; } = new();

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
    LocalModel,

    /// <summary>
    /// A coding agent CLI (pi, codex, claude, etc.) launched inside a
    /// bubblewrap sandbox. See <c>CodingAgentRunner</c> for the full contract.
    /// </summary>
    CodingAgent,
}
