using EvalLab.Core.Cases.WeightedSplit;

namespace EvalLab.Tests.Visible;

public sealed class WeightedSplitVisibleTests
{
    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "weighted-split")]
    public void Split_distributes_simple_even_amounts()
    {
        var result = WeightedSplitCalculator.Split(100, [1, 1]);

        Assert.Equal([50L, 50L], result);
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "weighted-split")]
    public void Split_assigns_remainder_from_left_to_right()
    {
        var result = WeightedSplitCalculator.Split(101, [1, 1]);

        Assert.Equal([51L, 50L], result);
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "weighted-split")]
    public void Split_handles_clean_proportional_division()
    {
        var result = WeightedSplitCalculator.Split(100, [3, 7]);

        Assert.Equal([30L, 70L], result);
    }
}
