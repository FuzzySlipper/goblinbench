using System.Text.Json;
using GoblinBench.Candidates;
using GoblinBench.Core;
using GoblinBench.Scorers;

namespace GoblinBench.Core.Tests;

public class McpToolBehaviorSuiteTests
{
    [Fact]
    public async Task McpToolUseScorer_FlagsNullAndEmptyOptionalParameterStuffing()
    {
        var scenario = ToolBehaviorScenario("tool-call-behavior.optional-parameter-minimalism", new Dictionary<string, object?>
        {
            ["expected_calls"] = JsonSerializer.SerializeToElement(new object[]
            {
                new { tool = "calendar_find_slots", argument_contains = new { attendee = "Mira", window = "Friday" } }
            }),
            ["optional_parameter_rules"] = JsonSerializer.SerializeToElement(new object[]
            {
                new
                {
                    tool = "calendar_find_slots",
                    optional_arguments = new[] { "timezone", "tags", "include_declined", "max_results" }
                }
            }),
            ["final_response_contains"] = JsonSerializer.SerializeToElement(new[] { "Mira" })
        });
        var result = ResultWithOutput(new
        {
            tool_calls = new object[]
            {
                new
                {
                    tool = "calendar_find_slots",
                    arguments = new
                    {
                        attendee = "Mira",
                        window = "Friday",
                        timezone = (string?)null,
                        tags = Array.Empty<string>(),
                        include_declined = (bool?)null,
                        max_results = (int?)null
                    },
                    result = new { ok = true, slots = new[] { "Friday 10:00" } }
                }
            },
            bypass_attempts = Array.Empty<object>(),
            final_response = "Mira has a Friday 10:00 slot."
        });

        var score = await new McpToolUseScorer().ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext());

