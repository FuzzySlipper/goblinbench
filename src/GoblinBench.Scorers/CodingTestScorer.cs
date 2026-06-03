using System.Diagnostics;
using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Scorers;

/// <summary>
/// Scores a coding candidate by running the fixture's test suite and scanning
/// source files for unfinished-work markers.
///
/// Requires <c>CandidateResult.Output["fixture_dir"]</c> (set by CodingCandidateRunner).
///
/// Scoring weights: visible tests 50%, strict tests 40%, no markers 10%.
/// Default pass threshold: 0.8.
///
/// Parameters (from scenario scoring config):
/// - <c>test_project</c>: path to .csproj relative to fixture_dir (default: first *.csproj found)
/// - <c>visible_filter</c>: dotnet test --filter value (default: "FullyQualifiedName~Tests.Visible")
/// - <c>strict_filter</c>: dotnet test --filter value (default: "FullyQualifiedName~Tests.Strict")
/// - <c>scan_dir</c>: subdirectory to scan for markers, relative to fixture_dir (default: "src")
/// - <c>timeout_seconds</c>: per-suite timeout (default: 120)
/// </summary>
public sealed class CodingTestScorer : IScorer
{
    private static readonly string[] DefaultMarkers =
        ["TODO", "FIXME", "HACK", "NotImplementedException", "throw new NotImplementedException"];

    public string Id => "coding-tests";
    public string Name => "Coding Test Scorer";

    public async Task<ScoreResult> ScoreAsync(
        Scenario scenario,
        CandidateConfig candidate,
        CandidateResult candidateResult,
        RunContext context,
        CancellationToken ct = default)
    {
        var parameters = GetParameters(scenario);
        var timeoutSec = GetIntParam(parameters, "timeout_seconds") ?? 120;
        var visibleFilter = GetStringParam(parameters, "visible_filter")
            ?? "FullyQualifiedName~Tests.Visible";
        var strictFilter = GetStringParam(parameters, "strict_filter")
            ?? "FullyQualifiedName~Tests.Strict";
        var scanDir = GetStringParam(parameters, "scan_dir") ?? "src";

        var fixtureDir = ExtractFixtureDir(candidateResult);
        if (fixtureDir == null)
        {
            return Fail("fixture_dir not found in candidate output — CodingCandidateRunner must run first.");
        }

        if (!Directory.Exists(fixtureDir))
        {
            return Fail($"Fixture directory does not exist: {fixtureDir}");
        }

        // Locate test project
        var testProjectOverride = GetStringParam(parameters, "test_project");
        var testProject = testProjectOverride != null
            ? Path.Combine(fixtureDir, testProjectOverride)
            : FindTestProject(fixtureDir);

        if (testProject == null)
        {
            return Fail("No .csproj file found in fixture directory.");
        }

        // Declare artifactDir early (needed for build failure log)
        var artifactDir = context.GetCandidateArtifactsDirectory(candidate.Id);
        Directory.CreateDirectory(artifactDir);

        // Restore and build fixture — needed when fixture was freshly copied into a temp dir
        var (buildOk, buildLog) = await BuildOnceAsync(fixtureDir, testProject, timeoutSec, ct);
        if (!buildOk)
        {
            await File.WriteAllTextAsync(Path.Combine(artifactDir, "coding-build.log"), buildLog, ct);
            return new ScoreResult
            {
                ScorerId = Id, ScorerName = Name, ScoringKind = "command",
                Success = false, Score = 0.0, Passed = false,
                Error = "Fixture build failed — check coding-build.log in artifacts.",
                HumanSummary = "FAIL: coding-tests: fixture build failed",
                Detail = new Dictionary<string, object?> { ["build_log"] = buildLog[..Math.Min(buildLog.Length, 500)] }
            };
        }

        // Run visible and strict test suites
        var (visiblePass, visibleTotal, visibleLog) = await RunTestsAsync(
            fixtureDir, testProject, visibleFilter, timeoutSec, ct);
        var (strictPass, strictTotal, strictLog) = await RunTestsAsync(
            fixtureDir, testProject, strictFilter, timeoutSec, ct);

        // Scan source files for unfinished markers
        var markers = ScanForMarkers(Path.Combine(fixtureDir, scanDir));

        var visibleOk = visibleTotal > 0 && visiblePass == visibleTotal;
        var strictOk = strictTotal > 0 && strictPass == strictTotal;
        var markersOk = markers.Count == 0;

        var score =
            0.50 * (visibleOk ? 1.0 : visibleTotal > 0 ? (double)visiblePass / visibleTotal : 0.0) +
            0.40 * (strictOk ? 1.0 : strictTotal > 0 ? (double)strictPass / strictTotal : 0.0) +
            0.10 * (markersOk ? 1.0 : 0.0);

        var threshold = GetThreshold(scenario, 0.8);
        var passed = score >= threshold;

        var summary = passed
            ? $"PASS: visible {visiblePass}/{visibleTotal}, strict {strictPass}/{strictTotal}, markers {markers.Count} ({score:F2})"
            : $"FAIL: visible {visiblePass}/{visibleTotal}, strict {strictPass}/{strictTotal}, markers {markers.Count} ({score:F2})";

        // Write test logs to artifacts
        await File.WriteAllTextAsync(Path.Combine(artifactDir, "coding-visible-tests.log"), visibleLog, ct);
        await File.WriteAllTextAsync(Path.Combine(artifactDir, "coding-strict-tests.log"), strictLog, ct);
        if (markers.Count > 0)
            await File.WriteAllTextAsync(Path.Combine(artifactDir, "coding-markers.txt"),
                string.Join(Environment.NewLine, markers), ct);

        return new ScoreResult
        {
            ScorerId = Id, ScorerName = Name, ScoringKind = "command",
            Success = true, Score = score, Passed = passed,
            HumanSummary = summary,
            Explanation = BuildExplanation(visiblePass, visibleTotal, strictPass, strictTotal, markers),
            Detail = new Dictionary<string, object?>
            {
                ["visible_pass"] = visiblePass, ["visible_total"] = visibleTotal,
                ["strict_pass"] = strictPass, ["strict_total"] = strictTotal,
                ["marker_count"] = markers.Count, ["markers"] = markers,
                ["fixture_dir"] = fixtureDir
            }
        };
    }

