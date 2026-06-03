using System.Diagnostics;
using System.Text;
using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// Candidate runner for vision-capable models (OpenAI-compatible multimodal API).
/// Reads image paths from <c>scenario.input.image_paths</c>, encodes them as base64
/// data URLs, and calls the chat completions endpoint with a multimodal message.
///
/// The system prompt instructs the model to return a structured JSON response
/// compatible with the Den Vision Analyzer output schema.
///
/// Activated by <c>cli_command = "vision-openai"</c>.
/// </summary>
public sealed class VisionCandidateRunner : ICandidateRunner
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = false
    };

    private static readonly string VisionSystemPrompt =
        """
        You are a vision analysis assistant. Analyze the provided screenshot(s) carefully and answer the question.

        Always respond with a JSON object matching this exact schema:
        {
          "elements_found": ["list", "of", "ui", "elements", "you", "can", "see"],
          "answer": "direct answer to the question asked",
          "confidence": 0.0,
          "hallucination_risk": "low|medium|high",
          "suggested_action": "next action to take, or null if not applicable",
          "actionability": 0.0
        }

        Rules:
        - elements_found: list only elements you can actually see. Do NOT invent elements.
        - answer: be specific and direct. Reference what you actually observe.
        - confidence: your confidence in the analysis (0.0 = uncertain, 1.0 = certain).
        - hallucination_risk: rate your own risk of confabulating. "high" if uncertain about details.
        - suggested_action: the most likely next user interaction, or null if not asked.
        - actionability: how actionable your analysis is for the caller (0.0 = no action needed, 1.0 = clear next step).

        Output ONLY the JSON object. Do not wrap it in markdown code blocks or add explanation.
        """;

    private readonly HttpClient _httpClient;

    public string Name => "vision-openai";

    public VisionCandidateRunner(HttpClient? httpClient = null)
    {
        _httpClient = httpClient ?? new HttpClient();
    }

    public bool CanHandle(CandidateConfig candidate) =>
        string.Equals(candidate.CliCommand, "vision-openai", StringComparison.OrdinalIgnoreCase);

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;
        var stopwatch = Stopwatch.StartNew();

        var apiKey = ResolveApiKey(candidate);
        var baseUrl = candidate.BaseUrl ?? candidate.Endpoint ?? "https://api.openai.com/v1";
        var model = candidate.Model ?? "gpt-4o";

        var trace = new List<TraceEvent>
        {
            new() { Timestamp = DateTime.UtcNow, Event = "vision.runner.started",
                Data = new { model, base_url = baseUrl } }
        };

        try
        {
            var imageParts = await BuildImagePartsAsync(scenario, context, trace, ct);
            var prompt = GetPrompt(scenario);
            var messages = BuildMessages(prompt, imageParts, candidate);

            var requestBody = new
            {
                model,
                messages,
                temperature = GetConfigDouble(candidate, "temperature", 0.2),
                max_tokens = GetConfigInt(candidate, "max_tokens", 2048)
            };

            var requestJson = JsonSerializer.Serialize(requestBody, JsonOptions);

            trace.Add(new()
            {
                Timestamp = DateTime.UtcNow, Event = "vision.request.sent",
                Data = new { image_count = imageParts.Count, prompt_length = prompt.Length }
            });

            var request = new HttpRequestMessage(
                HttpMethod.Post, $"{baseUrl.TrimEnd('/')}/chat/completions")
            {
                Content = new StringContent(requestJson, Encoding.UTF8, "application/json")
            };

            if (!string.IsNullOrEmpty(apiKey))
                request.Headers.TryAddWithoutValidation("Authorization", $"Bearer {apiKey}");

            using var response = await _httpClient.SendAsync(
                request, HttpCompletionOption.ResponseHeadersRead, ct);
            var rawResponse = OpenAiChatRunner.RedactSecrets(
                await response.Content.ReadAsStringAsync(ct)) ?? string.Empty;
            stopwatch.Stop();

            trace.Add(new()
            {
                Timestamp = DateTime.UtcNow, Event = "vision.response.received",
                Data = new { status_code = (int)response.StatusCode }
            });

            // Extract model text and parse structured JSON
            string? modelText = null;
            JsonElement? parsedOutput = null;
            string? error = null;

            if (response.IsSuccessStatusCode)
            {
                modelText = ExtractModelText(rawResponse);
                if (modelText != null)
                    parsedOutput = TryParseJson(modelText);
            }
            else
            {
                error = $"HTTP {(int)response.StatusCode}: {rawResponse[..Math.Min(rawResponse.Length, 500)]}";
            }

            await WriteArtifactsAsync(candidate, context, rawResponse, parsedOutput, ct);

            return new CandidateResult
            {
                CandidateId = candidate.Id,
                CandidateName = candidate.Name,
                CandidateKind = candidate.Kind,
                ModelIdentity = new ModelIdentity
                {
                    Model = model, Provider = candidate.Provider,
                    BaseUrl = baseUrl, DisplayName = $"{candidate.Provider}/{model}"
                },
                Success = response.IsSuccessStatusCode,
                Error = error,
                DurationMs = stopwatch.ElapsedMilliseconds,
                RawResponse = modelText ?? rawResponse,
                ParsedResponse = parsedOutput.HasValue ? (object)parsedOutput.Value : null,
                Output = parsedOutput.HasValue ? (object)parsedOutput.Value : null,
                Trace = trace,
                ArtifactDirectory = context.GetCandidateArtifactsDirectory(candidate.Id)
            };
        }
        catch (OperationCanceledException)
        {
            stopwatch.Stop();
            return Failure(candidate, model, baseUrl, "Request timed out or was cancelled.",
                stopwatch.ElapsedMilliseconds, trace);
        }
        catch (Exception ex)
        {
            stopwatch.Stop();
            return Failure(candidate, model, baseUrl,
                OpenAiChatRunner.RedactSecrets(ex.Message) ?? ex.Message,
                stopwatch.ElapsedMilliseconds, trace);
        }
    }

    // ── message construction ──────────────────────────────────────────────────

    private static async Task<List<object>> BuildImagePartsAsync(
        Scenario scenario, RunContext context, List<TraceEvent> trace, CancellationToken ct)
    {
        var parts = new List<object>();
        if (!scenario.Input.TryGetValue("image_paths", out var pathsObj) || pathsObj == null)
            return parts;

        var paths = new List<string>();
        if (pathsObj is JsonElement je && je.ValueKind == JsonValueKind.Array)
            paths = je.EnumerateArray()
                .Where(e => e.ValueKind == JsonValueKind.String)
                .Select(e => e.GetString()!)
                .ToList();

        // Resolve paths relative to repo root (parent of the runs directory)
        var runsParent = Path.GetDirectoryName(context.RunsRoot) ?? context.RunsRoot;

        foreach (var relPath in paths)
        {
            var absPath = Path.IsPathRooted(relPath) ? relPath : Path.Combine(runsParent, relPath);
            if (!File.Exists(absPath))
            {
                trace.Add(new() { Timestamp = DateTime.UtcNow, Event = "vision.image.not_found",
                    Data = new { path = relPath } });
                continue;
            }

            var bytes = await File.ReadAllBytesAsync(absPath, ct);
            var mime = absPath.EndsWith(".png", StringComparison.OrdinalIgnoreCase) ? "image/png" : "image/jpeg";
            var b64 = Convert.ToBase64String(bytes);

            parts.Add(new
            {
                type = "image_url",
                image_url = new { url = $"data:{mime};base64,{b64}", detail = "high" }
            });

            trace.Add(new() { Timestamp = DateTime.UtcNow, Event = "vision.image.encoded",
                Data = new { path = relPath, bytes = bytes.Length } });
        }

        return parts;
    }

    private static List<object> BuildMessages(string prompt, List<object> imageParts, CandidateConfig candidate)
    {
        var systemPrompt = candidate.SystemPrompt ?? VisionSystemPrompt;
        var content = new List<object> { new { type = "text", text = prompt } };
        content.AddRange(imageParts);

        return new List<object>
        {
            new { role = "system", content = systemPrompt },
            new { role = "user", content = (object)content }
        };
    }

    private static string GetPrompt(Scenario scenario) =>
        scenario.Input.TryGetValue("prompt", out var p) && p is string s ? s
        : scenario.Input.TryGetValue("prompt", out var p2) && p2 is JsonElement je
            && je.ValueKind == JsonValueKind.String ? je.GetString()!
        : scenario.Description;

    // ── response parsing ──────────────────────────────────────────────────────

    private static string? ExtractModelText(string rawApiResponse)
    {
        try
        {
            using var doc = JsonDocument.Parse(rawApiResponse);
            if (doc.RootElement.TryGetProperty("choices", out var choices)
                && choices.ValueKind == JsonValueKind.Array
                && choices.GetArrayLength() > 0)
            {
                var first = choices[0];
                if (first.TryGetProperty("message", out var msg)
                    && msg.TryGetProperty("content", out var content)
                    && content.ValueKind == JsonValueKind.String)
                    return content.GetString();
            }
        }
        catch { }
        return null;
    }

    private static JsonElement? TryParseJson(string text)
    {
        var t = text.Trim();
        // Strip markdown code fences if present
        if (t.StartsWith("```"))
        {
            var start = t.IndexOf('\n');
            var end = t.LastIndexOf("```");
            if (start >= 0 && end > start)
                t = t[(start + 1)..end].Trim();
        }
        // Find first { to last }
        var objStart = t.IndexOf('{');
        var objEnd = t.LastIndexOf('}');
        if (objStart >= 0 && objEnd > objStart)
        {
            try
            {
                using var doc = JsonDocument.Parse(t[objStart..(objEnd + 1)]);
                return doc.RootElement.Clone();
            }
            catch { }
        }
        return null;
    }

    // ── helpers ───────────────────────────────────────────────────────────────

    private static string? ResolveApiKey(CandidateConfig candidate)
    {
        if (!string.IsNullOrEmpty(candidate.ApiKey)) return candidate.ApiKey;
        if (!string.IsNullOrEmpty(candidate.ApiKeyEnv))
        {
            var v = Environment.GetEnvironmentVariable(candidate.ApiKeyEnv);
            if (!string.IsNullOrEmpty(v)) return v;
        }
        return Environment.GetEnvironmentVariable("OPENAI_API_KEY")
            ?? Environment.GetEnvironmentVariable("GOBLINBENCH_OPENAI_API_KEY");
    }

    private static double GetConfigDouble(CandidateConfig c, string key, double def)
    {
        if (c.Config.TryGetValue(key, out var v))
        {
            if (v is JsonElement je && je.ValueKind == JsonValueKind.Number) return je.GetDouble();
            if (v is double d) return d;
        }
        return def;
    }

    private static int GetConfigInt(CandidateConfig c, string key, int def)
    {
        if (c.Config.TryGetValue(key, out var v))
        {
            if (v is JsonElement je && je.ValueKind == JsonValueKind.Number) return je.GetInt32();
            if (v is int i) return i;
        }
        return def;
    }

    private static async Task WriteArtifactsAsync(
        CandidateConfig candidate, RunContext context,
        string? rawResponse, JsonElement? parsed, CancellationToken ct)
    {
        var artifactDir = context.GetCandidateArtifactsDirectory(candidate.Id);
        Directory.CreateDirectory(artifactDir);

        var outputPath = context.GetCandidateOutputPath(candidate.Id);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);

        if (!string.IsNullOrEmpty(rawResponse))
            await File.WriteAllTextAsync(outputPath, rawResponse, ct);

        if (parsed.HasValue)
        {
            var parsedPath = Path.Combine(artifactDir, "vision_analysis.json");
            await File.WriteAllTextAsync(parsedPath,
                JsonSerializer.Serialize(parsed.Value, new JsonSerializerOptions { WriteIndented = true }), ct);
        }
    }

    private static CandidateResult Failure(CandidateConfig c, string model,
        string baseUrl, string error, long durationMs, List<TraceEvent> trace) =>
        new()
        {
            CandidateId = c.Id, CandidateName = c.Name, CandidateKind = c.Kind,
            ModelIdentity = new() { Model = model, Provider = c.Provider, BaseUrl = baseUrl },
            Success = false, Error = error, DurationMs = durationMs, Trace = trace,
            ArtifactDirectory = string.Empty
        };
}
