namespace DenCore.Llm;

/// <summary>
/// Abstraction over an LLM provider for generating completions,
/// summaries, and structured data from natural language prompts.
/// </summary>
public interface ILlmClient
{
    /// <summary>Send a completion request and get the response text.</summary>
    Task<string> CompleteAsync(string systemPrompt, string userPrompt, CancellationToken ct = default);

    /// <summary>Send a streaming completion request.</summary>
    IAsyncEnumerable<string> CompleteStreamAsync(string systemPrompt, string userPrompt, CancellationToken ct = default);

    /// <summary>Send a structured completion expecting JSON output.</summary>
    Task<T> CompleteStructuredAsync<T>(string systemPrompt, string userPrompt, CancellationToken ct = default);
}
