using GoblinBench.Candidates;

namespace GoblinBench.Core.Tests;

public class SecretRedactionTests
{
    [Fact]
    public void RedactSecrets_RedactsBearerToken()
    {
        var input = "Authorization: Bearer sK-test123-moretext";
        var result = OpenAiChatRunner.RedactSecrets(input);
        Assert.DoesNotContain("sK-tes", result);
        Assert.Contains("[REDACTED]", result);
        Assert.Contains("Authorization", result);
    }

    [Fact]
    public void RedactSecrets_RedactsApiKeyHeader()
    {
        var input = "x-api-key: my-secret-key-12345";
        var result = OpenAiChatRunner.RedactSecrets(input);
        Assert.DoesNotContain("my-secret-key-12345", result);
        Assert.Contains("[REDACTED]", result);
    }

    [Fact]
    public void RedactSecrets_RedactsApiKeyEquals()
    {
        var input = "api_key=sk-abc123";
        var result = OpenAiChatRunner.RedactSecrets(input);
        Assert.Contains("api_key=[REDACTED]", result);
        Assert.DoesNotContain("sk-abc123", result);
    }

    [Fact]
    public void RedactSecrets_NoSecretsUnchanged()
    {
        var input = "no secrets here";
        var result = OpenAiChatRunner.RedactSecrets(input);
        Assert.Equal("no secrets here", result);
    }

    [Fact]
    public void RedactSecrets_EmptyString()
    {
        var result = OpenAiChatRunner.RedactSecrets("");
        Assert.Equal("", result);
    }

    [Fact]
    public void RedactSecrets_NullInput_ReturnsNull()
    {
        var result = OpenAiChatRunner.RedactSecrets(null!);
        Assert.Null(result);
    }

    [Fact]
    public void RedactSecrets_PreservesNonSecretContent()
    {
        var input = "Model: gpt-4o, Status: ok, Latency: 1234ms, api_key=secret";
        var result = OpenAiChatRunner.RedactSecrets(input);
        Assert.Contains("Model: gpt-4o", result);
        Assert.Contains("Status: ok", result);
        Assert.Contains("Latency: 1234ms", result);
        Assert.Contains("[REDACTED]", result);
        Assert.DoesNotContain("secret", result);
    }
}
