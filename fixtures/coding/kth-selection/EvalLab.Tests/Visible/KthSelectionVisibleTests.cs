using EvalLab.Core.Cases.KthSelection;

namespace EvalLab.Tests.Visible;

public sealed class KthSelectionVisibleTests
{
    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "kth-selection")]
    public void KthSmallest_finds_minimum()
    {
        Assert.Equal(1, Selector.KthSmallest([3, 1, 2], 1));
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "kth-selection")]
    public void KthSmallest_finds_middle()
    {
        Assert.Equal(2, Selector.KthSmallest([3, 1, 2], 2));
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "kth-selection")]
    public void KthSmallest_finds_maximum()
    {
        Assert.Equal(3, Selector.KthSmallest([3, 1, 2], 3));
    }
}
