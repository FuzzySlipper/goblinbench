using System.Diagnostics;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// Candidate runner that calls an OpenAI-compatible chat completions API.
/// Records latency, raw response, parsed response, and errors.
/// Secrets are never written to run artifacts.
/// </summary>
public sealed class OpenAiChatRunner : ICandidateRunner
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = false
    };

    private static readonly string[] SecretPatterns =
    [
        "api_key", "api-key", "Authorization", "Bearer",
        "sk-", "sk-ant-", "hf_", "x-api-key"
    ];

    private readonly HttpClient _httpClient;

    public string Name => "openai-chat";

    public OpenAiChatRunner(HttpClient? httpClient = null)
    {
        _httpClient = httpClient ?? new HttpClient();
    }

    public bool CanHandle(CandidateConfig candidate) =>
        candidate.Kind == CandidateKind.OpenAiModel;

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;
        var stopwatch = Stopwatch.StartNew();

        // Resolve API key
        var apiKey = ResolveApiKey(candidate);
        var baseUrl = candidate.BaseUrl ?? candidate.Endpoint ?? "https://api.openai.com/v1";
        var model = candidate.Model ?? "gpt-4o";

        // Build the chat completion request
        var messages = BuildMessages(scenario, candidate);

        var requestBody = new
        {
            model,
            messages,
            temperature = GetConfigDouble(candidate, "temperature", 0.7),
            max_tokens = GetConfigInt(candidate, "max_tokens", 4096)
        };

        var requestJson = JsonSerializer.Serialize(requestBody, JsonOptions);
        var trace = new List<TraceEvent>
        {
            new() { Timestamp = DateTime.UtcNow, Event = "openai.request.built",
                Data = new { model, base_url = baseUrl, message_count = messages.Count } }
        };

        try
        {
            var request = new HttpRequestMessage(HttpMethod.Post, $"{baseUrl.TrimEnd('/')}/chat/completions")
            {
                Content = new StringContent(requestJson, Encoding.UTF8, "application/json")
            };

            if (!string.IsNullOrEmpty(apiKey))
                request.Headers.TryAddWithoutValidation("Authorization", $"Bearer {apiKey}");

            trace.Add(new()
            {
                Timestamp = DateTime.UtcNow,
                Event = "openai.request.sent"
            });

            using var response = await _httpClient.SendAsync(request,
                HttpCompletionOption.ResponseHeadersRead, ct);

            var rawResponse = await response.Content.ReadAsStringAsync(ct);
            stopwatch.Stop();

            // Redact secrets from raw response before storing
            rawResponse = RedactSecrets(rawResponse);

            trace.Add(new()
            {
                Timestamp = DateTime.UtcNow,
                Event = "openai.response.received",
                Data = new { status_code = (int)response.StatusCode, content_length = rawResponse.Length }
            });

            object? parsedResponse = null;
            string? error = null;

            if (response.IsSuccessStatusCode)
            {
                try
                {
                    parsedResponse = JsonSerializer.Deserialize<object>(rawResponse);
                }
                catch
                {
                    // Raw response is stored; parsed may be null for non-JSON responses
                }
            }
            else
            {
                error = $"HTTP {(int)response.StatusCode}: {rawResponse[..Math.Min(rawResponse.Length, 500)]}";
            }

            // Build model identity
            var modelIdentity = new ModelIdentity
            {
                Model = model,
                Provider = candidate.Provider,
                BaseUrl = baseUrl,
                DisplayName = $"{candidate.Provider}/{model}"
            };

            // Write artifacts
            await WriteArtifactsAsync(candidate, context, rawResponse, parsedResponse, error, ct);

            return new CandidateResult
            {
                CandidateId = candidate.Id,
                CandidateName = candidate.Name,
                CandidateKind = candidate.Kind,
                ModelIdentity = modelIdentity,
                Success = response.IsSuccessStatusCode,
                Error = error,
                DurationMs = stopwatch.ElapsedMilliseconds,
                RawResponse = rawResponse,
                ParsedResponse = parsedResponse,
                Output = new { model, status = response.IsSuccessStatusCode ? "ok" : "error" },
                Trace = trace,
                ArtifactDirectory = context.GetCandidateArtifactsDirectory(candidate.Id)
            };
        }
        catch (OperationCanceledException)
        {
            stopwatch.Stop();
            return new CandidateResult
            {
                CandidateId = candidate.Id,
                CandidateName = candidate.Name,
                CandidateKind = candidate.Kind,
                ModelIdentity = new ModelIdentity { Model = model, Provider = candidate.Provider, BaseUrl = baseUrl },
                Success = false,
                Error = "Request timed out or was cancelled.",
                DurationMs = stopwatch.ElapsedMilliseconds,
                Trace = trace,
                ArtifactDirectory = context.GetCandidateArtifactsDirectory(candidate.Id)
            };
        }
        catch (Exception ex)
        {
            stopwatch.Stop();
            return new CandidateResult
            {
                CandidateId = candidate.Id,
                CandidateName = candidate.Name,
                CandidateKind = candidate.Kind,
                ModelIdentity = new ModelIdentity { Model = model, Provider = candidate.Provider, BaseUrl = baseUrl },
                Success = false,
                Error = RedactSecrets(ex.Message),
                DurationMs = stopwatch.ElapsedMilliseconds,
                Trace = trace,
                ArtifactDirectory = context.GetCandidateArtifactsDirectory(candidate.Id)
            };
        }
    }

    private static string? ResolveApiKey(CandidateConfig candidate)
    {
        // First, use explicitly-set ApiKey
        if (!string.IsNullOrEmpty(candidate.ApiKey))
            return candidate.ApiKey;

        // Then, try the environment variable named by ApiKeyEnv
        if (!string.IsNullOrEmpty(candidate.ApiKeyEnv))
        {
            var envValue = Environment.GetEnvironmentVariable(candidate.ApiKeyEnv);
            if (!string.IsNullOrEmpty(envValue))
                return envValue;
        }

        // Fallback: common env vars
        return Environment.GetEnvironmentVariable("OPENAI_API_KEY")
            ?? Environment.GetEnvironmentVariable("GOBLINBENCH_OPENAI_API_KEY");
    }

    private static List<object> BuildMessages(Scenario scenario, CandidateConfig candidate)
    {
        var messages = new List<object>();

        if (!string.IsNullOrEmpty(candidate.SystemPrompt))
        {
            messages.Add(new { role = "system", content = candidate.SystemPrompt });
        }

        // Build user message from scenario input
        if (scenario.Input.TryGetValue("prompt", out var prompt) && prompt is string promptStr)
        {
            messages.Add(new { role = "user", content = promptStr });
        }
        else if (scenario.Input.Count > 0)
        {
            // Serialise the entire input as the user message
            var inputJson = JsonSerializer.Serialize(scenario.Input);
            messages.Add(new { role = "user", content = inputJson });
        }
        else
        {
            messages.Add(new { role = "user", content = scenario.Description });
        }

        return messages;
    }

    private static double GetConfigDouble(CandidateConfig candidate, string key, double defaultValue)
    {
        if (candidate.Config.TryGetValue(key, out var val))
        {
            if (val is JsonElement je && je.ValueKind == JsonValueKind.Number)
                return je.GetDouble();
            if (val is double d) return d;
            if (val is int i) return i;
            if (val is long l) return l;
        }
        return defaultValue;
    }

    private static int GetConfigInt(CandidateConfig candidate, string key, int defaultValue)
    {
        if (candidate.Config.TryGetValue(key, out var val))
        {
            if (val is JsonElement je && je.ValueKind == JsonValueKind.Number)
                return je.GetInt32();
            if (val is int i) return i;
            if (val is long l) return (int)l;
            if (val is double d) return (int)d;
        }
        return defaultValue;
    }

    /// <summary>
    /// Redact known secret patterns from a string before writing to artifacts.
    /// </summary>
    public static string RedactSecrets(string text)
    {
        if (string.IsNullOrEmpty(text))
            return text;

        foreach (var pattern in SecretPatterns)
        {
            // Case-insensitive redaction for header-like patterns
            var idx = text.IndexOf(pattern, StringComparison.OrdinalIgnoreCase);
            while (idx >= 0)
            {
                // Find the end of the value (next whitespace, comma, newline, or quote)
                var end = idx + pattern.Length;
                // Skip past optional colon/equals and spaces
                while (end < text.Length && (text[end] == ':' || text[end] == '=' || text[end] == ' '))
                    end++;

                // Capture the value until whitespace/comma/newline/quote
                var valueStart = end;
                while (end < text.Length && !IsBoundary(text[end]))
                    end++;

                if (valueStart < end)
                {
                    text = text[..valueStart] + "[REDACTED]" + text[end..];
                }

                idx = text.IndexOf(pattern, valueStart, StringComparison.OrdinalIgnoreCase);
            }
        }

        return text;
    }

    private static bool IsBoundary(char c) =>
        c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == ',' || c == '"' || c == '}' || c == ']';

    private async Task WriteArtifactsAsync(
        CandidateConfig candidate,
        RunContext context,
        string? rawResponse,
        object? parsedResponse,
        string? error,
        CancellationToken ct)
    {
        var artifactDir = context.GetCandidateArtifactsDirectory(candidate.Id);
        Directory.CreateDirectory(artifactDir);

        // Write raw response (already redacted)
        if (!string.IsNullOrEmpty(rawResponse))
        {
            var responsePath = context.GetCandidateOutputPath(candidate.Id);
            Directory.CreateDirectory(Path.GetDirectoryName(responsePath)!);
            await File.WriteAllTextAsync(responsePath, rawResponse, ct);
        }

        // Write parsed response
        if (parsedResponse != null)
        {
            var parsedPath = Path.Combine(artifactDir, "parsed_response.json");
            var parsedJson = JsonSerializer.Serialize(parsedResponse,
                new JsonSerializerOptions { WriteIndented = true });
            await File.WriteAllTextAsync(parsedPath, parsedJson, ct);
        }

        // Write error if present
        if (!string.IsNullOrEmpty(error))
        {
            var errorPath = Path.Combine(artifactDir, "error.txt");
            await File.WriteAllTextAsync(errorPath, RedactSecrets(error), ct);
        }

        // Write trace
        var tracePath = context.GetCandidateTracePath(candidate.Id);
        Directory.CreateDirectory(Path.GetDirectoryName(tracePath)!);
        // trace events are written by Runner CLI, not here
    }
}
