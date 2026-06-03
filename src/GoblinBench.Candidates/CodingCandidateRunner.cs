using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// Candidate runner for coding evaluation tasks. Copies a named fixture from
/// <c>fixtures/coding/{fixture_case}/</c> into the run artifact directory, then
/// applies the candidate's changes before returning.
///
/// For deterministic smoke-testing, use <c>cli_command = "coding-scripted"</c>. The runner
/// reads <c>correct_patch.json</c> from the fixture directory and applies it, giving the
/// scorer a known-correct file state to validate against.
///
/// The fixture directory path is returned in <c>Output["fixture_dir"]</c> so scorers can
/// locate the modified files and run tests against them.
/// </summary>
public sealed class CodingCandidateRunner : ICandidateRunner
{
    public string Name => "coding";

    public bool CanHandle(CandidateConfig candidate) =>
        string.Equals(candidate.CliCommand, "coding-scripted", StringComparison.OrdinalIgnoreCase);

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;

        var fixtureCase = GetStringFromInput(scenario, "fixture_case");
        if (string.IsNullOrEmpty(fixtureCase))
        {
            return Failure(candidate, startedAt, "Scenario input missing 'fixture_case'.");
        }

        // Locate fixture source — prefer explicit RepoRoot if set (avoids brittle path walking)
        var repoRoot = context.RepoRoot ?? FindRepoRoot(context.RunsRoot);
        var fixtureSource = Path.Combine(repoRoot, "fixtures", "coding", fixtureCase);
        if (!Directory.Exists(fixtureSource))
        {
            return Failure(candidate, startedAt,
                $"Fixture directory not found: {fixtureSource}");
        }

        // Copy fixture into run artifact directory
        var fixtureDestination = Path.Combine(
            context.GetCandidateDirectory(candidate.Id), "fixture");
        CopyDirectory(fixtureSource, fixtureDestination);

        var trace = new List<TraceEvent>
        {
            new() { Timestamp = startedAt, Event = "coding.fixture.copied",
                Data = new { source = fixtureSource, destination = fixtureDestination } }
        };

        // Apply correct_patch.json for the scripted path
        var patchPath = Path.Combine(fixtureDestination, "correct_patch.json");
        if (File.Exists(patchPath))
        {
            try
            {
                var patchJson = await File.ReadAllTextAsync(patchPath, ct);
                var patch = JsonSerializer.Deserialize<Dictionary<string, string>>(patchJson);
                if (patch != null)
                {
                    foreach (var (relPath, content) in patch)
                    {
                        var targetPath = Path.Combine(fixtureDestination, relPath);
                        Directory.CreateDirectory(Path.GetDirectoryName(targetPath)!);
                        await File.WriteAllTextAsync(targetPath, content, ct);
                    }

                    trace.Add(new() { Timestamp = DateTime.UtcNow, Event = "coding.patch.applied",
                        Data = new { files_patched = patch.Count } });
                }
            }
            catch (Exception ex)
            {
                return Failure(candidate, startedAt, $"Failed to apply correct_patch.json: {ex.Message}");
            }
        }
        else
        {
            trace.Add(new() { Timestamp = DateTime.UtcNow, Event = "coding.patch.skipped",
                Data = new { reason = "no correct_patch.json in fixture" } });
        }

        var durationMs = (long)(DateTime.UtcNow - startedAt).TotalMilliseconds;

        return new CandidateResult
        {
            CandidateId = candidate.Id,
            CandidateName = candidate.Name,
            CandidateKind = candidate.Kind,
            ModelIdentity = new ModelIdentity
            {
                Model = "scripted-patch",
                Provider = "goblinbench",
                DisplayName = "Scripted Coding Runner (correct_patch.json)"
            },
            Success = true,
            DurationMs = durationMs,
            RawResponse = $"Applied correct_patch.json to fixture '{fixtureCase}'",
            Output = new Dictionary<string, object?>
            {
                ["fixture_dir"] = fixtureDestination,
                ["fixture_case"] = fixtureCase
            },
            Trace = trace,
            ArtifactDirectory = context.GetCandidateArtifactsDirectory(candidate.Id)
        };
    }

    private static readonly HashSet<string> SkipDirs =
        new(StringComparer.OrdinalIgnoreCase) { "obj", "bin", ".git", ".vs" };

    private static void CopyDirectory(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (var file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories))
        {
            var relative = Path.GetRelativePath(source, file);
            // Skip build artifact directories — the runner will restore/build from scratch
            var segments = relative.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (segments.Any(s => SkipDirs.Contains(s))) continue;

            var destFile = Path.Combine(destination, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(destFile)!);
            File.Copy(file, destFile, overwrite: true);
        }
    }

    private static string GetStringFromInput(Scenario scenario, string key)
    {
        if (!scenario.Input.TryGetValue(key, out var v) || v == null) return string.Empty;
        if (v is string s) return s;
        if (v is JsonElement je && je.ValueKind == JsonValueKind.String) return je.GetString() ?? string.Empty;
        return v.ToString() ?? string.Empty;
    }

    private static string FindRepoRoot(string runsRoot)
    {
        var dir = Path.GetDirectoryName(runsRoot) ?? runsRoot;
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir, "suites")) &&
                Directory.Exists(Path.Combine(dir, "src")))
                return dir;
            var parent = Path.GetDirectoryName(dir);
            if (parent == dir) break;
            dir = parent;
        }
        return Path.GetDirectoryName(runsRoot) ?? runsRoot;
    }

    private static CandidateResult Failure(CandidateConfig candidate, DateTime startedAt, string error) =>
        new()
        {
            CandidateId = candidate.Id, CandidateName = candidate.Name,
            CandidateKind = candidate.Kind, Success = false, Error = error,
            DurationMs = (long)(DateTime.UtcNow - startedAt).TotalMilliseconds
        };
}