    private static async Task<(bool ok, string log)> BuildOnceAsync(
        string workingDir, string testProject, int timeoutSec, CancellationToken ct)
    {
        var sb = new System.Text.StringBuilder();

        // Step 1: restore (--force ensures packages are re-evaluated for the new working path)
        var (restoreOk, restoreOut) = await RunCommandAsync(
            workingDir, "dotnet", ["restore", testProject, "--force"], timeoutSec, ct);
        sb.AppendLine("=== restore ===").AppendLine(restoreOut);
        if (!restoreOk) return (false, sb.ToString());

        // Step 2: build
        var (buildOk, buildOut) = await RunCommandAsync(
            workingDir, "dotnet", ["build", testProject, "-v", "quiet"], timeoutSec, ct);
        sb.AppendLine("=== build ===").AppendLine(buildOut);
        return (buildOk, sb.ToString());
    }

    private static async Task<(bool ok, string output)> RunCommandAsync(
        string workingDir, string executable, IEnumerable<string> arguments,
        int timeoutSec, CancellationToken ct)
    {
        var psi = new ProcessStartInfo
        {
            FileName = executable,
            WorkingDirectory = workingDir,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };
        foreach (var arg in arguments) psi.ArgumentList.Add(arg);

        try
        {
            using var proc = new Process { StartInfo = psi };
            proc.Start();
            var outTask = proc.StandardOutput.ReadToEndAsync(ct);
            var errTask = proc.StandardError.ReadToEndAsync(ct);
            using var tCts = new CancellationTokenSource(TimeSpan.FromSeconds(timeoutSec));
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(ct, tCts.Token);
            await proc.WaitForExitAsync(linked.Token);
            var output = string.Join(Environment.NewLine, new[] { await outTask, await errTask }
                .Where(s => !string.IsNullOrEmpty(s)));
            return (proc.ExitCode == 0, output);
        }
        catch (Exception ex)
        {
            return (false, ex.Message);
        }
    }

    private static async Task<(int passed, int total, string log)> RunTestsAsync(
        string workingDir, string testProject, string filter, int timeoutSec, CancellationToken ct)
    {
        var psi = new ProcessStartInfo
        {
            FileName = "dotnet",
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = workingDir
        };
        psi.ArgumentList.Add("test");
        psi.ArgumentList.Add(testProject);
        psi.ArgumentList.Add("--filter");
        psi.ArgumentList.Add(filter);
        psi.ArgumentList.Add("--no-build");
        psi.ArgumentList.Add("-v");
        psi.ArgumentList.Add("quiet");

        try
        {
            using var process = new Process { StartInfo = psi };
            process.Start();

            var outTask = process.StandardOutput.ReadToEndAsync(ct);
            var errTask = process.StandardError.ReadToEndAsync(ct);

            using var timeoutCts = new CancellationTokenSource(TimeSpan.FromSeconds(timeoutSec));
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(ct, timeoutCts.Token);
            await process.WaitForExitAsync(linked.Token);

            var stdout = await outTask;
            var stderr = await errTask;
            var log = string.Join(Environment.NewLine, new[] { stdout, stderr }
                .Where(s => !string.IsNullOrEmpty(s)));

            var (passed, total) = ParseTestCounts(stdout + stderr);
            return (passed, total, log);
        }
        catch (OperationCanceledException)
        {
            return (0, 0, $"Test run timed out after {timeoutSec}s");
        }
        catch (Exception ex)
        {
            return (0, 0, $"Test run error: {ex.Message}");
        }
    }

