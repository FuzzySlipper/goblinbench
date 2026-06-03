using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// Candidate runner for Electron GUI harness scenarios.
/// Activated by <c>cli_command = "playwright-electron"</c>.
///
/// Executes the <c>input.flow</c> step sequence using the Playwright Electron API.
/// Steps requiring FlaUI/UIA or Windows-MCP on non-Windows hosts are skipped and
/// recorded in the flow log with a platform note.
///
/// For deterministic smoke-testing on Linux, use <c>scripted_response</c> in the
/// scenario input — the runner returns it directly without launching Electron.
///
/// Current state: the Playwright execution path is stubbed; the scripted path
/// and step-logging contract are complete. The live Playwright path requires
/// Node.js + the fixture's npm dependencies installed at scenario time.
/// </summary>
public sealed class ElectronCandidateRunner : ICandidateRunner
{
    public string Name => "playwright-electron";

    public bool CanHandle(CandidateConfig candidate) =>
        string.Equals(candidate.CliCommand, "playwright-electron", StringComparison.OrdinalIgnoreCase);

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;

        // Scripted path: return canned response for smoke testing
        if (scenario.Input.TryGetValue("scripted_response", out var scriptedObj) && scriptedObj != null)
        {
            await Task.Delay(1, ct);
            return BuildScriptedResult(candidate, startedAt, scriptedObj, scenario, context);
        }

        // Determine required layers and platform availability
        var requiredLayers = GetStringList(scenario.Input, "layers");
        var platformNotes = new List<string>();
        var skippedSteps = new List<string>();

        if (requiredLayers.Contains("flaui") && !OperatingSystem.IsWindows())
        {
            platformNotes.Add("flaui layer skipped (not Windows)");
            skippedSteps.Add("flaui");
        }
        if (requiredLayers.Contains("windows-mcp") && !OperatingSystem.IsWindows())
        {
            platformNotes.Add("windows-mcp layer skipped (not Windows)");
            skippedSteps.Add("windows-mcp");
        }

        // Playwright path (stub — returns platform report without launching)
        // TODO: implement via `npx playwright` subprocess invocation with the
        // fixture's goblinbench-launcher.json as the launch config.
        var steps = GetObjectList(scenario.Input, "flow");
        var stepLog = steps.Select((s, i) =>
        {
            var stepType = GetString(s, "step");
            var layer = GetString(s, "layer");
            var isSkipped = layer != null && skippedSteps.Contains(layer);
            return new Dictionary<string, object?>
            {
                ["index"] = i,
                ["step"] = stepType,
                ["layer"] = layer,
                ["status"] = isSkipped ? "skipped" : "stub",
                ["note"] = isSkipped
                    ? $"{layer} not available on this host"
                    : "Playwright execution not yet implemented — use scripted_response for smoke tests"
            };
        }).ToList();

        var durationMs = (long)(DateTime.UtcNow - startedAt).TotalMilliseconds;
        var artifactDir = context.GetCandidateArtifactsDirectory(candidate.Id);

        var output = new Dictionary<string, object?>
        {
            ["steps_completed"] = 0,
            ["steps_skipped"] = skippedSteps.Count,
            ["steps_stubbed"] = steps.Count - skippedSteps.Count,
            ["final_state"] = "stub",
            ["platform_notes"] = platformNotes,
            ["step_log"] = stepLog
        };

        await WriteFlowLogAsync(context, candidate.Id, stepLog, ct);

        return new CandidateResult
        {
            CandidateId = candidate.Id,
            CandidateName = candidate.Name,
            CandidateKind = candidate.Kind,
            ModelIdentity = new ModelIdentity
            {
                Model = "playwright-electron",
                Provider = "goblinbench",
                DisplayName = "Playwright Electron Runner (stub)"
            },
            Success = true,
            DurationMs = durationMs,
            RawResponse = JsonSerializer.Serialize(output, new JsonSerializerOptions { WriteIndented = true }),
            Output = output,
            Trace = new List<TraceEvent>
            {
                new() { Timestamp = startedAt, Event = "electron.runner.started",
                    Data = new { layers = requiredLayers, platform = OperatingSystem.IsWindows() ? "windows" : "linux" } },
                new() { Timestamp = DateTime.UtcNow, Event = "electron.runner.completed",
                    Data = new { platform_notes = platformNotes } }
            },
            ArtifactDirectory = artifactDir
        };
    }

    private static CandidateResult BuildScriptedResult(
        CandidateConfig candidate, DateTime startedAt, object scriptedObj,
        Scenario scenario, RunContext context)
    {
        string rawResponse;
        JsonElement? parsed = null;

        if (scriptedObj is JsonElement je)
        {
            rawResponse = je.GetRawText();
            if (je.ValueKind == JsonValueKind.Object) parsed = je;
        }
        else
        {
            rawResponse = JsonSerializer.Serialize(scriptedObj);
            try
            {
                var el = JsonSerializer.Deserialize<JsonElement>(rawResponse);
                if (el.ValueKind == JsonValueKind.Object) parsed = el;
            }
            catch { }
        }

        return new CandidateResult
        {
            CandidateId = candidate.Id,
            CandidateName = candidate.Name,
            CandidateKind = candidate.Kind,
            ModelIdentity = new ModelIdentity
            {
                Model = "scripted",
                Provider = "goblinbench",
                DisplayName = "Scripted Electron Runner"
            },
            Success = true,
            DurationMs = (long)(DateTime.UtcNow - startedAt).TotalMilliseconds,
            RawResponse = rawResponse,
            ParsedResponse = parsed.HasValue ? (object)parsed.Value : null,
            Output = parsed.HasValue ? (object)parsed.Value : null,
            Trace = new List<TraceEvent>
            {
                new() { Timestamp = startedAt, Event = "electron.scripted.started" },
                new() { Timestamp = DateTime.UtcNow, Event = "electron.scripted.completed" }
            },
            ArtifactDirectory = context.GetCandidateArtifactsDirectory(candidate.Id)
        };
    }

    private static async Task WriteFlowLogAsync(
        RunContext context, string candidateId,
        List<Dictionary<string, object?>> stepLog, CancellationToken ct)
    {
        var dir = context.GetCandidateDirectory(candidateId);
        Directory.CreateDirectory(dir);
        var logPath = Path.Combine(dir, "flow-log.jsonl");
        var lines = stepLog.Select(s => JsonSerializer.Serialize(s));
        await File.WriteAllTextAsync(logPath, string.Join(Environment.NewLine, lines) + Environment.NewLine, ct);
    }

    private static List<string> GetStringList(Dictionary<string, object?> input, string key)
    {
        if (!input.TryGetValue(key, out var v) || v == null) return new();
        if (v is JsonElement je && je.ValueKind == JsonValueKind.Array)
            return je.EnumerateArray()
                .Where(e => e.ValueKind == JsonValueKind.String)
                .Select(e => e.GetString()!)
                .ToList();
        return new();
    }

    private static List<JsonElement> GetObjectList(Dictionary<string, object?> input, string key)
    {
        if (!input.TryGetValue(key, out var v) || v == null) return new();
        if (v is JsonElement je && je.ValueKind == JsonValueKind.Array)
            return je.EnumerateArray().ToList();
        return new();
    }

    private static string? GetString(JsonElement obj, string key)
    {
        if (obj.TryGetProperty(key, out var prop) && prop.ValueKind == JsonValueKind.String)
            return prop.GetString();
        return null;
    }
}
