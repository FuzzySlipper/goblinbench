using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using GoblinBench.Core;

namespace GoblinBench.Runner;

/// <summary>
/// Generates Markdown and JSON comparison reports from one or more run artifacts.
/// Reports are comparison-first: candidates × scenarios in a grid with pass/fail,
/// scores, latency, model identity, failure notes, and artifact paths.
/// </summary>
public static class ReportGenerator
{
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = true
    };

    // ── public API ────────────────────────────────────────────────────────────

    public static async Task<ReportData> LoadRunsAsync(
        IEnumerable<string> runPaths, string? suiteFilter = null, CancellationToken ct = default)
    {
        var runs = new List<RunResult>();
        var runDirs = new List<string>();

        foreach (var path in runPaths)
        {
            var (result, dir) = await LoadRunAsync(path, ct);
            if (result != null)
            {
                runs.Add(result);
                runDirs.Add(dir);
            }
        }

        return BuildReportData(runs, runDirs, suiteFilter);
    }

    public static string RenderMarkdown(ReportData data)
    {
        var sb = new StringBuilder();

        sb.AppendLine("# GoblinBench Comparison Report");
        if (data.SuiteFilter != null) sb.AppendLine($"**Suite:** {data.SuiteFilter}  ");
        sb.AppendLine($"**Generated:** {data.GeneratedAt:yyyy-MM-dd HH:mm:ss} UTC  ");
        sb.AppendLine($"**Run(s):** {string.Join(", ", data.RunIds)}  ");
        sb.AppendLine();

        // ── Candidate overview ─────────────────────────────────────────────
        sb.AppendLine("## Candidate Overview");
        sb.AppendLine();
        sb.AppendLine("| Candidate | Model | Provider | Pass Rate | Avg Latency |");
        sb.AppendLine("|---|---|---|---|---|");
        foreach (var c in data.Candidates)
        {
            var passRate = c.TotalScenarios > 0
                ? $"{c.PassCount}/{c.TotalScenarios} ({100 * c.PassCount / c.TotalScenarios}%)"
                : "—";
            var latency = c.AvgLatencyMs < 1000
                ? $"{c.AvgLatencyMs:F0}ms"
                : $"{c.AvgLatencyMs / 1000.0:F1}s";
            var model = c.ModelIdentity?.Model ?? c.CandidateKind.ToString();
            var provider = c.ModelIdentity?.Provider ?? "—";
            sb.AppendLine($"| {c.CandidateId} | {model} | {provider} | {passRate} | {latency} |");
        }
        sb.AppendLine();

        // ── Scenario grid ──────────────────────────────────────────────────
        if (data.Scenarios.Count > 0)
        {
            sb.AppendLine("## Scenario Scores");
            sb.AppendLine();

            var candidateIds = data.Candidates.Select(c => c.CandidateId).ToList();
            var header = "| Scenario |" + string.Join("", candidateIds.Select(id => $" {ShortId(id)} |"));
            var divider = "|---|" + string.Join("", candidateIds.Select(_ => "---|"));
            sb.AppendLine(header);
            sb.AppendLine(divider);

            foreach (var scenario in data.Scenarios)
            {
                var cells = candidateIds.Select(cid =>
                {
                    if (!scenario.CandidateScores.TryGetValue(cid, out var s)) return " — ";
                    var icon = s.Passed == true ? "✓" : s.Passed == false ? "✗" : "~";
                    var score = s.Score.HasValue ? $" {s.Score:F2}" : "";
                    var lat = s.DurationMs < 1000 ? $" {s.DurationMs}ms" : $" {s.DurationMs / 1000.0:F1}s";
                    return $" {icon}{score}{lat} ";
                });
                sb.AppendLine($"| {ShortScenario(scenario.ScenarioId)} |" + string.Join("", cells.Select(c => $"{c}|")));
            }
            sb.AppendLine();
        }

        // ── Scorer key ──────────────────────────────────────────────────────
        if (data.ScorerIds.Count > 0)
        {
            sb.AppendLine("## Score Breakdown by Scorer");
            sb.AppendLine();
            foreach (var scorerId in data.ScorerIds)
            {
                sb.AppendLine($"### {scorerId}");
                sb.AppendLine();
                sb.AppendLine("| Candidate | Scenario | Score | Summary |");
                sb.AppendLine("|---|---|---|---|");
                foreach (var cand in data.Candidates)
                {
                    foreach (var scenario in data.Scenarios)
                    {
                        if (!scenario.CandidateScores.TryGetValue(cand.CandidateId, out var cs)) continue;
                        var scorer = cs.ScorerDetails.FirstOrDefault(s => s.ScorerId == scorerId);
                        if (scorer == null) continue;
                        var score = scorer.Score?.ToString("F2") ?? "—";
                        var summary = (scorer.HumanSummary ?? scorer.Error ?? "").Replace("|", "\\|");
                        if (summary.Length > 80) summary = summary[..77] + "...";
                        sb.AppendLine($"| {cand.CandidateId} | {ShortScenario(scenario.ScenarioId)} | {score} | {summary} |");
                    }
                }
                sb.AppendLine();
            }
        }

        // ── Failures ────────────────────────────────────────────────────────
        var failures = data.Scenarios
            .SelectMany(s => s.CandidateScores.Values.Where(c => c.Success == false || c.Passed == false))
            .ToList();

        if (failures.Any(f => f.Success == false))
        {
            sb.AppendLine("## Runner Failures");
            sb.AppendLine();
            // Group by candidate for readability; truncate verbose error bodies
            var failGroups = data.Scenarios
                .SelectMany(s => s.CandidateScores
                    .Where(kv => !kv.Value.Success)
                    .Select(kv => (scenario: s.ScenarioId, cid: kv.Key, error: kv.Value.Error)))
                .GroupBy(x => x.cid)
                .ToList();

            foreach (var group in failGroups)
            {
                var firstError = group.First().error ?? "unknown";
                var shortError = firstError.Length > 120 ? firstError[..117] + "..." : firstError;
                var scenarioList = string.Join(", ", group.Select(x => ShortScenario(x.scenario)));
                sb.AppendLine($"- **{group.Key}** ({group.Count()} scenario(s)): {shortError}");
                sb.AppendLine($"  Scenarios: {scenarioList}");
            }
            sb.AppendLine();
        }

        // ── Artifacts ───────────────────────────────────────────────────────
        sb.AppendLine("## Artifact Paths");
        sb.AppendLine();
        foreach (var (runId, runDir) in data.RunIds.Zip(data.RunDirs))
            sb.AppendLine($"- **{runId}**: `{runDir}`");

        return sb.ToString();
    }

    public static string RenderJson(ReportData data) =>
        JsonSerializer.Serialize(data, JsonOpts);

    // ── internal ──────────────────────────────────────────────────────────────

    private static async Task<(RunResult? result, string dir)> LoadRunAsync(
        string pathOrId, CancellationToken ct)
    {
        // Accept: absolute path to run dir, absolute path to run.json, or run ID
        string runJsonPath;
        string runDir;

        if (File.Exists(pathOrId))
        {
            runJsonPath = pathOrId;
            runDir = Path.GetDirectoryName(pathOrId) ?? pathOrId;
        }
        else if (Directory.Exists(pathOrId))
        {
            runDir = pathOrId;
            runJsonPath = Path.Combine(pathOrId, "run.json");
        }
        else
        {
            // Try as run ID relative to runs/ in the repo
            var repoRuns = FindRunsRoot(pathOrId);
            runDir = Path.Combine(repoRuns, pathOrId);
            runJsonPath = Path.Combine(runDir, "run.json");
        }

        if (!File.Exists(runJsonPath))
        {
            Console.Error.WriteLine($"Warning: run.json not found at {runJsonPath}");
            return (null, runDir);
        }

        try
        {
            var json = await File.ReadAllTextAsync(runJsonPath, ct);
            var result = JsonSerializer.Deserialize<RunResult>(json,
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            return (result, runDir);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Warning: failed to load {runJsonPath}: {ex.Message}");
            return (null, runDir);
        }
    }

    private static ReportData BuildReportData(
        List<RunResult> runs, List<string> runDirs, string? suiteFilter)
    {
        // Collect all candidate IDs and scenario IDs seen across runs
        var allCandidateIds = new List<string>();
        var allScenarioIds = new List<string>();

        foreach (var run in runs)
        {
            foreach (var scenario in run.Results)
            {
                if (suiteFilter != null)
                {
                    // Filter by suite prefix (scenario ID starts with "suite.")
                    var suitePart = scenario.ScenarioId.Split('.').FirstOrDefault();
                    if (!string.Equals(suitePart, suiteFilter, StringComparison.OrdinalIgnoreCase))
                        continue;
                }
                if (!allScenarioIds.Contains(scenario.ScenarioId))
                    allScenarioIds.Add(scenario.ScenarioId);
                foreach (var cr in scenario.CandidateResults)
                {
                    if (!allCandidateIds.Contains(cr.CandidateId))
                        allCandidateIds.Add(cr.CandidateId);
                }
            }
        }

        // Build per-candidate aggregates
        var candidateData = allCandidateIds.Select(cid =>
        {
            var allResults = runs
                .SelectMany(r => r.Results)
                .Where(s => suiteFilter == null || s.ScenarioId.StartsWith(suiteFilter + ".",
                    StringComparison.OrdinalIgnoreCase))
                .SelectMany(s => s.CandidateResults)
                .Where(cr => cr.CandidateId == cid)
                .ToList();

            var identity = allResults.Select(r => r.ModelIdentity).FirstOrDefault(m => m != null);
            var kind = allResults.Select(r => r.CandidateKind).FirstOrDefault();

            // A scenario "passed" if ANY scorer flagged it with passed=false → fail
            // Use the primary scorers (first non-noop, non-latency scorer)
            int passCount = 0, totalScenarios = 0;
            long totalLatencyMs = 0;
            int latencyCount = 0;

            foreach (var cr in allResults)
            {
                totalScenarios++;
                var primaryScore = cr.Scores.FirstOrDefault(s =>
                    s.Passed.HasValue && s.ScorerId != "noop" && s.ScorerId != "latency");
                if (primaryScore?.Passed == true) passCount++;
                else if (primaryScore == null && cr.Success) passCount++; // no declared scorers → success = pass
                totalLatencyMs += cr.DurationMs;
                latencyCount++;
            }

            return new CandidateSummary
            {
                CandidateId = cid,
                CandidateKind = kind.ToString(),
                ModelIdentity = identity,
                PassCount = passCount,
                TotalScenarios = totalScenarios,
                AvgLatencyMs = latencyCount > 0 ? (double)totalLatencyMs / latencyCount : 0
            };
        }).ToList();

        // Build per-scenario data
        var scenarioData = allScenarioIds.Select(sid =>
        {
            var scores = new Dictionary<string, CandidateScoreEntry>();
            foreach (var cid in allCandidateIds)
            {
                var cr = runs
                    .SelectMany(r => r.Results.Where(s => s.ScenarioId == sid))
                    .SelectMany(s => s.CandidateResults)
                    .LastOrDefault(r => r.CandidateId == cid);
                if (cr == null) continue;

                var primary = cr.Scores.FirstOrDefault(s =>
                    s.Passed.HasValue && s.ScorerId != "noop" && s.ScorerId != "latency");
                scores[cid] = new CandidateScoreEntry
                {
                    CandidateId = cid,
                    Success = cr.Success,
                    Error = cr.Error,
                    DurationMs = cr.DurationMs,
                    Score = primary?.Score,
                    Passed = primary?.Passed ?? (cr.Success ? (bool?)null : false),
                    PrimaryScorerId = primary?.ScorerId,
                    ScorerDetails = cr.Scores.Select(s => new ScorerEntry
                    {
                        ScorerId = s.ScorerId,
                        Score = s.Score,
                        Passed = s.Passed,
                        HumanSummary = s.HumanSummary,
                        Error = s.Error,
                        JudgeModel = s.JudgeModel,
                        JudgePromptVersion = s.JudgePromptVersion
                    }).ToList()
                };
            }
            return new ScenarioSummary { ScenarioId = sid, CandidateScores = scores };
        }).ToList();

        var allScorerIds = scenarioData
            .SelectMany(s => s.CandidateScores.Values)
            .SelectMany(c => c.ScorerDetails)
            .Select(s => s.ScorerId)
            .Where(id => id != "noop")
            .Distinct()
            .ToList();

        return new ReportData
        {
            GeneratedAt = DateTime.UtcNow,
            RunIds = runs.Select(r => r.RunId).ToList(),
            RunDirs = runDirs,
            SuiteFilter = suiteFilter,
            Candidates = candidateData,
            Scenarios = scenarioData,
            ScorerIds = allScorerIds
        };
    }

    private static string ShortId(string id)
    {
        // Shorten long IDs for table headers
        if (id.Length <= 18) return id;
        return id[..8] + "…" + id[^6..];
    }

    private static string ShortScenario(string id)
    {
        // Remove suite prefix for brevity
        var dot = id.IndexOf('.');
        return dot >= 0 ? id[(dot + 1)..] : id;
    }

    private static string FindRunsRoot(string runId)
    {
        // Walk up from the assembly location to find the repo root's runs/ directory
        var dir = Path.GetDirectoryName(typeof(ReportGenerator).Assembly.Location) ?? ".";
        while (dir != null)
        {
            var runsDir = Path.Combine(dir, "runs");
            if (Directory.Exists(runsDir) && Directory.Exists(Path.Combine(dir, "suites")))
                return runsDir;
            var parent = Path.GetDirectoryName(dir);
            if (parent == dir) break;
            dir = parent;
        }
        return Path.Combine(AppContext.BaseDirectory, "runs");
    }
}

