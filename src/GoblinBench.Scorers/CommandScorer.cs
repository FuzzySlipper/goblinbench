using System.Diagnostics;
using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Scorer that runs a deterministic shell command and checks its exit code
/// and/or stdout against expected values. Useful for running .NET tests,
/// linters, or any deterministic verification tool.
/// </summary>
public sealed class CommandScorer : IScorer
{
    public string Id => "command";
    public string Name => "Command / Test Scorer";

    public async Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var parameters = GetParams(scenario);

        if (!parameters.TryGetValue("command", out var cmdObj))
        {
            return new ScoreResult
            {
                ScorerId = Id,
                ScorerName = Name,
                ScoringKind = "command",
                Success = false,
                Error = "No 'command' configured for command scorer.",
                HumanSummary = "FAIL: command: no command configured"
            };
        }

        string command;
        if (cmdObj is string cmdStr)
        {
            command = cmdStr;
        }
        else if (cmdObj is JsonElement cmdEl && cmdEl.ValueKind == JsonValueKind.String)
        {
            command = cmdEl.GetString()!;
        }
        else if (cmdObj is JsonElement cmdElObj && cmdElObj.ValueKind == JsonValueKind.Object &&
                 cmdElObj.TryGetProperty("command", out var innerCmd) &&
                 innerCmd.ValueKind == JsonValueKind.String)
        {
            command = innerCmd.GetString()!;
        }
        else if (cmdObj is Dictionary<string, object?> cmdDict &&
                 cmdDict.TryGetValue("command", out var dictCmd) && dictCmd is string dictCmdStr)
        {
            command = dictCmdStr;
        }
        else
        {
            return new ScoreResult
            {
                ScorerId = Id,
                ScorerName = Name,
                ScoringKind = "command",
                Success = false,
                Error = "Invalid 'command' parameter — expected a string or object with 'command' field.",
                HumanSummary = "FAIL: command: invalid command parameter"
            };
        }

        // Substitute placeholders
        command = command
            .Replace("{run_dir}", context.RunDirectory)
            .Replace("{candidate_id}", candidate.Id)
            .Replace("{scenario_id}", scenario.Id);

        var workingDir = GetStringParam(parameters, "workdir") ?? context.RunDirectory;

        var timeoutSec = GetIntParam(parameters, "timeout_seconds") ?? 60;

        var expectExitCode = GetIntParam(parameters, "expect_exit_code") ?? 0;

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "/bin/bash",
                Arguments = $"-c {EscapeArg(command)}",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = workingDir
            };

            using var process = new Process { StartInfo = psi };
            process.Start();

            var outputTask = process.StandardOutput.ReadToEndAsync(ct);
            var errorTask = process.StandardError.ReadToEndAsync(ct);

            using var timeoutCts = new CancellationTokenSource(TimeSpan.FromSeconds(timeoutSec));
            using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(ct, timeoutCts.Token);

            await process.WaitForExitAsync(linkedCts.Token);

            var stdout = await outputTask;
            var stderr = await errorTask;

            // Write artifacts
            var artifactDir = context.GetCandidateArtifactsDirectory(candidate.Id);
            Directory.CreateDirectory(artifactDir);
            await File.WriteAllTextAsync(Path.Combine(artifactDir, $"scorer-command-stdout.txt"), stdout, ct);
            if (!string.IsNullOrEmpty(stderr))
                await File.WriteAllTextAsync(Path.Combine(artifactDir, $"scorer-command-stderr.txt"), stderr, ct);

            var exitOk = process.ExitCode == expectExitCode;

            // Check expected stdout if configured
            bool stdoutOk = true;
            string? stdoutExpected = GetStringParam(parameters, "expect_stdout_contains");
            if (stdoutExpected != null)
                stdoutOk = stdout.Contains(stdoutExpected, StringComparison.OrdinalIgnoreCase);

            var passed = exitOk && stdoutOk;
            var score = passed ? 1.0 : 0.0;
            var threshold = GetThreshold(scenario, 0.5);

            var reasons = new List<string>();
            if (!exitOk) reasons.Add($"exit code {process.ExitCode} != expected {expectExitCode}");
            if (!stdoutOk) reasons.Add($"stdout missing '{stdoutExpected}'");

            var summary = passed
                ? "PASS: command: exit code and output match (1.0)"
                : $"FAIL: command: {string.Join("; ", reasons)} (0.0)";

            if (!passed)
            {
                var failPath = Path.Combine(artifactDir, $"scorer-command-failure.txt");
                await File.WriteAllTextAsync(failPath,
                    $"Command: {command}\nExit code: {process.ExitCode} (expected {expectExitCode})\n" +
                    $"STDOUT:\n{stdout[..Math.Min(stdout.Length, 2000)]}\n\n" +
                    $"STDERR:\n{stderr[..Math.Min(stderr.Length, 2000)]}", ct);
            }

            return new ScoreResult
            {
                ScorerId = Id,
                ScorerName = Name,
                ScoringKind = "command",
                Success = true,
                Score = score,
                Passed = score >= threshold,
                Explanation = passed
                    ? $"Command '{command}' succeeded with expected exit code {expectExitCode}."
                    : $"Command '{command}' exited with code {process.ExitCode} (expected {expectExitCode}).",
                HumanSummary = summary,
                Detail = new Dictionary<string, object?>
                {
                    ["command"] = command,
                    ["exit_code"] = process.ExitCode,
                    ["expected_exit_code"] = expectExitCode,
                    ["stdout_length"] = stdout.Length,
                    ["stderr_length"] = stderr.Length,
                    ["exit_ok"] = exitOk,
                    ["stdout_ok"] = stdoutOk
                }
            };
        }
        catch (OperationCanceledException)
        {
            return new ScoreResult
            {
                ScorerId = Id,
                ScorerName = Name,
                ScoringKind = "command",
                Success = false,
                Error = $"Command timed out after {timeoutSec}s.",
                Score = 0.0,
                Passed = false,
                HumanSummary = $"FAIL: command: timed out after {timeoutSec}s"
            };
        }
        catch (Exception ex)
        {
            return new ScoreResult
            {
                ScorerId = Id,
                ScorerName = Name,
                ScoringKind = "command",
                Success = false,
                Error = ex.Message,
                Score = 0.0,
                Passed = false,
                HumanSummary = $"FAIL: command: error '{ex.Message[..Math.Min(ex.Message.Length, 80)]}'"
            };
        }
    }

    private static string EscapeArg(string arg)
    {
        return arg.Replace("\"", "\\\"");
    }

    private static string? GetStringParam(Dictionary<string, object?> parameters, string key)
    {
        if (!parameters.TryGetValue(key, out var val))
            return null;

        if (val is string s) return s;
        if (val is JsonElement je && je.ValueKind == JsonValueKind.String) return je.GetString();
        return null;
    }

    private static int? GetIntParam(Dictionary<string, object?> parameters, string key)
    {
        if (!parameters.TryGetValue(key, out var val))
            return null;

        if (val is int i) return i;
        if (val is long l) return (int)l;
        if (val is JsonElement je && je.ValueKind == JsonValueKind.Number)
        {
            if (je.TryGetInt32(out var i32)) return i32;
            return (int)je.GetInt64();
        }
        return null;
    }

    private Dictionary<string, object?> GetParams(Scenario scenario) =>
        scenario.Scoring?.Parameters.GetValueOrDefault(Id) ?? new();

    private double GetThreshold(Scenario scenario, double defaultThreshold) =>
        scenario.Scoring?.Thresholds.GetValueOrDefault(Id, defaultThreshold) ?? defaultThreshold;
}
