using Cases.RetryPolicy;

namespace Tests.Visible;

public sealed class RetryPolicyVisibleTests
{
    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "retry-policy")]
    public void Parse_supports_compact_repeat_tokens()
    {
        var policy = RetryPolicyParser.Parse("3x250ms");

        Assert.Equal(
            [TimeSpan.FromMilliseconds(250), TimeSpan.FromMilliseconds(250), TimeSpan.FromMilliseconds(250)],
            policy.Delays);
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "retry-policy")]
    public void Parse_supports_mixed_duration_lists()
    {
        var policy = RetryPolicyParser.Parse("250ms, 1s, 2s");

        Assert.Equal(
            [TimeSpan.FromMilliseconds(250), TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(2)],
            policy.Delays);
    }
}
