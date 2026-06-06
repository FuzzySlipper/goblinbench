using GoblinBench.Core;

namespace GoblinBench.Core.Tests;

public class RunContextTests
{
    [Fact]
    public void GetCandidateDirectory_SanitisesFilename()
    {
        var ctx = new RunContext
        {
            RunId = "test-run",
            RunDirectory = "/tmp/goblinbench/runs/test-run",
            RunsRoot = "/tmp/goblinbench/runs"
        };

        var dir = ctx.GetCandidateDirectory("candidate/with/slashes");
        // On all platforms, path separators must be stripped
        Assert.DoesNotContain("/", Path.GetFileName(dir));
    }

    [Fact]
    public void GetCandidateDirectory_ReturnsExpectedPath()
    {
        var ctx = new RunContext
        {
            RunId = "test-run",
            RunDirectory = "/tmp/goblinbench/runs/test-run",
            RunsRoot = "/tmp/goblinbench/runs"
        };

        var dir = ctx.GetCandidateDirectory("gpt4o");
        Assert.Equal("/tmp/goblinbench/runs/test-run/candidates/gpt4o", dir);
    }

    [Fact]
    public void GetCandidateDirectory_WhenScenarioIdIsSet_IsolatesArtifactsByScenario()
    {
        var ctx = new RunContext
        {
            RunId = "test-run",
            RunDirectory = "/tmp/goblinbench/runs/test-run",
            RunsRoot = "/tmp/goblinbench/runs",
            ScenarioId = "coding.cache-key"
        };

        var dir = ctx.GetCandidateDirectory("coding-scripted");

        Assert.Equal("/tmp/goblinbench/runs/test-run/scenarios/coding.cache-key/candidates/coding-scripted", dir);
    }

    [Fact]
    public void GetCandidateOutputPath_ReturnsExpectedFile()
    {
        var ctx = new RunContext
        {
            RunId = "test-run",
            RunDirectory = "/tmp/goblinbench/runs/test-run"
        };

        var path = ctx.GetCandidateOutputPath("gpt4o");
        Assert.EndsWith("output.json", path);
        Assert.Contains("gpt4o", path);
    }

    [Fact]
    public void GetCandidateTracePath_ReturnsExpectedFile()
    {
        var ctx = new RunContext
        {
            RunId = "test-run",
            RunDirectory = "/tmp/goblinbench/runs/test-run"
        };

        var path = ctx.GetCandidateTracePath("claude");
        Assert.EndsWith("trace.jsonl", path);
        Assert.Contains("claude", path);
    }

    [Fact]
    public void GetCandidateScoresPath_ReturnsExpectedFile()
    {
        var ctx = new RunContext
        {
            RunId = "test-run",
            RunDirectory = "/tmp/goblinbench/runs/test-run"
        };

        var path = ctx.GetCandidateScoresPath("deepseek");
        Assert.EndsWith("scores.json", path);
        Assert.Contains("deepseek", path);
    }
}
