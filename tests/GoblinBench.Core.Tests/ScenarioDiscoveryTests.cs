using GoblinBench.Core;

namespace GoblinBench.Core.Tests;

public class ScenarioDiscoveryTests
{
    [Fact]
    public async Task DiscoverAsync_EmptyDirectory_ReturnsEmpty()
    {
        var tmpDir = Path.Combine(Path.GetTempPath(), $"gb-test-{Guid.NewGuid():N}");
        Directory.CreateDirectory(tmpDir);
        try
        {
            var scenarios = await ScenarioDiscovery.DiscoverAsync(tmpDir);
            Assert.Empty(scenarios);
        }
        finally
        {
            Directory.Delete(tmpDir, recursive: true);
        }
    }

    [Fact]
    public async Task DiscoverAsync_NonexistentDirectory_ReturnsEmpty()
    {
        var scenarios = await ScenarioDiscovery.DiscoverAsync(
            "/tmp/goblinbench-nonexistent-dir-hopefully");
        Assert.Empty(scenarios);
    }

    [Fact]
    public async Task DiscoverAsync_FindsScenarioJson()
    {
        var tmpDir = Path.Combine(Path.GetTempPath(), $"gb-test-{Guid.NewGuid():N}");
        var suiteDir = Path.Combine(tmpDir, "demo");
        Directory.CreateDirectory(suiteDir);

        var scenarioJson = """
        {
          "id": "discovery-test",
          "version": "1.0.0",
          "name": "Discovery Test",
          "suite": "demo",
          "input": { "key": "value" },
          "timeout_seconds": 30
        }
        """;
        await File.WriteAllTextAsync(
            Path.Combine(suiteDir, "discovery-test.json"), scenarioJson);

        try
        {
            var scenarios = await ScenarioDiscovery.DiscoverAsync(tmpDir);
            Assert.Single(scenarios);
            Assert.Equal("discovery-test", scenarios[0].Id);
            Assert.Equal("demo", scenarios[0].Suite);
            Assert.Equal("1.0.0", scenarios[0].Version);
        }
        finally
        {
            Directory.Delete(tmpDir, recursive: true);
        }
    }

    [Fact]
    public async Task DiscoverAsync_FindsNestedScenarioJson()
    {
        var tmpDir = Path.Combine(Path.GetTempPath(), $"gb-test-{Guid.NewGuid():N}");
        var scenarioDir = Path.Combine(tmpDir, "demo", "nested-test");
        Directory.CreateDirectory(scenarioDir);

        var scenarioJson = """
        {
          "id": "nested-test",
          "version": "1.0.0",
          "name": "Nested Scenario",
          "suite": "demo",
          "input": {},
          "timeout_seconds": 30
        }
        """;
        await File.WriteAllTextAsync(
            Path.Combine(scenarioDir, "scenario.json"), scenarioJson);

        try
        {
            var scenarios = await ScenarioDiscovery.DiscoverAsync(tmpDir);
            Assert.Single(scenarios);
            Assert.Equal("nested-test", scenarios[0].Id);
        }
        finally
        {
            Directory.Delete(tmpDir, recursive: true);
        }
    }
}
