using System.Diagnostics;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// Candidate runner for Den capability service endpoints.
/// Sends an HTTP POST with scenario input and records latency, raw response,
/// parsed response, and errors.
/// </summary>
public sealed class ServiceEndpointRunner : ICandidateRunner
{
    private readonly HttpClient _httpClient;

    public string Name => "service-endpoint";

    public ServiceEndpointRunner(HttpClient? httpClient = null)
    {
        _httpClient = httpClient ?? new HttpClient();
    }

    public bool CanHandle(CandidateConfig candidate) =>
        candidate.Kind == CandidateKind.ServiceEndpoint;

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;
        var stopwatch = Stopwatch.StartNew();

        var endpoint = candidate.Endpoint ?? candidate.BaseUrl;
        if (string.IsNullOrEmpty(endpoint))
        {
            return new CandidateResult
            {
                CandidateId = candidate.Id,
                CandidateName = candidate.Name,
                CandidateKind = candidate.Kind,
                Success = false,
                Error = "No endpoint configured for service-endpoint candidate."
            };
        }

        var trace = new List<TraceEvent>
        {
            new() { Timestamp = DateTime.UtcNow, Event = "service.request.built",
                Data = new { endpoint } }
        };

        try
        {
            // Build request body from scenario input
            var requestBody = BuildRequestBody(scenario, candidate);
            var requestJson = JsonSerializer.Serialize(requestBody);

            var request = new HttpRequestMessage(HttpMethod.Post, endpoint)
            {
                Content = new StringContent(requestJson, Encoding.UTF8, "application/json")
            };

            // Add auth header if configured
            var apiKey = ResolveServiceKey(candidate);
            if (!string.IsNullOrEmpty(apiKey))
            {
                request.Headers.TryAddWithoutValidation("X-API-Key", apiKey);
            }

            trace.Add(new()
            {
                Timestamp = DateTime.UtcNow,
                Event = "service.request.sent"
            });

            using var response = await _httpClient.SendAsync(request,
                HttpCompletionOption.ResponseHeadersRead, ct);

            var rawResponse = await response.Content.ReadAsStringAsync(ct);
            stopwatch.Stop();

            trace.Add(new()
            {
                Timestamp = DateTime.UtcNow,
                Event = "service.response.received",
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
                catch { /* raw stored, parsed may be null */ }
            }
            else
            {
                error = $"HTTP {(int)response.StatusCode}: {rawResponse[..Math.Min(rawResponse.Length, 500)]}";
            }

            var modelIdentity = new ModelIdentity
            {
                Model = candidate.Model,
                Provider = candidate.Provider ?? "den-service",
                BaseUrl = endpoint,
                DisplayName = candidate.Name
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
                Output = new { endpoint, status = response.IsSuccessStatusCode ? "ok" : "error" },
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
                Success = false,
                Error = "Service request timed out or was cancelled.",
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
                Success = false,
                Error = ex.Message,
                DurationMs = stopwatch.ElapsedMilliseconds,
                Trace = trace,
                ArtifactDirectory = context.GetCandidateArtifactsDirectory(candidate.Id)
            };
        }
    }

    private static object BuildRequestBody(Scenario scenario, CandidateConfig candidate)
    {
        // If scenario input has a "payload" key, use it directly
        if (scenario.Input.TryGetValue("payload", out var payload) && payload != null)
            return payload;

        // Otherwise wrap everything
        return new Dictionary<string, object?>
        {
            ["scenario_id"] = scenario.Id,
            ["scenario_version"] = scenario.Version,
            ["input"] = scenario.Input
        };
    }

    private static string? ResolveServiceKey(CandidateConfig candidate)
    {
        if (!string.IsNullOrEmpty(candidate.ApiKey))
            return candidate.ApiKey;
        if (!string.IsNullOrEmpty(candidate.ApiKeyEnv))
            return Environment.GetEnvironmentVariable(candidate.ApiKeyEnv);
        return Environment.GetEnvironmentVariable("GOBLINBENCH_SERVICE_API_KEY");
    }

    private async Task WriteArtifactsAsync(
        CandidateConfig candidate,
        RunContext context,
        string rawResponse,
        object? parsedResponse,
        string? error,
        CancellationToken ct)
    {
        var artifactDir = context.GetCandidateArtifactsDirectory(candidate.Id);
        Directory.CreateDirectory(artifactDir);

        var outputPath = context.GetCandidateOutputPath(candidate.Id);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        await File.WriteAllTextAsync(outputPath, rawResponse, ct);

        if (parsedResponse != null)
        {
            var parsedPath = Path.Combine(artifactDir, "parsed_response.json");
            await File.WriteAllTextAsync(parsedPath,
                JsonSerializer.Serialize(parsedResponse, new JsonSerializerOptions { WriteIndented = true }), ct);
        }

        if (!string.IsNullOrEmpty(error))
        {
            await File.WriteAllTextAsync(Path.Combine(artifactDir, "error.txt"), error, ct);
        }
    }
}
