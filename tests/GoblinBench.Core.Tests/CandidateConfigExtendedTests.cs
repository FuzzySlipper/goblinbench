using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Core.Tests;

public class CandidateConfigExtendedTests
{
    [Fact]
    public void CandidateConfig_NewFields_DeserializeCorrectly()
    {
        var json = """
        {
          "id": "gpt4o-custom",
          "name": "GPT-4o Custom",
          "kind": "openAiModel",
          "model": "gpt-4o",
          "provider": "openai",
          "base_url": "https://custom.api.example.com/v1",
          "system_prompt": "You are a helpful benchmark evaluator.",
          "runtime_metadata": {
            "prompt_version": "v1",
            "runner_version": "0.1.0",
            "host": "den-k8"
          },
          "config": { "temperature": 0.3 }
        }
        """;

        var candidate = JsonSerializer.Deserialize<CandidateConfig>(json,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });

        Assert.NotNull(candidate);
        Assert.Equal("gpt4o-custom", candidate!.Id);
        Assert.Equal(CandidateKind.OpenAiModel, candidate!.Kind);
        Assert.Equal("gpt-4o", candidate.Model);
        Assert.Equal("openai", candidate.Provider);
        Assert.Equal("https://custom.api.example.com/v1", candidate.BaseUrl);
        Assert.Equal("You are a helpful benchmark evaluator.", candidate.SystemPrompt);
        Assert.NotNull(candidate.RuntimeMetadata);
        Assert.Equal("v1", candidate.RuntimeMetadata["prompt_version"]);
        Assert.Equal("0.1.0", candidate.RuntimeMetadata["runner_version"]);
        Assert.Equal("den-k8", candidate.RuntimeMetadata["host"]);
    }

    [Fact]
    public void CandidateConfig_ApiKeyEnv_NotSerialized()
    {
        var candidate = new CandidateConfig
        {
            Id = "test",
            Name = "Test",
            ApiKeyEnv = "MY_SECRET_KEY",
            ApiKey = "sk-actual-key-value"
        };

        var json = JsonSerializer.Serialize(candidate,
            new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });

        // Secret fields must not appear in serialized output
        Assert.DoesNotContain("apiKeyEnv", json);
        Assert.DoesNotContain("MY_SECRET_KEY", json);
        Assert.DoesNotContain("sk-actual", json);
        Assert.DoesNotContain("api_key_env", json);
    }

    [Fact]
    public void CandidateConfig_ApiKey_NotSerialized()
    {
        var candidate = new CandidateConfig
        {
            Id = "test",
            Name = "Test",
            ApiKey = "sk-super-secret-do-not-leak"
        };

        var json = JsonSerializer.Serialize(candidate,
            new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });

        Assert.DoesNotContain("sk-super-secret", json);
        Assert.DoesNotContain("apiKey", json);
    }

    [Fact]
    public void CandidateConfig_SerializableFields_ArePresent()
    {
        var candidate = new CandidateConfig
        {
            Id = "test",
            Name = "Test",
            Kind = CandidateKind.OpenAiModel,
            Model = "gpt-4o",
            Provider = "openai",
            BaseUrl = "https://api.openai.com/v1",
            ApiKeyEnv = "SECRET_ENV",   // should NOT appear
            ApiKey = "sk-12345",         // should NOT appear
            RuntimeMetadata = new Dictionary<string, string>
            {
                ["prompt_version"] = "v2"
            }
        };

        var json = JsonSerializer.Serialize(candidate,
            new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });

        Assert.Contains("\"id\"", json);
        Assert.Contains("\"name\"", json);
        Assert.Contains("\"kind\"", json);
        Assert.Contains("\"model\"", json);
        Assert.Contains("\"base_url\"", json);
        Assert.Contains("\"runtime_metadata\"", json);
        Assert.Contains("\"prompt_version\"", json);
        Assert.Contains("v2", json);

        // Secrets absent
        Assert.DoesNotContain("SECRET_ENV", json);
        Assert.DoesNotContain("sk-12345", json);
    }

    [Fact]
    public void ModelIdentity_SerializesCorrectly()
    {
        var identity = new ModelIdentity
        {
            Model = "gpt-4o",
            Provider = "openai",
            BaseUrl = "https://api.openai.com/v1",
            DisplayName = "OpenAI GPT-4o"
        };

        var json = JsonSerializer.Serialize(identity,
            new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });

        Assert.Contains("\"model\"", json);
        Assert.Contains("gpt-4o", json);
        Assert.Contains("openai", json);
        Assert.Contains("\"base_url\"", json);
        Assert.Contains("\"display_name\"", json);
        Assert.Contains("OpenAI GPT-4o", json);
    }

    [Fact]
    public void CandidateResult_WithModelIdentity_SerializesCorrectly()
    {
        var result = new CandidateResult
        {
            CandidateId = "gpt4o",
            CandidateName = "GPT-4o",
            CandidateKind = CandidateKind.OpenAiModel,
            ModelIdentity = new ModelIdentity
            {
                Model = "gpt-4o",
                Provider = "openai",
                BaseUrl = "https://api.openai.com/v1"
            },
            Success = true,
            DurationMs = 1234,
            RawResponse = "Hello, world!",
            ParsedResponse = new { answer = "Hello, world!" }
        };

        var json = JsonSerializer.Serialize(result,
            new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });

        Assert.Contains("\"model_identity\"", json);
        Assert.Contains("gpt-4o", json);
        Assert.Contains("\"raw_response\"", json);
        Assert.Contains("Hello, world!", json);
        Assert.Contains("1234", json);
    }
}
