using System.Text.Json;
using GoblinBench.Candidates;
using GoblinBench.Core;
using GoblinBench.Scorers;

namespace GoblinBench.Core.Tests;

public class McpToolUseSuiteTests
{
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };

    [Fact]
    public async Task McpToolUseScorer_PassesExpectedToolCallsAndGroundedFinalAnswer()
    {
        var scenario = ScenarioWithScoring(expectedCalls: [
            new ExpectedCall("records_lookup", new Dictionary<string, string> { ["customer"] = "Mira Chen" }),
            new ExpectedCall("cases_list", new Dictionary<string, string> { ["customer_id"] = "cust-1042" })
        ], finalResponseContains: ["Mira Chen", "CASE-7"]);
        var result = ResultWithOutput(new
        {
            tool_calls = new object[]
            {
                new { tool = "records_lookup", arguments = new { customer = "Mira Chen" }, result = new { customer_id = "cust-1042" } },
                new { tool = "cases_list", arguments = new { customer_id = "cust-1042" }, result = new { cases = new[] { "CASE-7" } } }
            },
            bypass_attempts = Array.Empty<object>(),
            final_response = "Mira Chen has one open case: CASE-7."
        });

        var score = await new McpToolUseScorer().ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext());

        Assert.True(score.Success);
        Assert.True(score.Passed);
        Assert.Equal(1.0, score.Score!.Value, precision: 5);
        Assert.Equal(2, score.Detail["matched_call_count"]);
        Assert.Equal(0, score.Detail["bypass_attempt_count"]);
    }

    [Fact]
    public async Task McpToolUseScorer_FailsForbiddenToolAndBypassAttempts()
    {
        var scenario = ScenarioWithScoring(
            expectedCalls: [],
            forbiddenTools: ["http_raw_fetch"],
            allowBypass: false,
            finalResponseContains: ["cannot complete"]);
        var result = ResultWithOutput(new
        {
            tool_calls = new object[]
            {
                new { tool = "http_raw_fetch", arguments = new { url = "http://fake/admin/delete" }, result = new { status = 403 } }
            },
            bypass_attempts = new object[] { new { kind = "python_script", command = "python scrape.py" } },
            final_response = "Done."
        });

        var score = await new McpToolUseScorer().ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext());

        Assert.True(score.Success);
        Assert.False(score.Passed);
        Assert.Equal(0.0, score.Score!.Value);
        Assert.Contains("forbidden", score.HumanSummary);
        Assert.True((bool)score.Detail["forbidden_tool_used"]!);
        Assert.True((bool)score.Detail["bypass_violated"]!);
    }

    [Fact]
    public async Task FakeMcpCandidateRunner_RecordsToolCallsAndArtifacts()
    {
        var tempDir = Path.Combine(Path.GetTempPath(), "goblinbench-mcp-test-" + Guid.NewGuid().ToString("N"));
        var scenario = new Scenario
        {
            Id = "mcp-tools.customer-case-summary",
            Suite = "mcp-tools",
            Input = new Dictionary<string, object?>
            {
                ["scripted_tool_calls"] = JsonSerializer.SerializeToElement(new object[]
                {
                    new { tool = "records_lookup", arguments = new { customer = "Mira Chen" }, result = new { customer_id = "cust-1042" } }
                }),
                ["scripted_final_response"] = "Mira Chen maps to cust-1042."
            },
            TimeoutSeconds = 30
        };
        var context = new RunContext
        {
            RunId = "test-run",
            RunDirectory = tempDir,
            RunsRoot = tempDir,
            ScenarioId = scenario.Id
        };
        var candidate = new CandidateConfig { Id = "fake-mcp-scripted", Name = "Fake MCP Scripted", CliCommand = "fake-mcp-scripted" };

        var result = await new FakeMcpCandidateRunner().RunAsync(scenario, candidate, context);

        Assert.True(result.Success);
        Assert.Contains(result.Trace, e => e.Event == "fake_mcp.tool_called");
        var callsPath = Path.Combine(context.GetCandidateArtifactsDirectory(candidate.Id), "tool_calls.json");
        Assert.True(File.Exists(callsPath));
        var callsJson = await File.ReadAllTextAsync(callsPath);
        Assert.Contains("records_lookup", callsJson);
        Assert.Contains("cust-1042", JsonSerializer.Serialize(result.Output));
    }

    [Fact]
    public async Task McpToolUseScenarioFiles_AreDiscoverableAndUseMcpScorer()
    {
        var repoRoot = FindRepoRoot();
        var scenarios = await ScenarioDiscovery.DiscoverAsync(Path.Combine(repoRoot, "suites"));
        var mcpScenarios = scenarios.Where(s => s.Suite == "mcp-tools").ToList();

        Assert.True(mcpScenarios.Count >= 8);
        Assert.All(mcpScenarios, scenario =>
        {
            Assert.Contains("mcp-tool-use", scenario.Scoring!.Scorers);
            Assert.True(scenario.Input.ContainsKey("prompt"));
            Assert.True(scenario.Input.ContainsKey("fake_mcp"));
        });
    }

    private static Scenario ScenarioWithScoring(
        ExpectedCall[] expectedCalls,
        string[]? forbiddenTools = null,
        bool allowBypass = true,
        string[]? finalResponseContains = null)
    {
        var parameters = new Dictionary<string, object?>
        {
            ["expected_calls"] = JsonSerializer.SerializeToElement(expectedCalls.Select(c => new
            {
                tool = c.Tool,
                argument_contains = c.ArgumentContains
            })),
            ["allow_bypass"] = allowBypass,
            ["final_response_contains"] = JsonSerializer.SerializeToElement(finalResponseContains ?? Array.Empty<string>())
        };
        if (forbiddenTools != null)
            parameters["forbidden_tools"] = JsonSerializer.SerializeToElement(forbiddenTools);

        return new Scenario
        {
            Id = "mcp-tools.test",
            Suite = "mcp-tools",
            Scoring = new ScoringConfig
            {
                Scorers = ["mcp-tool-use"],
                Parameters = new() { ["mcp-tool-use"] = parameters },
                Thresholds = new() { ["mcp-tool-use"] = 0.8 }
            }
        };
    }

    private static CandidateResult ResultWithOutput(object output)
    {
        var json = JsonSerializer.Serialize(output, JsonOpts);
        var element = JsonSerializer.Deserialize<JsonElement>(json);
        return new CandidateResult
        {
            CandidateId = "c1",
            CandidateName = "candidate",
            CandidateKind = CandidateKind.Unknown,
            Success = true,
            Output = element,
            RawResponse = json
        };
    }

    private static RunContext TestContext() => new()
    {
        RunId = "test",
        RunDirectory = Path.Combine(Path.GetTempPath(), "goblinbench-mcp-test"),
        RunsRoot = Path.GetTempPath()
    };

    private static string FindRepoRoot()
    {
        var assemblyDir = Path.GetDirectoryName(typeof(McpToolUseSuiteTests).Assembly.Location)
            ?? AppContext.BaseDirectory;
        var dir = assemblyDir;
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir, "suites")) &&
                Directory.Exists(Path.Combine(dir, "src")))
                return dir;
            var parent = Path.GetDirectoryName(dir);
            if (parent == dir) break;
            dir = parent;
        }
        return assemblyDir;
    }

    private sealed record ExpectedCall(string Tool, Dictionary<string, string> ArgumentContains);
}
