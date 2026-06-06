using EvalLab.Core.Cases.KthSelection;

namespace EvalLab.Tests.Strict;

public sealed class KthSelectionStrictTests
{
    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "kth-selection")]
    public void KthSmallest_does_not_mutate_input()
    {
        var arr = new[] { 3, 1, 4, 1, 5, 9, 2, 6 };
        var snapshot = (int[])arr.Clone();

        _ = Selector.KthSmallest(arr, 3);

        Assert.Equal(snapshot, arr);
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "kth-selection")]
    public void KthSmallest_handles_duplicates_at_rank()
    {
        // sorted [1, 1, 1, 2, 3], k=2 → 1
        Assert.Equal(1, Selector.KthSmallest([1, 1, 2, 3, 1], 2));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "kth-selection")]
    public void KthSmallest_handles_all_identical()
    {
        Assert.Equal(5, Selector.KthSmallest([5, 5, 5, 5, 5], 3));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "kth-selection")]
    public void KthSmallest_handles_single_element()
    {
        Assert.Equal(42, Selector.KthSmallest([42], 1));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "kth-selection")]
    public void KthSmallest_handles_negative_and_positive_mix()
    {
        // sorted [-8, -3, -1, 0, 4, 7], k=2 → -3
        Assert.Equal(-3, Selector.KthSmallest([-3, 0, 7, -8, 4, -1], 2));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "kth-selection")]
    public void KthSmallest_handles_already_sorted_input()
    {
        Assert.Equal(7, Selector.KthSmallest([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 7));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "kth-selection")]
    public void KthSmallest_handles_reverse_sorted_input()
    {
        Assert.Equal(3, Selector.KthSmallest([10, 9, 8, 7, 6, 5, 4, 3, 2, 1], 3));
    }

    [Theory]
    [Trait("Suite", "Strict")]
    [Trait("Case", "kth-selection")]
    [InlineData(0)]
    [InlineData(-1)]
    [InlineData(11)]
    public void KthSmallest_rejects_out_of_range_k(int k)
    {
        var arr = new[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 };

        Assert.Throws<ArgumentOutOfRangeException>(() => Selector.KthSmallest(arr, k));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "kth-selection")]
    public void KthSmallest_rejects_empty_array()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => Selector.KthSmallest([], 1));
    }
}