// ── Data model ─────────────────────────────────────────────────────────────

public sealed class ReportData
{
    [JsonPropertyName("generated_at")]
    public DateTime GeneratedAt { get; init; }

    [JsonPropertyName("run_ids")]
    public List<string> RunIds { get; init; } = new();

    [JsonPropertyName("run_dirs")]
    public List<string> RunDirs { get; init; } = new();

    [JsonPropertyName("suite_filter")]
    public string? SuiteFilter { get; init; }

    [JsonPropertyName("candidates")]
    public List<CandidateSummary> Candidates { get; init; } = new();

    [JsonPropertyName("scenarios")]
    public List<ScenarioSummary> Scenarios { get; init; } = new();

    [JsonPropertyName("scorer_ids")]
    public List<string> ScorerIds { get; init; } = new();
}

public sealed class CandidateSummary
{
    [JsonPropertyName("candidate_id")]
    public string CandidateId { get; init; } = string.Empty;

    [JsonPropertyName("candidate_kind")]
    public string CandidateKind { get; init; } = string.Empty;

    [JsonPropertyName("model_identity")]
    public ModelIdentity? ModelIdentity { get; init; }

    [JsonPropertyName("pass_count")]
    public int PassCount { get; init; }

    [JsonPropertyName("total_scenarios")]
    public int TotalScenarios { get; init; }

