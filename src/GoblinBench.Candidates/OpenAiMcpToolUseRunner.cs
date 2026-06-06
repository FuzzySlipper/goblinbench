using System.Diagnostics;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// OpenAI-compatible real-model runner for GoblinBench fake-MCP tool-use scenarios.
///
/// The runner maps scenario-owned <c>input.fake_mcp.tools</c> entries into the
/// OpenAI chat-completions tool schema, executes requested tool calls against the
/// scenario's canned fake results, and writes the same artifact shape consumed by
/// <see cref="GoblinBench.Scorers.McpToolUseScorer"/>.
/// </summary>
public sealed class OpenAiMcpToolUseRunner : ICandidateRunner
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        WriteIndented = true
    };

    private readonly HttpClient _httpClient;

    public OpenAiMcpToolUseRunner(HttpClient? httpClient = null)
    {
        _httpClient = httpClient ?? new HttpClient();
    }

    public string Name => "mcp-openai-tool-use";

    public bool CanHandle(CandidateConfig candidate) =>
        candidate.Kind == CandidateKind.OpenAiModel &&
        (string.Equals(candidate.CliCommand, "mcp-openai-tool-use", StringComparison.OrdinalIgnoreCase) ||
         ConfigString(candidate, "runner")?.Equals("mcp-openai-tool-use", StringComparison.OrdinalIgnoreCase) == true);

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;
        var stopwatch = Stopwatch.StartNew();
        var artifactDir = context.GetCandidateArtifactsDirectory(candidate.Id);
        Directory.CreateDirectory(artifactDir);

        var trace = new List<TraceEvent>
        {
            new() { Timestamp = startedAt, Event = "mcp_openai.started", Data = new { scenario = scenario.Id } }
        };
        var toolCallRecords = new List<Dictionary<string, object?>>();
        var bypassAttempts = new List<Dictionary<string, object?>>();
        var messages = BuildInitialMessages(scenario, candidate);
        var fakeTools = GetFakeTools(scenario).ToList();
        var scriptedCalls = GetScriptedToolCalls(scenario).ToList();
        var usedScriptedCallIndexes = new HashSet<int>();
        var baseUrl = candidate.BaseUrl ?? candidate.Endpoint ?? "https://api.openai.com/v1";
        var model = candidate.Model ?? "gpt-4o";
        var finalResponse = string.Empty;
        string? error = null;
        var success = false;

        try
        {
            if (fakeTools.Count == 0)
                throw new InvalidOperationException("MCP tool-use scenario has no input.fake_mcp.tools entries.");

            var maxToolRounds = Math.Max(1, ConfigInt(candidate, "max_tool_rounds", 6));
            for (var round = 0; round < maxToolRounds; round++)
            {
                var requestBody = BuildRequestBody(candidate, model, messages, fakeTools);
                var requestJson = JsonSerializer.Serialize(requestBody, JsonOptions);
                await File.WriteAllTextAsync(Path.Combine(artifactDir, $"request_round_{round + 1}.json"), requestJson, ct);

                using var request = new HttpRequestMessage(HttpMethod.Post, $"{baseUrl.TrimEnd('/')}/chat/completions")
                {
                    Content = new StringContent(requestJson, Encoding.UTF8, "application/json")
                };

                var apiKey = ResolveApiKey(candidate);
                if (!string.IsNullOrEmpty(apiKey))
                    request.Headers.TryAddWithoutValidation("Authorization", $"Bearer {apiKey}");

                trace.Add(new TraceEvent
                {
                    Timestamp = DateTime.UtcNow,
                    Event = "mcp_openai.request.sent",
                    Data = new { round = round + 1, model, tool_count = fakeTools.Count }
                });

                using var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);
                var rawResponse = OpenAiChatRunner.RedactSecrets(await response.Content.ReadAsStringAsync(ct)) ?? string.Empty;
                await File.WriteAllTextAsync(Path.Combine(artifactDir, $"api_response_round_{round + 1}.json"), rawResponse, ct);

                trace.Add(new TraceEvent
                {
                    Timestamp = DateTime.UtcNow,
                    Event = "mcp_openai.response.received",
                    Data = new { round = round + 1, status_code = (int)response.StatusCode, content_length = rawResponse.Length }
                });

                if (!response.IsSuccessStatusCode)
                {
                    error = $"HTTP {(int)response.StatusCode}: {rawResponse[..Math.Min(rawResponse.Length, 500)]}";
                    break;
                }

                using var responseDoc = JsonDocument.Parse(rawResponse);
                var message = ExtractMessage(responseDoc.RootElement);
                finalResponse = ExtractMessageContent(message) ?? finalResponse;
                var toolCalls = ExtractToolCalls(message).ToList();

                if (toolCalls.Count == 0)
                {
                    success = true;
                    break;
                }

                messages.Add(BuildAssistantMessage(message, finalResponse, toolCalls));

                foreach (var toolCall in toolCalls)
                {
                    var callId = ExtractToolCallId(toolCall);
                    var toolName = ExtractToolName(toolCall);
                    var arguments = ExtractToolArguments(toolCall);
                    var result = ExecuteFakeTool(toolName, scriptedCalls, usedScriptedCallIndexes);

                    var record = new Dictionary<string, object?>
                    {
                        ["tool"] = toolName,
                        ["arguments"] = arguments,
                        ["result"] = result,
                        ["tool_call_id"] = callId,
                        ["order"] = toolCallRecords.Count + 1
                    };
                    toolCallRecords.Add(record);

                    trace.Add(new TraceEvent
                    {
                        Timestamp = DateTime.UtcNow,
                        Event = "mcp_openai.tool_called",
                        Data = record
                    });

                    messages.Add(new Dictionary<string, object?>
                    {
                        ["role"] = "tool",
                        ["tool_call_id"] = callId,
                        ["name"] = toolName,
                        ["content"] = JsonSerializer.Serialize(result, JsonOptions)
                    });
                }
            }

            if (!success && error == null)
                error = "Model did not produce a final response before max_tool_rounds was reached.";
        }
        catch (OperationCanceledException)
        {
            error = "Request timed out or was cancelled.";
        }
        catch (Exception ex)
        {
            error = OpenAiChatRunner.RedactSecrets(ex.Message);
        }
        finally
        {
            stopwatch.Stop();
        }

        if (string.IsNullOrWhiteSpace(finalResponse) && error != null)
            finalResponse = error;

        var output = new Dictionary<string, object?>
        {
            ["tool_calls"] = toolCallRecords,
            ["bypass_attempts"] = bypassAttempts,
            ["final_response"] = finalResponse
        };
        var rawOutput = JsonSerializer.Serialize(output, JsonOptions);
        var parsed = JsonSerializer.Deserialize<JsonElement>(rawOutput);

        await WriteScoringArtifactsAsync(context, candidate, artifactDir, toolCallRecords, bypassAttempts, finalResponse, rawOutput, error, ct);
        await File.WriteAllTextAsync(
            Path.Combine(artifactDir, "chat_transcript.json"),
            JsonSerializer.Serialize(messages, JsonOptions),
            ct);

        trace.Add(new TraceEvent
        {
            Timestamp = DateTime.UtcNow,
            Event = success ? "mcp_openai.completed" : "mcp_openai.failed",
            Data = new
            {
                tool_call_count = toolCallRecords.Count,
                bypass_attempt_count = bypassAttempts.Count,
                artifact_dir = artifactDir,
                error
            }
        });

        return new CandidateResult
        {
            CandidateId = candidate.Id,
            CandidateName = candidate.Name,
            CandidateKind = candidate.Kind,
            ModelIdentity = new ModelIdentity
            {
                Model = model,
                Provider = candidate.Provider,
                BaseUrl = baseUrl,
                DisplayName = $"{candidate.Provider}/{model} MCP tools"
            },
            Success = success,
            Error = error,
            DurationMs = stopwatch.ElapsedMilliseconds,
            RawResponse = rawOutput,
            ParsedResponse = parsed,
            Output = parsed,
            Trace = trace,
            ArtifactDirectory = artifactDir
        };
    }

    private static Dictionary<string, object?> BuildRequestBody(
        CandidateConfig candidate,
        string model,
        List<Dictionary<string, object?>> messages,
        IReadOnlyList<JsonElement> fakeTools) => new()
    {
        ["model"] = model,
        ["messages"] = messages,
        ["tools"] = fakeTools.Select(ToOpenAiTool).ToList(),
        ["tool_choice"] = ConfigString(candidate, "tool_choice") ?? "auto",
        ["temperature"] = ConfigDouble(candidate, "temperature", 0.2),
        ["max_tokens"] = ConfigInt(candidate, "max_tokens", 4096)
    };

    private static Dictionary<string, object?> ToOpenAiTool(JsonElement tool)
    {
        var name = GetString(tool, "name") ?? "unknown_fake_tool";
        var description = GetString(tool, "description") ?? string.Empty;
        var parameters = tool.TryGetProperty("input_schema", out var schema)
            ? schema.Clone()
            : JsonSerializer.SerializeToElement(new Dictionary<string, object?> { ["type"] = "object" });

        return new Dictionary<string, object?>
        {
            ["type"] = "function",
            ["function"] = new Dictionary<string, object?>
            {
                ["name"] = name,
                ["description"] = description,
                ["parameters"] = parameters
            }
        };
    }

    private static List<Dictionary<string, object?>> BuildInitialMessages(Scenario scenario, CandidateConfig candidate)
    {
        var messages = new List<Dictionary<string, object?>>();
        messages.Add(new Dictionary<string, object?>
        {
            ["role"] = "system",
            ["content"] = candidate.SystemPrompt ??
                "You are evaluating fake MCP tool use. Use only the provided tools when a tool is needed. Do not claim to perform real-world side effects. After using tools, provide a concise final answer grounded in tool results."
        });
        messages.Add(new Dictionary<string, object?>
        {
            ["role"] = "user",
            ["content"] = GetScenarioPrompt(scenario)
        });
        return messages;
    }

    private static string GetScenarioPrompt(Scenario scenario)
    {
        if (scenario.Input.TryGetValue("prompt", out var prompt))
        {
            if (prompt is string s) return s;
            if (prompt is JsonElement element && element.ValueKind == JsonValueKind.String)
                return element.GetString() ?? scenario.Description;
        }
        return scenario.Description;
    }

    private static JsonElement ExtractMessage(JsonElement root)
    {
        if (root.TryGetProperty("choices", out var choices) &&
            choices.ValueKind == JsonValueKind.Array &&
            choices.GetArrayLength() > 0 &&
            choices[0].TryGetProperty("message", out var message))
            return message.Clone();
        throw new InvalidOperationException("OpenAI-compatible response did not include choices[0].message.");
    }

    private static string? ExtractMessageContent(JsonElement message)
    {
        if (message.TryGetProperty("content", out var content) && content.ValueKind == JsonValueKind.String)
            return content.GetString();
        return null;
    }

    private static IEnumerable<JsonElement> ExtractToolCalls(JsonElement message)
    {
        if (!message.TryGetProperty("tool_calls", out var toolCalls) || toolCalls.ValueKind != JsonValueKind.Array)
            yield break;
        foreach (var call in toolCalls.EnumerateArray())
            yield return call.Clone();
    }

    private static Dictionary<string, object?> BuildAssistantMessage(JsonElement message, string? content, List<JsonElement> toolCalls) => new()
    {
        ["role"] = "assistant",
        ["content"] = content,
        ["tool_calls"] = toolCalls
    };

    private static string ExtractToolCallId(JsonElement toolCall)
    {
        if (toolCall.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.String)
            return id.GetString() ?? Guid.NewGuid().ToString("N");
        return Guid.NewGuid().ToString("N");
    }

    private static string ExtractToolName(JsonElement toolCall)
    {
        if (toolCall.TryGetProperty("function", out var function) &&
            function.TryGetProperty("name", out var name) &&
            name.ValueKind == JsonValueKind.String)
            return name.GetString() ?? string.Empty;
        if (toolCall.TryGetProperty("name", out var directName) && directName.ValueKind == JsonValueKind.String)
            return directName.GetString() ?? string.Empty;
        return string.Empty;
    }

    private static JsonElement ExtractToolArguments(JsonElement toolCall)
    {
        if (!toolCall.TryGetProperty("function", out var function) ||
            !function.TryGetProperty("arguments", out var arguments))
            return JsonSerializer.SerializeToElement(new Dictionary<string, object?>());

        if (arguments.ValueKind == JsonValueKind.String)
        {
            var raw = arguments.GetString() ?? "{}";
            try
            {
                using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(raw) ? "{}" : raw);
                return doc.RootElement.Clone();
            }
            catch
            {
                return JsonSerializer.SerializeToElement(new Dictionary<string, object?> { ["_raw"] = raw });
            }
        }

        return arguments.Clone();
    }

    private static JsonElement ExecuteFakeTool(
        string toolName,
        IReadOnlyList<JsonElement> scriptedCalls,
        HashSet<int> usedScriptedCallIndexes)
    {
        for (var i = 0; i < scriptedCalls.Count; i++)
        {
            if (usedScriptedCallIndexes.Contains(i))
                continue;
            var call = scriptedCalls[i];
            if (GetString(call, "tool") == toolName)
            {
                usedScriptedCallIndexes.Add(i);
                if (call.TryGetProperty("result", out var result))
                    return result.Clone();
                return JsonSerializer.SerializeToElement(new Dictionary<string, object?> { ["ok"] = true });
            }
        }

        var knownToolNames = scriptedCalls.Select(c => GetString(c, "tool")).Where(n => n != null).ToHashSet();
        if (!knownToolNames.Contains(toolName))
            return JsonSerializer.SerializeToElement(new Dictionary<string, object?>
            {
                ["ok"] = false,
                ["error"] = $"unknown or unscripted fake tool: {toolName}"
            });

        return JsonSerializer.SerializeToElement(new Dictionary<string, object?>
        {
            ["ok"] = true,
            ["note"] = "tool called more times than canned results were provided"
        });
    }

    private static async Task WriteScoringArtifactsAsync(
        RunContext context,
        CandidateConfig candidate,
        string artifactDir,
        List<Dictionary<string, object?>> toolCalls,
        List<Dictionary<string, object?>> bypassAttempts,
        string finalResponse,
        string rawOutput,
        string? error,
        CancellationToken ct)
    {
        await File.WriteAllTextAsync(Path.Combine(artifactDir, "tool_calls.json"), JsonSerializer.Serialize(toolCalls, JsonOptions), ct);
        await File.WriteAllTextAsync(Path.Combine(artifactDir, "bypass_attempts.json"), JsonSerializer.Serialize(bypassAttempts, JsonOptions), ct);
        await File.WriteAllTextAsync(Path.Combine(artifactDir, "final_response.txt"), finalResponse, ct);

        var outputPath = context.GetCandidateOutputPath(candidate.Id);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        await File.WriteAllTextAsync(outputPath, rawOutput, ct);

        if (!string.IsNullOrWhiteSpace(error))
            await File.WriteAllTextAsync(Path.Combine(artifactDir, "error.txt"), error, ct);
    }

    private static IEnumerable<JsonElement> GetFakeTools(Scenario scenario)
    {
        if (!scenario.Input.TryGetValue("fake_mcp", out var fakeMcp) || fakeMcp is null)
            yield break;

        var fakeMcpElement = ToJsonElement(fakeMcp);
        if (!fakeMcpElement.TryGetProperty("tools", out var tools) || tools.ValueKind != JsonValueKind.Array)
            yield break;

        foreach (var tool in tools.EnumerateArray())
            yield return tool.Clone();
    }

    private static IEnumerable<JsonElement> GetScriptedToolCalls(Scenario scenario)
    {
        if (!scenario.Input.TryGetValue("scripted_tool_calls", out var calls) || calls is null)
            yield break;

        var callsElement = ToJsonElement(calls);
        if (callsElement.ValueKind != JsonValueKind.Array)
            yield break;

        foreach (var call in callsElement.EnumerateArray())
            yield return call.Clone();
    }

    private static JsonElement ToJsonElement(object value)
    {
        if (value is JsonElement element)
            return element.Clone();
        return JsonSerializer.SerializeToElement(value, JsonOptions);
    }

    private static string? GetString(JsonElement element, string property)
    {
        if (element.ValueKind == JsonValueKind.Object &&
            element.TryGetProperty(property, out var value) &&
            value.ValueKind == JsonValueKind.String)
            return value.GetString();
        return null;
    }

    private static string? ResolveApiKey(CandidateConfig candidate)
    {
        if (!string.IsNullOrEmpty(candidate.ApiKey))
            return candidate.ApiKey;
        if (!string.IsNullOrEmpty(candidate.ApiKeyEnv))
        {
            var envValue = Environment.GetEnvironmentVariable(candidate.ApiKeyEnv);
            if (!string.IsNullOrEmpty(envValue))
                return envValue;
        }
        var configEnv = ConfigString(candidate, "api_key_env");
        if (!string.IsNullOrEmpty(configEnv))
        {
            var envValue = Environment.GetEnvironmentVariable(configEnv);
            if (!string.IsNullOrEmpty(envValue))
                return envValue;
        }
        return Environment.GetEnvironmentVariable("OPENAI_API_KEY")
            ?? Environment.GetEnvironmentVariable("GOBLINBENCH_OPENAI_API_KEY");
    }

    private static string? ConfigString(CandidateConfig candidate, string key)
    {
        if (!candidate.Config.TryGetValue(key, out var value) || value is null)
            return null;
        if (value is string s) return s;
        if (value is JsonElement element)
        {
            if (element.ValueKind == JsonValueKind.String) return element.GetString();
            return element.ToString();
        }
        return value.ToString();
    }

    private static int ConfigInt(CandidateConfig candidate, string key, int defaultValue)
    {
        if (!candidate.Config.TryGetValue(key, out var value) || value is null)
            return defaultValue;
        if (value is int i) return i;
        if (value is long l) return (int)l;
        if (value is double d) return (int)d;
        if (value is JsonElement element && element.ValueKind == JsonValueKind.Number && element.TryGetInt32(out var parsed))
            return parsed;
        return int.TryParse(value.ToString(), out var textParsed) ? textParsed : defaultValue;
    }

    private static double ConfigDouble(CandidateConfig candidate, string key, double defaultValue)
    {
        if (!candidate.Config.TryGetValue(key, out var value) || value is null)
            return defaultValue;
        if (value is double d) return d;
        if (value is int i) return i;
        if (value is long l) return l;
        if (value is JsonElement element && element.ValueKind == JsonValueKind.Number && element.TryGetDouble(out var parsed))
            return parsed;
        return double.TryParse(value.ToString(), out var textParsed) ? textParsed : defaultValue;
    }
}
