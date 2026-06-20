using System.Runtime.CompilerServices;
using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace DenCore.Llm;

/// <summary>
/// OpenAI-compatible LLM client for DenCore. Supports both
/// chat completions and structured JSON output via response_format.
/// </summary>
public sealed class OpenAiCompatibleLlmClient : ILlmClient
{
    private readonly HttpClient _httpClient;
    private readonly string _apiKey;
    private readonly string _model;
    private readonly ILogger<OpenAiCompatibleLlmClient> _logger;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = false
    };

    public OpenAiCompatibleLlmClient(
        HttpClient httpClient,
        string apiKey,
        string model,
        ILogger<OpenAiCompatibleLlmClient> logger)
    {
        _httpClient = httpClient;
        _apiKey = apiKey;
        _model = model;
        _logger = logger;
    }

    public async Task<string> CompleteAsync(string systemPrompt, string userPrompt, CancellationToken ct = default)
    {
        var request = new
        {
            model = _model,
            messages = new[]
            {
                new { role = "system", content = systemPrompt },
                new { role = "user", content = userPrompt }
            }
        };

        var response = await SendRequestAsync(request, ct);
        return ExtractContent(response);
    }

    public async IAsyncEnumerable<string> CompleteStreamAsync(
        string systemPrompt, string userPrompt, [EnumeratorCancellation] CancellationToken ct = default)
    {
        var request = new
        {
            model = _model,
            stream = true,
            messages = new[]
            {
                new { role = "system", content = systemPrompt },
                new { role = "user", content = userPrompt }
            }
        };

        var json = JsonSerializer.Serialize(request, JsonOptions);
        var httpRequest = new HttpRequestMessage(HttpMethod.Post, "v1/chat/completions")
        {
            Content = new StringContent(json, System.Text.Encoding.UTF8, "application/json")
        };
        httpRequest.Headers.Add("Authorization", $"Bearer {_apiKey}");

        using var response = await _httpClient.SendAsync(
            httpRequest, HttpCompletionOption.ResponseHeadersRead, ct);
        response.EnsureSuccessStatusCode();

        using var stream = await response.Content.ReadAsStreamAsync(ct);
        using var reader = new StreamReader(stream);

        while (!reader.EndOfStream && !ct.IsCancellationRequested)
        {
            var line = await reader.ReadLineAsync(ct);
            if (string.IsNullOrEmpty(line)) continue;
            if (line.StartsWith("data: "))
            {
                var data = line[6..];
                if (data == "[DONE]") yield break;

                using var doc = JsonDocument.Parse(data);
                var choice = doc.RootElement.GetProperty("choices")[0];
                if (choice.TryGetProperty("delta", out var delta) &&
                    delta.TryGetProperty("content", out var content))
                {
                    yield return content.GetString() ?? "";
                }
            }
        }
    }

    public async Task<T> CompleteStructuredAsync<T>(
        string systemPrompt, string userPrompt, CancellationToken ct = default)
    {
        var request = new
        {
            model = _model,
            response_format = new { type = "json_object" },
            messages = new[]
            {
                new { role = "system", content = systemPrompt },
                new { role = "user", content = userPrompt }
            }
        };

        var response = await SendRequestAsync(request, ct);
        var content = ExtractContent(response);

        return JsonSerializer.Deserialize<T>(content, JsonOptions)
            ?? throw new InvalidOperationException("Failed to deserialize structured response");
    }

    private async Task<JsonDocument> SendRequestAsync(object requestBody, CancellationToken ct)
    {
        var json = JsonSerializer.Serialize(requestBody, JsonOptions);
        var httpRequest = new HttpRequestMessage(HttpMethod.Post, "v1/chat/completions")
        {
            Content = new StringContent(json, System.Text.Encoding.UTF8, "application/json")
        };
        httpRequest.Headers.Add("Authorization", $"Bearer {_apiKey}");

        _logger.LogDebug("Sending LLM request to {Model}", _model);

        var response = await _httpClient.SendAsync(httpRequest, ct);
        response.EnsureSuccessStatusCode();

        var responseBody = await response.Content.ReadAsStringAsync(ct);
        return JsonDocument.Parse(responseBody);
    }

    private static string ExtractContent(JsonDocument doc)
    {
        return doc.RootElement
            .GetProperty("choices")[0]
            .GetProperty("message")
            .GetProperty("content")
            .GetString() ?? "";
    }
}
