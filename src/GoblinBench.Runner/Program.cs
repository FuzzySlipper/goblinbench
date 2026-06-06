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

        // Dispatch to report subcommand if requested
        if (args.Length > 0 && args[0].Equals("report", StringComparison.OrdinalIgnoreCase))
            return await RunReportAsync(args[1..]);

        Console.WriteLine("=== GoblinBench Runner ===");
        Console.WriteLine();

        // Resolve paths
        var repoRoot = ResolveRepoRoot();
        var suitesRoot = Path.Combine(repoRoot, "suites");
        var runsRoot = Path.Combine(repoRoot, "runs");
        var candidatesFile = Path.Combine(repoRoot, "candidates.json");

        // Parse basic filters and overrides
        string? suiteFilter = null;
        string? scenarioFilter = null;
        string? candidatesOverride = null;
        var candidateFilters = new List<string>();
        for (var i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == "--suite") suiteFilter = args[i + 1];
            if (args[i] == "--scenario") scenarioFilter = args[i + 1];
            if (args[i] == "--candidates") candidatesOverride = args[i + 1];
            if (args[i] == "--candidate") candidateFilters.Add(args[i + 1]);
        }
        if (candidatesOverride != null)
            candidatesFile = Path.IsPathRooted(candidatesOverride)
                ? candidatesOverride
                : Path.Combine(repoRoot, candidatesOverride);

        // Generate a collision-safe run ID: timestamp + 8 hex chars from a GUID
        var runId = $"run-{DateTime.UtcNow:yyyyMMdd-HHmmss}-{Guid.NewGuid().ToString("N")[..8]}";
        var runDir = Path.Combine(runsRoot, runId);

        Console.WriteLine($"Run ID:   {runId}");
        Console.WriteLine($"Suites:   {suitesRoot}");
        Console.WriteLine($"Runs:     {runsRoot}");
        if (suiteFilter != null) Console.WriteLine($"Filter:   --suite {suiteFilter}");
        if (scenarioFilter != null) Console.WriteLine($"Filter:   --scenario {scenarioFilter}");
        if (candidateFilters.Count > 0) Console.WriteLine($"Filter:   --candidate {string.Join(",", ExpandCandidateFilters(candidateFilters))}");
        Console.WriteLine();

        // Discover scenarios
        Console.Write("Discovering scenarios... ");
        var allScenarios = await ScenarioDiscovery.DiscoverAsync(suitesRoot);
        var scenarios = allScenarios
            .Where(s => suiteFilter == null ||
                        s.Suite.Equals(suiteFilter, StringComparison.OrdinalIgnoreCase))
            .Where(s => scenarioFilter == null ||
                        s.Id.Equals(scenarioFilter, StringComparison.OrdinalIgnoreCase))
            .ToList();
        Console.WriteLine($"{scenarios.Count} found (of {allScenarios.Count} total)");

        if (scenarios.Count == 0)
        {
            Console.Error.WriteLine("Error: no scenarios found. Create .json files under suites/.");
            return 1;
        }

        foreach (var s in scenarios)
            Console.WriteLine($"  - {s.Id} (v{s.Version}) [{s.Suite}]");

        Console.WriteLine();

        // Load candidates
        var candidates = FilterCandidatesById(await LoadCandidatesAsync(candidatesFile), candidateFilters);
        if (candidates.Count == 0)
        {
            Console.Error.WriteLine("Error: no candidates matched --candidate filter.");
            return 1;
        }
        Console.WriteLine($"Candidates: {candidates.Count} (from {Path.GetFileName(candidatesFile)})");
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
            RepoRoot = repoRoot,
            Label = $"CLI run {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss}"
        };

        // Ensure run directory
        Directory.CreateDirectory(runDir);
        Directory.CreateDirectory(Path.Combine(runDir, "candidates"));

        // Resolve runners and scorers
        // ScriptedCandidateRunner must come before NoOpCandidateRunner: NoOp matches
        // any Kind=Unknown candidate, which would otherwise shadow the scripted runner.
        var runners = new List<ICandidateRunner>
        {
            new ScriptedCandidateRunner(),
            new FakeMcpCandidateRunner(),
            new CodingCandidateRunner(),
            new CodingAgentRunner(),
            new ElectronCandidateRunner(),
            new VisionCandidateRunner(),
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
            new LlmJudgeScorer(),
            new OrchestratorDecisionScorer(),
            new McpToolUseScorer(),
            new VisionCorrectnessScorer(),
            new CodingTestScorer(),
            new ElectronFlowScorer()
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

            var scenarioContext = CreateScenarioContext(context, scenario.Id);

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

                    var candidateResult = await runner.RunAsync(scenario, candidate, scenarioContext, ct);

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
                                scenario, candidate, candidateResult, scenarioContext, ct);
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
                    if (!string.IsNullOrEmpty(scenarioContext.GetCandidateScoresPath(candidate.Id)))
                    {
                        var scoresDir = Path.GetDirectoryName(
                            scenarioContext.GetCandidateScoresPath(candidate.Id));
                        if (scoresDir != null)
                            Directory.CreateDirectory(scoresDir);

                        await File.WriteAllTextAsync(
                            scenarioContext.GetCandidateScoresPath(candidate.Id),
                            JsonSerializer.Serialize(candidateResult.Scores, JsonOptions));
                    }

                    // Write trace.jsonl — flushed centrally so all runners get it
                    if (candidateResult.Trace.Count > 0)
                    {
                        var tracePath = scenarioContext.GetCandidateTracePath(candidate.Id);
                        var traceDir = Path.GetDirectoryName(tracePath);
                        if (traceDir != null) Directory.CreateDirectory(traceDir);
                        var traceLines = candidateResult.Trace
                            .Select(t => JsonSerializer.Serialize(t, JsonOptions));
                        await File.AppendAllTextAsync(tracePath,
                            string.Join(Environment.NewLine, traceLines) + Environment.NewLine);
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
                var candidateDir = CreateScenarioContext(context, scenarioResult.ScenarioId)
                    .GetCandidateDirectory(cr.CandidateId);
                Console.WriteLine($"  {scenarioResult.ScenarioId}/{cr.CandidateId}: " +
                    $"{(cr.Success ? "OK" : "FAIL")} ({cr.DurationMs}ms) " +
                    $"{candidateDir}");
            }
        }

        return 0;
    }

    private static RunContext CreateScenarioContext(RunContext context, string scenarioId) => new()
    {
        RunId = context.RunId,
        StartedAt = context.StartedAt,
        RunDirectory = context.RunDirectory,
        RunsRoot = context.RunsRoot,
        RepoRoot = context.RepoRoot,
        ScenarioId = scenarioId,
        Label = context.Label,
        Metadata = context.Metadata
    };

    private static async Task<int> RunReportAsync(string[] args)
    {
        Console.WriteLine("=== GoblinBench Report ===");
        Console.WriteLine();

        // Parse: report <run...> [--suite <suite>] [--output <path>] [--den] [--den-project <id>]
        var runArgs = new List<string>();
        string? suiteFilter = null;
        string? outputPath = null;
        bool postToDen = false;
        string denProject = "goblinbench";

        for (var i = 0; i < args.Length; i++)
        {
            if (args[i] == "--suite" && i + 1 < args.Length) suiteFilter = args[++i];
            else if (args[i] == "--output" && i + 1 < args.Length) outputPath = args[++i];
            else if (args[i] == "--den") postToDen = true;
            else if (args[i] == "--den-project" && i + 1 < args.Length) denProject = args[++i];
            else if (!args[i].StartsWith("--")) runArgs.Add(args[i]);
        }

        if (runArgs.Count == 0)
        {
            // Default: use the most recent run in runs/
            var repoRoot = ResolveRepoRoot();
            var runsRoot = Path.Combine(repoRoot, "runs");
            if (Directory.Exists(runsRoot))
            {
                var latest = Directory.EnumerateDirectories(runsRoot)
                    .Where(d => File.Exists(Path.Combine(d, "run.json")))
                    .OrderByDescending(d => d)
                    .FirstOrDefault();
                if (latest != null) runArgs.Add(latest);
            }
        }

        if (runArgs.Count == 0)
        {
            Console.Error.WriteLine("Usage: goblinbench report <run-id-or-path> [...]" +
                " [--suite <suite>] [--output <path>] [--den]");
            return 1;
        }

        Console.WriteLine($"Loading {runArgs.Count} run(s)...");
        var data = await ReportGenerator.LoadRunsAsync(runArgs, suiteFilter);

        if (data.Candidates.Count == 0)
        {
            Console.Error.WriteLine("No candidate results found in the specified runs.");
            return 1;
        }

        Console.WriteLine($"  {data.Scenarios.Count} scenario(s), {data.Candidates.Count} candidate(s)");
        Console.WriteLine();

        var markdown = ReportGenerator.RenderMarkdown(data);
        var jsonReport = ReportGenerator.RenderJson(data);

        // Write report files
        var repoRootForOutput = ResolveRepoRoot();
        var defaultDir = data.RunIds.Count == 1
            ? Path.Combine(repoRootForOutput, "runs", data.RunIds[0])
            : Path.Combine(repoRootForOutput, "runs");

        var mdPath = outputPath != null
            ? Path.ChangeExtension(outputPath, ".md")
            : Path.Combine(defaultDir, "report.md");
        var jsonPath = outputPath != null
            ? Path.ChangeExtension(outputPath, ".json")
            : Path.Combine(defaultDir, "report.json");

        await File.WriteAllTextAsync(mdPath, markdown);
        await File.WriteAllTextAsync(jsonPath, jsonReport);

        Console.WriteLine($"Report written:");
        Console.WriteLine($"  Markdown: {mdPath}");
        Console.WriteLine($"  JSON:     {jsonPath}");
        Console.WriteLine();
        Console.Write(markdown);

        // Den integration
        if (postToDen)
        {
            Console.WriteLine();
            Console.WriteLine("--- Posting to Den ---");
            var posted = await PostReportToDenAsync(data, markdown, jsonReport, denProject);
            if (posted) Console.WriteLine("Posted to Den.");
            else Console.WriteLine("Den posting failed or skipped — report saved locally.");
        }
        else
        {
            Console.WriteLine();
            Console.WriteLine("Tip: pass --den to store this report as a Den document.");
        }

        return 0;
    }

    private static async Task<bool> PostReportToDenAsync(
        ReportData data, string markdown, string jsonReport, string denProject)
    {
        // Call the planner MCP server to store the report as a Den document.
        // Uses the stateful HTTP transport: initialize → tools/call store_document.
        const string plannerUrl = "http://192.168.1.10:5199/mcp?tool_profile=planner";

        try
        {
            using var http = new System.Net.Http.HttpClient { Timeout = TimeSpan.FromSeconds(30) };

            // Initialize session
            var initBody = JsonSerializer.Serialize(new
            {
                jsonrpc = "2.0", id = 1, method = "initialize",
                @params = new
                {
                    protocolVersion = "2024-11-05",
                    capabilities = new { },
                    clientInfo = new { name = "goblinbench-reporter", version = "1.0" }
                }
            });

            var initReq = new System.Net.Http.HttpRequestMessage(
                System.Net.Http.HttpMethod.Post, plannerUrl)
            {
                Content = new System.Net.Http.StringContent(
                    initBody, System.Text.Encoding.UTF8, "application/json")
            };
            initReq.Headers.TryAddWithoutValidation("Accept", "text/event-stream, application/json");

            using var initResp = await http.SendAsync(initReq);
            var sessionId = initResp.Headers.TryGetValues("Mcp-Session-Id", out var vals)
                ? vals.First() : null;
            if (sessionId == null)
            {
                Console.Error.WriteLine($"Den: init failed — no session ID in response ({(int)initResp.StatusCode})");
                return false;
            }

            // Build slug and title
            var suite = data.SuiteFilter ?? string.Join("-", data.RunIds.Take(2));
            var slug = $"bench-report-{suite}-{DateTime.UtcNow:yyyyMMdd-HHmm}";
            var title = data.SuiteFilter != null
                ? $"Benchmark Report — {data.SuiteFilter} suite — {DateTime.UtcNow:yyyy-MM-dd}"
                : $"Benchmark Report — {string.Join(", ", data.RunIds)} — {DateTime.UtcNow:yyyy-MM-dd}";

            // Build summary section for the document (markdown is the full content)
            var toolBody = JsonSerializer.Serialize(new
            {
                jsonrpc = "2.0", id = 2, method = "tools/call",
                @params = new
                {
                    name = "store_document",
                    arguments = new
                    {
                        project_id = denProject,
                        slug,
                        title,
                        content = markdown,
                        doc_type = "note",
                        tags = new[] { "benchmark", "report", data.SuiteFilter ?? "multi-suite" }
                            .Where(t => t != null).ToArray()
                    }
                }
            });

            var toolReq = new System.Net.Http.HttpRequestMessage(
                System.Net.Http.HttpMethod.Post, plannerUrl)
            {
                Content = new System.Net.Http.StringContent(
                    toolBody, System.Text.Encoding.UTF8, "application/json")
            };
            toolReq.Headers.TryAddWithoutValidation("Mcp-Session-Id", sessionId);
            toolReq.Headers.TryAddWithoutValidation("Accept", "text/event-stream, application/json");

            using var toolResp = await http.SendAsync(toolReq);
            var toolRespBody = await toolResp.Content.ReadAsStringAsync();
            var parsedJson = SseContent(toolRespBody);

            using var doc = JsonDocument.Parse(parsedJson);
            if (doc.RootElement.TryGetProperty("error", out var errProp))
            {
                Console.Error.WriteLine($"Den: tool call error — {errProp.GetRawText()[..Math.Min(120, errProp.GetRawText().Length)]}");
                return false;
            }
            if (doc.RootElement.TryGetProperty("result", out var result))
            {
                if (result.TryGetProperty("isError", out var isErr) && isErr.GetBoolean())
                {
                    Console.Error.WriteLine("Den: store_document returned isError=true");
                    return false;
                }
                Console.WriteLine($"  Stored as '{slug}' in project '{denProject}'");
                Console.WriteLine($"  Title: {title}");
                return true;
            }
            Console.Error.WriteLine($"Den: unexpected response shape — {parsedJson[..Math.Min(200, parsedJson.Length)]}");
            return false;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Den posting error: {ex.Message}");
            return false;
        }
    }

    private static string SseContent(string rawResponse)
    {
        // SSE responses start with "event: message\ndata: ..." — extract the data JSON
        foreach (var line in rawResponse.Split('\n'))
        {
            var trimmed = line.Trim();
            if (trimmed.StartsWith("data:"))
                return trimmed["data:".Length..].Trim();
        }
        return rawResponse;
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

    public static List<CandidateConfig> FilterCandidatesById(
        IReadOnlyList<CandidateConfig> candidates,
        IReadOnlyList<string> candidateFilters)
    {
        var wanted = ExpandCandidateFilters(candidateFilters).ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (wanted.Count == 0) return candidates.ToList();
        return candidates.Where(c => wanted.Contains(c.Id)).ToList();
    }

    private static IEnumerable<string> ExpandCandidateFilters(IReadOnlyList<string> candidateFilters) =>
        candidateFilters
            .SelectMany(f => f.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            .Where(f => !string.IsNullOrWhiteSpace(f));

    private static async Task<List<CandidateConfig>> LoadCandidatesAsync(string path)
    {
        if (!File.Exists(path))
        {
            Console.WriteLine($"Warning: {path} not found — using built-in no-op demo candidate.");
            Console.WriteLine("  Create candidates.json at the repo root, or pass --candidates <path>.");
            Console.WriteLine("  See docs/vision-suite-guide.md for candidate config examples.");
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
