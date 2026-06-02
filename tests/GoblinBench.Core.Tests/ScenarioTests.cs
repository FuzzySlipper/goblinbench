using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Core.Tests;

public class ScenarioTests
{
    [Fact]
    public void Scenario_DefaultValues_AreSane()
    {
        var scenario = new Scenario { Id = "test-1", Name = "Test Scenario" };

        Assert.Equal("test-1", scenario.Id);
        Assert.Equal("Test Scenario", scenario.Name);
        Assert.Equal("1.0.0", scenario.Version);
        Assert.Empty(scenario.Description);
        Assert.Empty(scenario.Suite);
        Assert.Empty(scenario.Input);
        Assert.Null(scenario.Fixture);
        Assert.Null(scenario.Scoring);
        Assert.Equal(0, scenario.TimeoutSeconds);
    }

    [Fact]
    public void Scenario_DeserializesCorrectly()
    {
        var json = """
        {
          "id": "vision-ui.login-error",
          "version": "2.0.0",
          "name": "Login Error Banner Detection",
          "description": "Can the model detect a visible error banner on a login screen?",
          "suite": "vision",
          "input": { "screenshot_path": "fixtures/login-error.png" },
          "fixture": {
            "setup_commands": ["echo setup"],
            "teardown_commands": ["echo teardown"],
            "provision_files": {}
          },
          "scoring": {
            "scorers": ["exact-match", "llm-judge"],
            "parameters": {
              "exact-match": { "expected": "error_banner_visible" }
            }
          },
          "timeout_seconds": 60
        }
        """;

        var scenario = JsonSerializer.Deserialize<Scenario>(json,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });

        Assert.NotNull(scenario);
        Assert.Equal("vision-ui.login-error", scenario!.Id);
        Assert.Equal("2.0.0", scenario.Version);
        Assert.Equal("Login Error Banner Detection", scenario.Name);
        Assert.Equal("vision", scenario.Suite);
        Assert.Equal(60, scenario.TimeoutSeconds);
        Assert.NotNull(scenario.Input);
        Assert.Equal("fixtures/login-error.png", scenario.Input["screenshot_path"]?.ToString());
        Assert.NotNull(scenario.Fixture);
        Assert.Single(scenario.Fixture!.SetupCommands);
        Assert.NotNull(scenario.Scoring);
        Assert.Equal(2, scenario.Scoring!.Scorers.Count);
    }

    [Fact]
    public void Scenario_SerializesRoundTrip()
    {
        var scenario = new Scenario
        {
            Id = "test-roundtrip",
            Version = "1.0.0",
            Name = "Round-trip Test",
            Suite = "test",
            Input = new Dictionary<string, object?> { ["key"] = "value" },
            TimeoutSeconds = 30
        };

        var json = JsonSerializer.Serialize(scenario,
            new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
        var deserialized = JsonSerializer.Deserialize<Scenario>(json,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });

        Assert.NotNull(deserialized);
        Assert.Equal(scenario.Id, deserialized!.Id);
        Assert.Equal(scenario.Version, deserialized.Version);
        Assert.Equal(scenario.Name, deserialized.Name);
        Assert.Equal(scenario.Suite, deserialized.Suite);
        Assert.Equal(scenario.TimeoutSeconds, deserialized.TimeoutSeconds);
    }
}
