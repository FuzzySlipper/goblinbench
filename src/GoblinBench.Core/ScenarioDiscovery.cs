using System.Text.Json;
using System.Text.Json.Serialization;

namespace GoblinBench.Core;

/// <summary>
/// Discovers and loads scenario definitions from a suites directory.
/// </summary>
public static class ScenarioDiscovery
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    /// <summary>
    /// Discover all scenario JSON files under the given suites root.
    /// Scenarios are named <c>&lt;suite&gt;/&lt;scenario-id&gt;.json</c> or
    /// <c>&lt;suite&gt;/&lt;scenario-id&gt;/scenario.json</c>.
    /// </summary>
    public static async Task<IReadOnlyList<Scenario>> DiscoverAsync(
        string suitesRoot,
        CancellationToken ct = default)
    {
        if (!Directory.Exists(suitesRoot))
            return Array.Empty<Scenario>();

        var scenarios = new List<Scenario>();

        // Pattern 1: suites/<suite>/<scenario-id>.json
        foreach (var jsonFile in Directory.EnumerateFiles(suitesRoot, "*.json", SearchOption.AllDirectories))
        {
            if (Path.GetFileName(jsonFile).Equals("scenario.json", StringComparison.OrdinalIgnoreCase))
                continue; // handled by pattern 2

            ct.ThrowIfCancellationRequested();
            var scenario = await LoadScenarioAsync(jsonFile, ct);
            if (scenario != null)
                scenarios.Add(scenario);
        }

        // Pattern 2: suites/<suite>/<scenario-id>/scenario.json
        foreach (var dir in Directory.EnumerateDirectories(suitesRoot, "*", SearchOption.AllDirectories))
        {
            var scenarioFile = Path.Combine(dir, "scenario.json");
            if (!File.Exists(scenarioFile))
                continue;

            // Avoid double-loading if we already loaded it via pattern 1
            if (scenarios.Any(s =>
                    string.Equals(s.Id, Path.GetFileName(dir), StringComparison.OrdinalIgnoreCase)))
                continue;

            ct.ThrowIfCancellationRequested();
            var scenario = await LoadScenarioAsync(scenarioFile, ct);
            if (scenario != null)
                scenarios.Add(scenario);
        }

        return scenarios;
    }

    private static async Task<Scenario?> LoadScenarioAsync(
        string path, CancellationToken ct)
    {
        try
        {
            var json = await File.ReadAllTextAsync(path, ct);
            var scenario = JsonSerializer.Deserialize<Scenario>(json, JsonOptions);
            if (scenario == null)
                return null;

            // Auto-derive suite from directory path if not set
            if (string.IsNullOrEmpty(scenario.Suite))
            {
                var dir = Path.GetDirectoryName(path);
                if (dir != null)
                {
                    var suitesIndex = dir.LastIndexOf(
                        "suites", StringComparison.OrdinalIgnoreCase);
                    if (suitesIndex >= 0)
                    {
                        var relative = dir[(suitesIndex + "suites".Length)..]
                            .TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                        scenario = scenario with { Suite = relative };
                    }
                }
            }

            // Auto-derive id from filename if not set
            if (string.IsNullOrEmpty(scenario.Id))
            {
                var fileName = Path.GetFileNameWithoutExtension(path);
                if (string.Equals(fileName, "scenario", StringComparison.OrdinalIgnoreCase))
                    fileName = Path.GetFileName(Path.GetDirectoryName(path) ?? fileName);
                scenario = scenario with { Id = fileName };
            }

            return scenario;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            // Log and skip malformed scenarios
            Console.Error.WriteLine($"Warning: failed to load scenario '{path}': {ex.Message}");
            return null;
        }
    }
}
