using System.Diagnostics;
using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// Candidate runner that invokes a Hermes profile via the hermes CLI.
/// Uses <c>hermes chat -q -p &lt;profile&gt;</c> (non-interactive).
/// Records latency, raw output, and errors.
/// </summary>
public sealed class HermesProfileRunner : ICandidateRunner
{
    public string Name => "hermes-profile";

    public bool CanHandle(CandidateConfig candidate) =>
        candidate.Kind == CandidateKind.HermesProfile;

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;
        var stopwatch = Stopwatch.StartNew();
        var profile = candidate.Profile ?? "default";

        var trace = new List<TraceEvent>
        {
            new() { Timestamp = DateTime.UtcNow, Event = "hermes.runner.started",
                Data = new { profile } }
        };

        // Build the prompt from scenario input
        var prompt = BuildPrompt(scenario);

        try
        {
            // Resolve hermes CLI path
            var hermesPath = ResolveHermesPath();

            var psi = new ProcessStartInfo
            {
                FileName = hermesPath,
                Arguments = $"chat -q -p {EscapeArg(profile)} {EscapeArg(prompt)}",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            trace.Add(new()
            {
                Timestamp = DateTime.UtcNow,
                Event = "hermes.process.starting",
                Data = new { command = $"{hermesPath} chat -q -p {profile}" }
            });

            using var process = new Process { StartInfo = psi };
            process.Start();

            var outputTask = process.StandardOutput.ReadToEndAsync(ct);
            var errorTask = process.StandardError.ReadToEndAsync(ct);

            await process.WaitForExitAsync(ct);
            stopwatch.Stop();

            var stdout = await outputTask;
            var stderr = await errorTask;

            trace.Add(new()
            {
                Timestamp = DateTime.UtcNow,
                Event = "hermes.process.exited",
                Data = new { exit_code = process.ExitCode, output_length = stdout.Length }
            });

            var success = process.ExitCode == 0;
            var error = success ? null : $"Exit code {process.ExitCode}: {stderr[..Math.Min(stderr.Length, 500)]}";

            // Build model identity for a profile-based candidate
            var modelIdentity = new ModelIdentity
            {
                Model = candidate.Model,
                Provider = candidate.Provider ?? "hermes",
                DisplayName = $"hermes:{profile}"
            };

            // Write artifacts
            await WriteArtifactsAsync(candidate, context, stdout, stderr, ct);

            return new CandidateResult
            {
                CandidateId = candidate.Id,
                CandidateName = candidate.Name,
                CandidateKind = candidate.Kind,
                ModelIdentity = modelIdentity,
                Success = success,
                Error = error,
                DurationMs = stopwatch.ElapsedMilliseconds,
                RawResponse = stdout,
                Output = new { profile, exit_code = process.ExitCode, status = success ? "ok" : "error" },
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
                Error = "Hermes invocation timed out or was cancelled.",
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

    private static string BuildPrompt(Scenario scenario)
    {
        if (scenario.Input.TryGetValue("prompt", out var prompt) && prompt is string promptStr)
            return promptStr;

        if (scenario.Input.TryGetValue("message", out var msg) && msg is string msgStr)
            return msgStr;

        var json = JsonSerializer.Serialize(scenario.Input);
        return json;
    }

    private static string ResolveHermesPath()
    {
        // Check common locations
        var candidates = new[]
        {
            "/usr/local/bin/hermes",
            "/home/agent/.local/bin/hermes",
            "/opt/hermes/hermes"
        };

        foreach (var c in candidates)
            if (File.Exists(c))
                return c;

        return "hermes"; // fallback to PATH lookup
    }

    private static string EscapeArg(string arg)
    {
        // Simple shell escaping: wrap in quotes if it contains spaces
        if (arg.Contains(' ') || arg.Contains('"'))
            return $"\"{arg.Replace("\"", "\\\"")}\"";
        return arg;
    }

    private async Task WriteArtifactsAsync(
        CandidateConfig candidate,
        RunContext context,
        string stdout,
        string stderr,
        CancellationToken ct)
    {
        var outputPath = context.GetCandidateOutputPath(candidate.Id);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        await File.WriteAllTextAsync(outputPath, stdout, ct);

        if (!string.IsNullOrEmpty(stderr))
        {
            var artifactDir = context.GetCandidateArtifactsDirectory(candidate.Id);
            Directory.CreateDirectory(artifactDir);
            await File.WriteAllTextAsync(Path.Combine(artifactDir, "stderr.txt"), stderr, ct);
        }
    }
}
