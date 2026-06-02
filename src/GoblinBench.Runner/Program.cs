using System.Text.Json;
using GoblinBench.Candidates;
using GoblinBench.Core;
using GoblinBench.Scorers;

namespace GoblinBench.Runner;

/// <summary>
/// GoblinBench CLI — discovers and executes benchmark scenarios
/// against one or more candidates.
/// </summary>
public static class Program
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    public static async Task<int> Main(string[] args)
    {
        Console.ResetColor();
        Console.WriteLine("=== GoblinBench Runner ===");
        Console.WriteLine();

        // Resolve paths
        var repoRoot = ResolveRepoRoot();
        var suitesRoot = Path.Combine(repoRoot, "suites");
        var runsRoot = Path.Combine(repoRoot, "runs");
        var candidatesFile = Path.Combine(repoRoot, "candidates.json");

        // Generate run ID
        var runId = $"run-{DateTime.UtcNow:yyyyMMdd-HHmmss}-{Guid.NewGuid():N}"[..16];
        var runDir = Path.Combine(runsRoot, runId);

        Console.WriteLine($"Run ID:   {runId}");
        Console.WriteLine($"Suites:   {suitesRoot}");
        Console.WriteLine($"Runs:     {runsRoot}");
        Console.WriteLine();

        // Discover scenarios
        Console.Write("Discovering scenarios... ");
        var scenarios = await ScenarioDiscovery.DiscoverAsync(suitesRoot);
        Console.WriteLine($"{scenarios.Count} found");

        if (scenarios.Count == 0)
        {
            Console.Error.WriteLine("Error: no scenarios found. Create .json files under suites/.");
            return 1;
        }

        foreach (var s in scenarios)
            Console.WriteLine($"  - {s.Id} (v{s.Version}) [{s.Suite}]");

        Console.WriteLine();

        // Load candidates
        var candidates = await LoadCandidatesAsync(candidatesFile);
        Console.WriteLine($"Candidates: {candidates.Count}");
        foreach (var c in candidates)
            Console.WriteLine($"  - {c.Id} ({c.Kind})");

        Console.WriteLine();

        // Create run context
        var context = new RunContext
        {
            RunId = runId,
            StartedAt = DateTime.UtcNow,
            RunDirectory = runDir,
            RunsRoot = runsRoot,
            Label = $"CLI run {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss}"
        };

        // Ensure run directory
        Directory.CreateDirectory(runDir);
        Directory.CreateDirectory(Path.Combine(runDir, "candidates"));

        // Resolve runners and scorers
        var runners = new List<ICandidateRunner>
        {
            new NoOpCandidateRunner(),
            new OpenAiChatRunner(),
            new HermesProfileRunner(),
            new ServiceEndpointRunner(),
            new ExternalCliRunner()
        };

        var scorers = new List<IScorer>
        {
            new NoOpScorer(),
            new ExactDecisionScorer(),
            new SchemaComplianceScorer(),
            new LatencyScorer(),
            new HeuristicTextScorer(),
            new CommandScorer(),
            new LlmJudgeScorer()
        };

        // Execute
        var runResult = new RunResult
        {
            RunId = runId,
            StartedAt = context.StartedAt,
            Label = context.Label
        };

        foreach (var scenario in scenarios)
        {
            Console.WriteLine($"--- Scenario: {scenario.Id} ---");

            var scenarioResult = new PerScenarioResult
            {
                ScenarioId = scenario.Id,
                ScenarioVersion = scenario.Version
            };

            runResult.Scenarios.Add(scenario.Id);

            foreach (var candidate in candidates)
            {
                Console.Write($"  Candidate: {candidate.Id} ... ");

                var runner = runners.FirstOrDefault(r => r.CanHandle(candidate));
                if (runner == null)
                {
                    Console.WriteLine("SKIP (no runner)");
                    scenarioResult.CandidateResults.Add(new CandidateResult
                    {
                        CandidateId = candidate.Id,
                        CandidateName = candidate.Name,
                        CandidateKind = candidate.Kind,
                        Success = false,
                        Error = "No compatible candidate runner found."
                    });
                    continue;
                }

                try
                {
                    var ct = new CancellationTokenSource(
                        TimeSpan.FromSeconds(scenario.TimeoutSeconds > 0
                            ? scenario.TimeoutSeconds
                            : 300)).Token;

                    var candidateResult = await runner.RunAsync(scenario, candidate, context, ct);

                    // Run scorers — only those declared in the scenario's scoring config
                    var declaredScorerIds = scenario.Scoring?.Scorers;
                    var activeScorers = declaredScorerIds != null && declaredScorerIds.Count > 0
                        ? scorers.Where(s => declaredScorerIds.Contains(s.Id, StringComparer.OrdinalIgnoreCase)).ToList()
                        : scorers; // fallback: all scorers if none declared

                    foreach (var scorer in activeScorers)
                    {
                        try
                        {
                            var score = await scorer.ScoreAsync(
                                scenario, candidate, candidateResult, context, ct);
                            candidateResult.Scores.Add(score);
                        }
                        catch (Exception ex)
                        {
                            candidateResult.Scores.Add(new ScoreResult
                            {
                                ScorerId = scorer.Id,
                                ScorerName = scorer.Name,
                                Success = false,
                                Error = ex.Message
                            });
                        }
                    }

                    // Write scores artifact
                    if (!string.IsNullOrEmpty(context.GetCandidateScoresPath(candidate.Id)))
                    {
                        var scoresDir = Path.GetDirectoryName(
                            context.GetCandidateScoresPath(candidate.Id));
                        if (scoresDir != null)
                            Directory.CreateDirectory(scoresDir);

                        await File.WriteAllTextAsync(
                            context.GetCandidateScoresPath(candidate.Id),
                            JsonSerializer.Serialize(candidateResult.Scores, JsonOptions));
                    }

                    scenarioResult.CandidateResults.Add(candidateResult);
                    Console.WriteLine(candidateResult.Success ? "OK" : "FAIL");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"ERROR: {ex.Message}");
                    scenarioResult.CandidateResults.Add(new CandidateResult
                    {
                        CandidateId = candidate.Id,
                        CandidateName = candidate.Name,
                        CandidateKind = candidate.Kind,
                        Success = false,
                        Error = ex.Message
                    });
                }
            }

            runResult.Results.Add(scenarioResult);
        }

        runResult = runResult with { CompletedAt = DateTime.UtcNow };

        // Write run.json
        var runJsonPath = Path.Combine(runDir, "run.json");
        await File.WriteAllTextAsync(runJsonPath,
            JsonSerializer.Serialize(runResult, JsonOptions));

        Console.WriteLine();
        Console.WriteLine($"Run complete. Artifacts: {runDir}");
        Console.WriteLine($"  run.json: {Path.GetFileName(runJsonPath)}");

        foreach (var scenarioResult in runResult.Results)
        {
            foreach (var cr in scenarioResult.CandidateResults)
            {
                var candidateDir = context.GetCandidateDirectory(cr.CandidateId);
                Console.WriteLine($"  {scenarioResult.ScenarioId}/{cr.CandidateId}: " +
                    $"{(cr.Success ? "OK" : "FAIL")} ({cr.DurationMs}ms) " +
                    $"{candidateDir}");
            }
        }

        return 0;
    }

    private static string ResolveRepoRoot()
    {
        // Walk up from the assembly location to find the repo root
        var dir = AppContext.BaseDirectory;
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir, "suites")) &&
                Directory.Exists(Path.Combine(dir, "src")))
                return dir;

            var parent = Path.GetDirectoryName(dir);
            if (parent == dir) break;
            dir = parent;
        }

        return Environment.CurrentDirectory;
    }

    private static async Task<List<CandidateConfig>> LoadCandidatesAsync(string path)
    {
        if (!File.Exists(path))
        {
            // Return a default no-op candidate for demo purposes
            return new List<CandidateConfig>
            {
                new()
                {
                    Id = "noop-demo",
                    Name = "No-Op Demo Candidate",
                    Kind = CandidateKind.Unknown,
                    CliCommand = "noop"
                }
            };
        }

        var json = await File.ReadAllTextAsync(path);
        return JsonSerializer.Deserialize<List<CandidateConfig>>(json, JsonOptions) ?? new();
    }
}
