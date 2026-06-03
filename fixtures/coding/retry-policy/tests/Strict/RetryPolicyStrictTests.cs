using Cases.RetryPolicy;

namespace Tests.Strict;

public sealed class RetryPolicyStrictTests
{
    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "retry-policy")]
    public void Parse_rejects_empty_segments_instead_of_silently_skipping_them()
    {
        Assert.Throws<FormatException>(() => RetryPolicyParser.Parse("250ms,,1s"));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "retry-policy")]
    public void Parse_keeps_jitter_flag_while_expanding_repeated_segments()
    {
        var policy = RetryPolicyParser.Parse("2x500ms jitter");

        Assert.True(policy.UseJitter);
        Assert.Equal([TimeSpan.FromMilliseconds(500), TimeSpan.FromMilliseconds(500)], policy.Delays);
    }
}
