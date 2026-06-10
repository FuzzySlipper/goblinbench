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

        var codingRows = GetCodingTestRows(data).ToList();
        if (codingRows.Count > 0)
        {
            sb.AppendLine("## Coding Test Summary");
            sb.AppendLine();
            sb.AppendLine("| Scenario | Candidate | Runner | Tests | Score | Visible | Strict | Markers | Duration |");
            sb.AppendLine("|---|---|---|---|---|---|---|---|---|");
            foreach (var row in codingRows)
            {
                var runner = row.RunnerSuccess ? "OK" : "FAIL";
                var tests = row.Passed == true ? "PASS" : row.Passed == false ? "FAIL" : "—";
                var score = row.Score.HasValue ? row.Score.Value.ToString("F2") : "—";
                var duration = row.DurationMs < 1000 ? $"{row.DurationMs}ms" : $"{row.DurationMs / 1000.0:F1}s";
                sb.AppendLine($"| {EscapeCell(ShortScenario(row.ScenarioId))} | {EscapeCell(row.CandidateId)} | {runner} | {tests} | {score} | {row.Visible} | {row.Strict} | {row.Markers} | {duration} |");
            }
            sb.AppendLine();
        }

        var mcpRows = GetMcpToolUseRows(data).ToList();
        if (mcpRows.Count > 0)
        {
            sb.AppendLine("## MCP Tool-Use Summary");
            sb.AppendLine();
            sb.AppendLine("| Scenario | Candidate | Score | Calls | Actual | Bypass | Trace Artifacts |");
            sb.AppendLine("|---|---|---|---|---|---|---|");
            foreach (var row in mcpRows)
            {
                var score = row.Score.HasValue ? row.Score.Value.ToString("F2") : "—";
                var calls = row.ExpectedCalls.HasValue && row.MatchedCalls.HasValue
                    ? $"{row.MatchedCalls}/{row.ExpectedCalls}"
                    : "—";
                var actual = row.ActualCalls?.ToString() ?? "—";
                var bypass = row.BypassAttempts?.ToString() ?? "—";
                var artifacts = string.IsNullOrWhiteSpace(row.ArtifactDirectory)
                    ? "—"
                    : $"`{Path.Combine(row.ArtifactDirectory, "tool_calls.json")}`";
                sb.AppendLine($"| {EscapeCell(ShortScenario(row.ScenarioId))} | {EscapeCell(row.CandidateId)} | {score} | {calls} | {actual} | {bypass} | {artifacts} |");
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

                var scorerEntries = cr.Scores.Select(s => new ScorerEntry
                {
                    ScorerId = s.ScorerId,
                    Score = s.Score,
                    Passed = s.Passed,
                    HumanSummary = s.HumanSummary,
                    Error = s.Error,
                    JudgeModel = s.JudgeModel,
                    JudgePromptVersion = s.JudgePromptVersion,
                    Detail = s.Detail
                }).ToList();
                var primary = scorerEntries.FirstOrDefault(s =>
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
                    ArtifactDirectory = cr.ArtifactDirectory,
                    FailureCategories = DeriveFailureCategories(cr, primary, scorerEntries),
                    ScorerDetails = scorerEntries
                };
            }
            return new ScenarioSummary
            {
                ScenarioId = sid,
                TaskShapeTags = DeriveTaskShapeTags(sid),
                CandidateScores = scores
            };
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

    private static IEnumerable<CodingTestReportRow> GetCodingTestRows(ReportData data)
    {
        foreach (var scenario in data.Scenarios)
        {
            foreach (var (candidateId, score) in scenario.CandidateScores)
            {
                var coding = score.ScorerDetails.FirstOrDefault(s =>
                    s.ScorerId.Equals("coding-tests", StringComparison.OrdinalIgnoreCase));
                if (coding == null) continue;

                yield return new CodingTestReportRow(
                    scenario.ScenarioId,
                    candidateId,
                    score.Success,
                    coding.Passed,
                    coding.Score,
                    FormatTestCount(coding, "visible_pass", "visible_total"),
                    FormatTestCount(coding, "strict_pass", "strict_total"),
                    FormatMarkerCount(coding),
                    score.DurationMs);
            }
        }
    }

    private static IEnumerable<McpToolUseReportRow> GetMcpToolUseRows(ReportData data)
    {
        foreach (var scenario in data.Scenarios)
        {
            foreach (var (candidateId, score) in scenario.CandidateScores)
            {
                var mcp = score.ScorerDetails.FirstOrDefault(s =>
                    s.ScorerId.Equals("mcp-tool-use", StringComparison.OrdinalIgnoreCase));
                if (mcp == null) continue;

                yield return new McpToolUseReportRow(
                    scenario.ScenarioId,
                    candidateId,
                    mcp.Score,
                    GetDetailInt(mcp, "matched_call_count"),
                    GetDetailInt(mcp, "expected_call_count"),
                    GetDetailInt(mcp, "actual_call_count"),
                    GetDetailInt(mcp, "bypass_attempt_count"),
                    score.ArtifactDirectory);
            }
        }
    }

    private static string FormatTestCount(ScorerEntry scorer, string passKey, string totalKey)
    {
        var passed = GetDetailInt(scorer, passKey);
        var total = GetDetailInt(scorer, totalKey);
        return passed.HasValue && total.HasValue ? $"{passed}/{total}" : "—";
    }

    private static string FormatMarkerCount(ScorerEntry scorer) =>
        GetDetailInt(scorer, "marker_count")?.ToString() ?? "—";

    private static int? GetDetailInt(ScorerEntry scorer, string key)
    {
        if (!scorer.Detail.TryGetValue(key, out var value) || value == null) return null;

        return value switch
        {
            int i => i,
            long l when l <= int.MaxValue && l >= int.MinValue => (int)l,
            double d when d % 1 == 0 && d <= int.MaxValue && d >= int.MinValue => (int)d,
            decimal d when d % 1 == 0 && d <= int.MaxValue && d >= int.MinValue => (int)d,
            string s when int.TryParse(s, out var i) => i,
            JsonElement { ValueKind: JsonValueKind.Number } e when e.TryGetInt32(out var i) => i,
            JsonElement { ValueKind: JsonValueKind.String } e when int.TryParse(e.GetString(), out var i) => i,
            _ => null
        };
    }

    private static bool? GetDetailBool(ScorerEntry scorer, string key)
    {
        if (!scorer.Detail.TryGetValue(key, out var value) || value == null) return null;

        return value switch
        {
            bool b => b,
            string s when bool.TryParse(s, out var b) => b,
            JsonElement { ValueKind: JsonValueKind.True } => true,
            JsonElement { ValueKind: JsonValueKind.False } => false,
            JsonElement { ValueKind: JsonValueKind.String } e when bool.TryParse(e.GetString(), out var b) => b,
            _ => null
        };
    }

    private static List<string> GetDetailStringArray(ScorerEntry scorer, string key)
    {
        if (!scorer.Detail.TryGetValue(key, out var value) || value == null) return new List<string>();
        if (value is string[] strings) return strings.ToList();
        if (value is IEnumerable<string> enumerable) return enumerable.ToList();
        if (value is JsonElement element && element.ValueKind == JsonValueKind.Array)
            return element.EnumerateArray()
                .Where(e => e.ValueKind == JsonValueKind.String)
                .Select(e => e.GetString() ?? string.Empty)
                .Where(s => !string.IsNullOrWhiteSpace(s))
                .ToList();
        return new List<string>();
    }

    private static List<string> DeriveFailureCategories(
        CandidateResult result, ScorerEntry? primary, IReadOnlyList<ScorerEntry> scorers)
    {
        var categories = new List<string>();
        if (!result.Success) categories.Add("runner_failure");
        if (primary == null)
            return categories;

        if (primary.ScorerId.Equals("mcp-tool-use", StringComparison.OrdinalIgnoreCase))
        {
            var expected = GetDetailInt(primary, "expected_call_count") ?? 0;
            var matched = GetDetailInt(primary, "matched_call_count") ?? 0;
            var actual = GetDetailInt(primary, "actual_call_count") ?? 0;
            var argMatches = GetDetailInt(primary, "argument_match_count") ?? 0;
            var bypassAttempts = GetDetailInt(primary, "bypass_attempt_count") ?? 0;
            var finalMatches = GetDetailInt(primary, "final_response_match_count") ?? 0;
            var finalExpected = GetDetailInt(primary, "final_response_expected_count") ?? 0;
            var forbiddenUsed = GetDetailBool(primary, "forbidden_tool_used") == true;
            var bypassViolated = GetDetailBool(primary, "bypass_violated") == true;
            var noCallsViolated = GetDetailBool(primary, "no_calls_violated") == true;

            if (actual > Math.Max(expected * 3, 10)) categories.Add("tool_thrashing");
            if (expected > 0 && matched < expected) categories.Add("missing_expected_tool_calls");
            if (expected > 0 && argMatches < expected) categories.Add("argument_grounding_failure");
            if (finalExpected > 0 && finalMatches == 0) categories.Add("final_response_missing");
            else if (finalExpected > 0 && finalMatches < finalExpected) categories.Add("weak_final_grounding");
            if (forbiddenUsed) categories.Add("forbidden_tool_used");
            if (bypassAttempts > 0 || bypassViolated) categories.Add("bypass_attempt");
            if (noCallsViolated) categories.Add("unexpected_tool_call");
            categories.AddRange(GetDetailStringArray(primary, "failure_categories"));
        }
        else if (primary.ScorerId.Equals("coding-tests", StringComparison.OrdinalIgnoreCase) && primary.Passed == false)
        {
            var visiblePass = GetDetailInt(primary, "visible_pass");
            var visibleTotal = GetDetailInt(primary, "visible_total");
            var strictPass = GetDetailInt(primary, "strict_pass");
            var strictTotal = GetDetailInt(primary, "strict_total");
            var markers = GetDetailInt(primary, "marker_count") ?? 0;
            if (visiblePass.HasValue && visibleTotal.HasValue && visiblePass < visibleTotal) categories.Add("visible_test_failure");
            if (strictPass.HasValue && strictTotal.HasValue && strictPass < strictTotal) categories.Add("strict_test_failure");
            if (markers > 0) categories.Add("marker_violation");
        }
        else if (primary.ScorerId.Equals("fuzzy-agent-behavior", StringComparison.OrdinalIgnoreCase))
        {
            categories.AddRange(GetDetailStringArray(primary, "failure_categories"));
        }

        if (primary.Passed == false && categories.Count == 0)
            categories.Add("scorer_failure");

        return categories.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
    }

    private static List<string> DeriveTaskShapeTags(string scenarioId)
    {
        var id = scenarioId.ToLowerInvariant();
        var suite = id.Split('.').FirstOrDefault() ?? id;
        var tags = new List<string>();

        if (suite == "mcp-tools-hard")
            tags.AddRange(new[] { "tool-forest", "decoy-resistance", "schema-grounding", "final-answer-grounding" });
        else if (suite == "mcp-tools")
            tags.AddRange(new[] { "tool-use", "decoy-resistance" });
        else if (suite == "mcp-session")
            tags.AddRange(new[] { "multi-turn-memory", "trajectory", "tool-use" });
        else if (suite == "coding")
            tags.AddRange(new[] { "coding-agent", "test-repair" });
        else if (suite == "orchestrator")
            tags.AddRange(new[] { "orchestration", "workflow-decision" });
        else if (suite == "autonomy-calibration")
            tags.AddRange(new[] { "ask-vs-proceed", "autonomy-calibration", "source-authority" });
        else if (suite == "evidence-grounding")
            tags.AddRange(new[] { "missing-evidence", "groundedness", "non-coding-groundedness" });
        else if (suite == "tool-call-behavior")
            tags.AddRange(new[] { "tool-use", "schema-discipline", "optional-parameter-minimalism", "error-recovery" });
        else if (suite == "fake-den-mcp")
            tags.AddRange(new[] { "tool-use", "den-mcp", "tool-forest", "safe-fake-side-effects" });
        else if (suite == "den-mcp-ambiguity" || suite == "den-mcp-ambiguity-hinted")
        {
            tags.AddRange(new[] { "tool-use", "den-mcp", "ambiguity", "project-routing", "ask-vs-proceed", "safe-fake-side-effects" });
            if (suite == "den-mcp-ambiguity-hinted") tags.Add("tool-description-hints");
        }

        if (id.Contains("archive")) tags.AddRange(new[] { "refusal-boundary", "safety-boundary" });
        if (id.Contains("invoice") || id.Contains("payment")) tags.AddRange(new[] { "safe-write-boundary", "schema-grounding" });
        if (id.Contains("canary") || id.Contains("rollout")) tags.AddRange(new[] { "action-gating", "evidence-gathering" });
        if (id.Contains("http") || id.Contains("bypass")) tags.Add("bypass-resistance");
        if (id.Contains("malformed") || id.Contains("stale")) tags.Add("bad-evidence-handling");
        if (id.Contains("conflict")) tags.Add("source-conflict");
        if (id.Contains("self-report")) tags.Add("self-report-vs-verified");
        if (id.Contains("smoke")) tags.Add("routine-verification");
        if (id.Contains("model-capability")) tags.Add("model-routing");
        if (id.Contains("partial-thread")) tags.Add("partial-context");
        if (id.Contains("optional") || id.Contains("null-optional")) tags.Add("optional-parameter-discipline");
        if (id.Contains("guided-error")) tags.Add("guided-error");
        if (id.Contains("bare-error")) tags.Add("bare-error-control");

        return tags.Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(t => t).ToList();
    }

    private static string EscapeCell(string value) => value.Replace("|", "\\|");

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

    [JsonPropertyName("task_shape_tags")]
    public List<string> TaskShapeTags { get; init; } = new();

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

    [JsonPropertyName("artifact_directory")]
    public string? ArtifactDirectory { get; init; }

    [JsonPropertyName("failure_categories")]
    public List<string> FailureCategories { get; init; } = new();

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

    [JsonPropertyName("detail")]
    public Dictionary<string, object?> Detail { get; init; } = new();
}

internal sealed record CodingTestReportRow(
    string ScenarioId,
    string CandidateId,
    bool RunnerSuccess,
    bool? Passed,
    double? Score,
    string Visible,
    string Strict,
    string Markers,
    long DurationMs);

internal sealed record McpToolUseReportRow(
    string ScenarioId,
    string CandidateId,
    double? Score,
    int? MatchedCalls,
    int? ExpectedCalls,
    int? ActualCalls,
    int? BypassAttempts,
    string? ArtifactDirectory);