    [JsonPropertyName("avg_latency_ms")]
    public double AvgLatencyMs { get; init; }
}

public sealed class ScenarioSummary
{
    [JsonPropertyName("scenario_id")]
    public string ScenarioId { get; init; } = string.Empty;

    [JsonPropertyName("candidate_scores")]
    public Dictionary<string, CandidateScoreEntry> CandidateScores { get; init; } = new();
}

public sealed class CandidateScoreEntry
{
    [JsonPropertyName("candidate_id")]
    public string CandidateId { get; init; } = string.Empty;

    [JsonPropertyName("success")]
    public bool Success { get; init; }

    [JsonPropertyName("error")]
    public string? Error { get; init; }

    [JsonPropertyName("duration_ms")]
    public long DurationMs { get; init; }

    [JsonPropertyName("score")]
    public double? Score { get; init; }

    [JsonPropertyName("passed")]
    public bool? Passed { get; init; }

    [JsonPropertyName("primary_scorer_id")]
    public string? PrimaryScorerId { get; init; }

    [JsonPropertyName("scorer_details")]
    public List<ScorerEntry> ScorerDetails { get; init; } = new();
}

public sealed class ScorerEntry
{
    [JsonPropertyName("scorer_id")]
    public string ScorerId { get; init; } = string.Empty;

    [JsonPropertyName("score")]
    public double? Score { get; init; }

    [JsonPropertyName("passed")]
    public bool? Passed { get; init; }

    [JsonPropertyName("human_summary")]
    public string? HumanSummary { get; init; }

    [JsonPropertyName("error")]
    public string? Error { get; init; }

    [JsonPropertyName("judge_model")]
    public string? JudgeModel { get; init; }

    [JsonPropertyName("judge_prompt_version")]
    public string? JudgePromptVersion { get; init; }
}
