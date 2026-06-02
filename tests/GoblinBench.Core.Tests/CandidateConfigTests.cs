using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Core.Tests;

public class CandidateConfigTests
{
    [Fact]
    public void CandidateConfig_DefaultValues_AreSane()
    {
        var candidate = new CandidateConfig { Id = "c1", Name = "Test Candidate" };

        Assert.Equal("c1", candidate.Id);
        Assert.Equal("Test Candidate", candidate.Name);
        Assert.Equal(CandidateKind.Unknown, candidate.Kind);
        Assert.Null(candidate.Model);
        Assert.Null(candidate.Provider);
        Assert.Null(candidate.Endpoint);
        Assert.Null(candidate.Profile);
        Assert.Null(candidate.CliCommand);
        Assert.Empty(candidate.CliArgs);
        Assert.Empty(candidate.Config);
    }

    [Fact]
    public void CandidateConfig_DeserializesCorrectly()
    {
        var json = """
        {
          "id": "gpt4o-direct",
          "name": "GPT-4o Direct",
          "kind": "openAiModel",
          "model": "gpt-4o",
          "provider": "openai",
          "system_prompt": "You are a helpful assistant.",
          "config": { "temperature": 0.7, "max_tokens": 4096 }
        }
        """;

        var candidate = JsonSerializer.Deserialize<CandidateConfig>(json,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });

        Assert.NotNull(candidate);
        Assert.Equal("gpt4o-direct", candidate!.Id);
        Assert.Equal(CandidateKind.OpenAiModel, candidate.Kind);
        Assert.Equal("gpt-4o", candidate.Model);
        Assert.Equal("openai", candidate.Provider);
        Assert.Equal("You are a helpful assistant.", candidate.SystemPrompt);
        Assert.NotNull(candidate.Config);
        Assert.Equal(0.7, ((JsonElement)candidate.Config["temperature"]!).GetDouble());
    }

    [Theory]
    [InlineData("openAiModel", CandidateKind.OpenAiModel)]
    [InlineData("hermesProfile", CandidateKind.HermesProfile)]
    [InlineData("serviceEndpoint", CandidateKind.ServiceEndpoint)]
    [InlineData("externalCli", CandidateKind.ExternalCli)]
    [InlineData("localModel", CandidateKind.LocalModel)]
    [InlineData("unknown", CandidateKind.Unknown)]
    public void CandidateConfig_EnumDeserialization(string jsonValue, CandidateKind expected)
    {
        var json = $$"""{"id":"x","name":"x","kind":"{{jsonValue}}"}""";
        var candidate = JsonSerializer.Deserialize<CandidateConfig>(json,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });

        Assert.NotNull(candidate);
        Assert.Equal(expected, candidate!.Kind);
    }
}