        Assert.True(score.Success);
        Assert.False(score.Passed);
        Assert.True((bool)score.Detail["optional_parameter_violated"]!);
        Assert.Equal(4, score.Detail["optional_parameter_count"]);
        Assert.Equal(3, score.Detail["null_optional_parameter_count"]);
        Assert.Equal(1, score.Detail["empty_optional_array_count"]);
        Assert.Contains("optional_parameter_stuffing", (string[])score.Detail["failure_categories"]!);
    }

    [Fact]
    public async Task McpToolUseScorer_RecognizesGuidedErrorRecovery()
    {
        var scenario = ToolBehaviorScenario("tool-call-behavior.guided-error-recovery", new Dictionary<string, object?>
        {
            ["expected_calls"] = JsonSerializer.SerializeToElement(new object[]
            {
                new { tool = "issue_create", argument_contains = new { title = "Cache key expires", priority = "normal" } }
            }),
            ["expected_error_recovery"] = JsonSerializer.SerializeToElement(new
            {
                tool = "issue_create",
                guided_error_expected = true,
                required_guidance_contains = new[] { "priority must be one of", "omit optional fields" }
            }),
            ["final_response_contains"] = JsonSerializer.SerializeToElement(new[] { "ISSUE-42" })
        });
        var result = ResultWithOutput(new
        {
            tool_calls = new object[]
            {
                new
                {
                    tool = "issue_create",
                    arguments = new { title = "Cache key expires", priority = "urgent", labels = Array.Empty<string>() },
                    result = new
                    {
                        ok = false,
                        error = "validation failed",
                        use_suggestion = "priority must be one of low, normal, high; omit optional fields you do not need"
                    }
                },
                new
                {
                    tool = "issue_create",
                    arguments = new { title = "Cache key expires", priority = "normal" },
                    result = new { ok = true, issue_id = "ISSUE-42" }
                }
            },
            bypass_attempts = Array.Empty<object>(),
            final_response = "Created ISSUE-42."
        });

        var score = await new McpToolUseScorer().ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext());

        Assert.True(score.Success);
        Assert.True(score.Passed, score.Explanation);
        Assert.True((bool)score.Detail["guided_error_seen"]!);
        Assert.True((bool)score.Detail["recovered_after_error"]!);
        Assert.False((bool)score.Detail["repeated_invalid_call"]!);
        Assert.Equal(1, score.Detail["tool_error_count"]);
    }

    [Fact]
    public async Task McpToolUseScorer_FlagsUnnecessaryClarificationAndHallucinatedProjectArguments()
    {
        var scenario = ToolBehaviorScenario("den-mcp-ambiguity.den-mcp-doc-system-planner", new Dictionary<string, object?>
        {
            ["expected_calls"] = JsonSerializer.SerializeToElement(new object[]
            {
                new { tool = "mcp_den_store_document", argument_contains = new { project_id = "den-mcp", slug = "scheduler-report" } }
            }),
            ["forbidden_argument_values"] = JsonSerializer.SerializeToElement(new object[]
            {
                new { tool = "mcp_den_store_document", argument = "project_id", values = new[] { "den-system", "analyst" } }
            }),
            ["disallow_clarification"] = true,
            ["final_response_contains"] = JsonSerializer.SerializeToElement(new[] { "den-mcp" })
        });
        var result = ResultWithOutput(new
        {
            tool_calls = new object[]
            {
                new
                {
                    tool = "mcp_den_store_document",
                    arguments = new { project_id = "den-system", slug = "scheduler-report", title = "Scheduler Report" },
                    result = new { ok = true, fake_den_mcp = true, real_server_touched = false, document = new { project_id = "den-system", slug = "scheduler-report" } }
                }
            },
            bypass_attempts = Array.Empty<object>(),
            final_response = "Which den system project should I use?"
        });

        var score = await new McpToolUseScorer().ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext());

        Assert.True(score.Success);
        Assert.False(score.Passed);
        Assert.True((bool)score.Detail["clarification_violated"]!);
        Assert.True((bool)score.Detail["forbidden_argument_violated"]!);
        Assert.Equal(1, score.Detail["forbidden_argument_violation_count"]);
        Assert.Contains("unnecessary_clarification", (string[])score.Detail["failure_categories"]!);
        Assert.Contains("hallucinated_project_or_argument", (string[])score.Detail["failure_categories"]!);
    }

    [Fact]
    public async Task McpToolUseScorer_CanRequireClarificationForAmbiguousDestructiveRequests()
    {
        var scenario = ToolBehaviorScenario("den-mcp-ambiguity.clarify-destructive-doc-action", new Dictionary<string, object?>
        {
            ["expect_no_tool_calls"] = true,
            ["require_clarification"] = true,
            ["final_response_contains"] = JsonSerializer.SerializeToElement(new[] { "archive", "note" })
        });
        var result = ResultWithOutput(new
        {
            tool_calls = Array.Empty<object>(),
            bypass_attempts = Array.Empty<object>(),
            final_response = "Do you want me to archive the document, or only add a note to discuss it?"
        });

        var score = await new McpToolUseScorer().ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext());

        Assert.True(score.Success);
        Assert.True(score.Passed, score.Explanation);
        Assert.True((bool)score.Detail["clarification_required"]!);
        Assert.True((bool)score.Detail["clarification_seen"]!);
        Assert.False((bool)score.Detail["clarification_violated"]!);
    }

    [Fact]
    public async Task McpToolUseScorer_DoesNotCountNestedContentTextAsProjectRoutingArgument()
    {
        var scenario = ToolBehaviorScenario("den-mcp-ambiguity.project-explicit-report-doc", new Dictionary<string, object?>
        {
            ["expected_calls"] = JsonSerializer.SerializeToElement(new object[]
            {
                new { tool = "mcp_den_store_document", argument_contains = new { project_id = "goblinbench", slug = "local-model-overclarification-note" } }
            }),
            ["final_response_contains"] = JsonSerializer.SerializeToElement(new[] { "goblinbench" })
        });
        var result = ResultWithOutput(new
        {
            tool_calls = new object[]
            {
                new
                {
                    tool = "mcp_den_store_document",
                    arguments = new
                    {
                        project_id = "_global",
                        slug = "local-model-overclarification-note",
                        content = "This note talks about the GoblinBench suite."
                    },
                    result = new { ok = true }
                }
            },
            bypass_attempts = Array.Empty<object>(),
            final_response = "Saved in goblinbench."
        });

        var score = await new McpToolUseScorer().ScoreAsync(scenario, new() { Id = "c1" }, result, TestContext());

        Assert.True(score.Success);
        Assert.Equal(0, score.Detail["argument_match_count"]);
        Assert.False(score.Passed);
        Assert.Contains("argument_grounding_failure", (string[])score.Detail["failure_categories"]!);
    }

    [Fact]
    public async Task ToolBehaviorScenarioFiles_AreDiscoverableAndUseMcpScorer()
    {
        var repoRoot = FindRepoRoot();
        var scenarios = await ScenarioDiscovery.DiscoverAsync(Path.Combine(repoRoot, "suites"));
        var behaviorScenarios = scenarios.Where(s => s.Suite == "tool-call-behavior").ToList();

        Assert.True(behaviorScenarios.Count >= 4);
        Assert.Contains(behaviorScenarios, s => s.Id == "tool-call-behavior.optional-parameter-minimalism");
        Assert.Contains(behaviorScenarios, s => s.Id == "tool-call-behavior.guided-error-recovery");
        Assert.Contains(behaviorScenarios, s => s.Id == "tool-call-behavior.bare-error-recovery-control");
        Assert.Contains(behaviorScenarios, s => s.Id == "tool-call-behavior.null-optional-write-trap");
        Assert.All(behaviorScenarios, scenario => Assert.Contains("mcp-tool-use", scenario.Scoring!.Scorers));
    }

    private static Scenario ToolBehaviorScenario(string id, Dictionary<string, object?> parameters) => new()
    {
        Id = id,
        Suite = "tool-call-behavior",
        Scoring = new ScoringConfig
        {
            Scorers = ["mcp-tool-use"],
            Parameters = new() { ["mcp-tool-use"] = parameters },
            Thresholds = new() { ["mcp-tool-use"] = 0.8 }
        }
    };

    private static CandidateResult ResultWithOutput(object output)
    {
        var json = JsonSerializer.Serialize(output);
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
        RunDirectory = Path.Combine(Path.GetTempPath(), "goblinbench-tool-behavior-test"),
        RunsRoot = Path.GetTempPath()
    };

    private static string FindRepoRoot()
    {
        var dir = AppContext.BaseDirectory;
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir, "suites")) && Directory.Exists(Path.Combine(dir, "src")))
                return dir;
            dir = Directory.GetParent(dir)?.FullName;
        }
        throw new DirectoryNotFoundException("Could not locate repo root.");
    }
}
