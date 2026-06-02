using System.Diagnostics;
using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// Candidate runner for external agent CLIs (Codex, Claude Code, OpenCode).
/// Executes the CLI command with scenario input piped or passed as arguments,
/// captures stdout/stderr, and records latency, raw output, and errors.
/// </summary>
public sealed class ExternalCliRunner : ICandidateRunner
{
    public string Name => "external-cli";

    public bool CanHandle(CandidateConfig candidate) =>
        candidate.Kind == CandidateKind.ExternalCli;

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;
        var stopwatch = Stopwatch.StartNew();

        var command = candidate.CliCommand;
        if (string.IsNullOrEmpty(command))
        {
            return new CandidateResult
            {
                CandidateId = candidate.Id,
                CandidateName = candidate.Name,
                CandidateKind = candidate.Kind,
                Success = false,
                Error = "No CLI command configured for external-cli candidate."
            };
        }

        var trace = new List<TraceEvent>
        {
            new() { Timestamp = DateTime.UtcNow, Event = "cli.runner.started",
                Data = new { command, args = candidate.CliArgs } }
        };

        // Build the prompt from scenario input
        var prompt = BuildPrompt(scenario);

        try
        {
            // Build arguments, appending the prompt as the last argument
            var args = new List<string>(candidate.CliArgs);
            args.Add(prompt);

            var psi = new ProcessStartInfo
            {
                FileName = command,
                Arguments = string.Join(" ", args.Select(EscapeArg)),
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            // Set working directory if specified
            if (candidate.Config.TryGetValue("workdir", out var wd) && wd is string workDir)
                psi.WorkingDirectory = workDir;

            // Set environment variables from config
            if (candidate.Config.TryGetValue("env", out var envObj) &&
                envObj is JsonElement envEl && envEl.ValueKind == JsonValueKind.Object)
            {
                foreach (var kvp in envEl.EnumerateObject())
                {
                    psi.Environment[kvp.Name] = kvp.Value.GetString() ?? string.Empty;
                }
            }

            trace.Add(new()
            {
                Timestamp = DateTime.UtcNow,
                Event = "cli.process.starting",
                Data = new { command, args = args }
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
                Event = "cli.process.exited",
                Data = new { exit_code = process.ExitCode, output_length = stdout.Length }
            });

            var success = process.ExitCode == 0;
            var error = success
                ? null
                : $"Exit code {process.ExitCode}: {stderr[..Math.Min(stderr.Length, 500)]}";

            var modelIdentity = new ModelIdentity
            {
                Model = command,
                Provider = candidate.Provider ?? "external-cli",
                DisplayName = $"cli:{command}"
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
                Output = new { command, exit_code = process.ExitCode, status = success ? "ok" : "error" },
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
                Error = "CLI execution timed out or was cancelled.",
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

        return JsonSerializer.Serialize(scenario.Input);
    }

    private static string EscapeArg(string arg)
    {
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