    private static (int passed, int total) ParseTestCounts(string output)
    {
        // dotnet test summary: "Passed! - Failed: 0, Passed: 4, Skipped: 0, Total: 4"
        // or                   "Failed! - Failed: 2, Passed: 1, Skipped: 0, Total: 3"
        foreach (var line in output.Split('\n'))
        {
            if (!line.Contains("Total:")) continue;

            var passed = ExtractCount(line, "Passed:");
            var total = ExtractCount(line, "Total:");
            if (total > 0) return (passed, total);
        }
        return (0, 0);
    }

    private static int ExtractCount(string line, string prefix)
    {
        var idx = line.IndexOf(prefix, StringComparison.OrdinalIgnoreCase);
        if (idx < 0) return 0;
        var rest = line[(idx + prefix.Length)..].TrimStart();
        var end = 0;
        while (end < rest.Length && char.IsDigit(rest[end])) end++;
        return end > 0 ? int.Parse(rest[..end]) : 0;
    }

    private static List<string> ScanForMarkers(string sourceDir)
    {
        var findings = new List<string>();
        if (!Directory.Exists(sourceDir)) return findings;

        foreach (var file in Directory.EnumerateFiles(sourceDir, "*.cs", SearchOption.AllDirectories))
        {
            var lines = File.ReadAllLines(file);
            for (var i = 0; i < lines.Length; i++)
            {
                foreach (var marker in DefaultMarkers)
                {
                    if (lines[i].Contains(marker, StringComparison.OrdinalIgnoreCase))
                    {
                        var rel = Path.GetRelativePath(sourceDir, file);
                        findings.Add($"{rel}:{i + 1}: {lines[i].Trim()}");
                        break;
                    }
                }
            }
        }
        return findings;
    }

    private static string? FindTestProject(string fixtureDir)
    {
        // Prefer a .csproj that contains "test" in the name
        var allProjects = Directory.EnumerateFiles(fixtureDir, "*.csproj", SearchOption.TopDirectoryOnly)
            .ToList();
        return allProjects.FirstOrDefault(p =>
            Path.GetFileNameWithoutExtension(p).Contains("test", StringComparison.OrdinalIgnoreCase))
            ?? allProjects.FirstOrDefault();
    }

    private static string? ExtractFixtureDir(CandidateResult result)
    {
        var source = result.Output;
        if (source == null) return null;

        if (source is JsonElement je && je.ValueKind == JsonValueKind.Object)
        {
            if (je.TryGetProperty("fixture_dir", out var fd) && fd.ValueKind == JsonValueKind.String)
                return fd.GetString();
        }

        try
        {
            var json = JsonSerializer.Serialize(source);
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.TryGetProperty("fixture_dir", out var fd2)
                && fd2.ValueKind == JsonValueKind.String)
                return fd2.GetString();
        }
        catch { }

        return null;
    }

    private static string BuildExplanation(int vp, int vt, int sp, int st, List<string> markers)
    {
        var parts = new List<string>();
        if (vt == 0) parts.Add("no visible tests found");
        else if (vp < vt) parts.Add($"{vt - vp} visible test(s) failed");
        if (st == 0) parts.Add("no strict tests found");
        else if (sp < st) parts.Add($"{st - sp} strict test(s) failed");
        if (markers.Count > 0) parts.Add($"{markers.Count} unfinished-work marker(s) found");
        return parts.Count > 0 ? string.Join("; ", parts) : "All checks passed.";
    }

    private ScoreResult Fail(string error) => new()
    {
        ScorerId = Id, ScorerName = Name, ScoringKind = "command",
        Success = false, Score = 0.0, Passed = false,
        Error = error, HumanSummary = $"FAIL: coding-tests: {error[..Math.Min(error.Length, 80)]}"
    };

    private static string? GetStringParam(Dictionary<string, object?> p, string key)
    {
        if (!p.TryGetValue(key, out var v) || v == null) return null;
        if (v is string s) return s;
        if (v is JsonElement je && je.ValueKind == JsonValueKind.String) return je.GetString();
        return null;
    }

    private static int? GetIntParam(Dictionary<string, object?> p, string key)
    {
        if (!p.TryGetValue(key, out var v) || v == null) return null;
        if (v is int i) return i;
        if (v is JsonElement je && je.ValueKind == JsonValueKind.Number) return je.GetInt32();
        return null;
    }

    private double GetThreshold(Scenario scenario, double def) =>
        scenario.Scoring?.Thresholds.TryGetValue(Id, out var th) == true ? th : def;

    private Dictionary<string, object?> GetParameters(Scenario scenario) =>
        scenario.Scoring?.Parameters.TryGetValue(Id, out var p) == true ? p : new();
}
