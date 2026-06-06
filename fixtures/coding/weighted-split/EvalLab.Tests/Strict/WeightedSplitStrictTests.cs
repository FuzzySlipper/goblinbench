using EvalLab.Core.Cases.WeightedSplit;

namespace EvalLab.Tests.Strict;

public sealed class WeightedSplitStrictTests
{
    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "weighted-split")]
    public void Split_assigns_remainder_to_largest_fractional_share()
    {
        // floors: [33, 66] = 99; remainder 1 goes to index 1 (frac 2/3 > 1/3).
        var result = WeightedSplitCalculator.Split(100, [1, 2]);

        Assert.Equal([33L, 67L], result);
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "weighted-split")]
    public void Split_handles_single_recipient()
    {
        var result = WeightedSplitCalculator.Split(123, [7]);

        Assert.Equal([123L], result);
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "weighted-split")]
    public void Split_excludes_zero_weighted_recipients()
    {
        var result = WeightedSplitCalculator.Split(100, [0, 1, 1]);

        Assert.Equal([0L, 50L, 50L], result);
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "weighted-split")]
    public void Split_is_overflow_safe_for_large_totals()
    {
        // 7e18 * 3 overflows long; correct result requires careful arithmetic.
        // 7e18 / 8 = 875_000_000_000_000_000; *3 and *5 give an exact partition.
        var result = WeightedSplitCalculator.Split(
            7_000_000_000_000_000_000L,
            [3, 5]);

        Assert.Equal(
            [2_625_000_000_000_000_000L, 4_375_000_000_000_000_000L],
            result);
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "weighted-split")]
    public void Split_preserves_total_across_many_recipients()
    {
        var weights = Enumerable.Repeat(1, 100).ToArray();

        var result = WeightedSplitCalculator.Split(101, weights);

        Assert.Equal(100, result.Count);
        Assert.Equal(101L, result.Sum());
        Assert.Equal(1, result.Count(share => share == 2));
        Assert.Equal(99, result.Count(share => share == 1));
        Assert.Equal(2L, result[0]);
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "weighted-split")]
    public void Split_rejects_zero_only_weights()
    {
        Assert.Throws<ArgumentException>(() => WeightedSplitCalculator.Split(25, [0, 0]));
    }
}
