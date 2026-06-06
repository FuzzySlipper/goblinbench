using EvalLab.Core.Cases.TreePrune;
using EvalLab.Tests.Support;

namespace EvalLab.Tests.Visible;

public sealed class TreePruneVisibleTests
{
    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "tree-prune")]
    public void Prune_empty_forest_returns_empty()
    {
        var result = Pruner.Prune(new List<Node>(), v => v < 0);

        Assert.Equal("[]", TreeSerialize.Forest(result));
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "tree-prune")]
    public void Prune_with_no_matches_returns_equivalent_structure()
    {
        var forest = new List<Node>
        {
            new(1, new Node(2), new Node(3)),
            new(4),
        };

        var result = Pruner.Prune(forest, v => v > 100);

        Assert.Equal("[1(2,3),4]", TreeSerialize.Forest(result));
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "tree-prune")]
    public void Prune_leaf_removal_keeps_siblings()
    {
        var forest = new List<Node>
        {
            new(1, new Node(2), new Node(-3), new Node(4)),
        };

        var result = Pruner.Prune(forest, v => v < 0);

        Assert.Equal("[1(2,4)]", TreeSerialize.Forest(result));
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "tree-prune")]
    public void Prune_promotes_surviving_descendants_into_parent()
    {
        // 1
        // ├── 2 (kept) → (5, 6)
        // ├── -3 (removed) → (7, 8) promoted into 1's children at -3's slot
        // └── 4 (kept)
        var forest = new List<Node>
        {
            new(1,
                new Node(2, new Node(5), new Node(6)),
                new Node(-3, new Node(7), new Node(8)),
                new Node(4)),
        };

        var result = Pruner.Prune(forest, v => v < 0);

        Assert.Equal("[1(2(5,6),7,8,4)]", TreeSerialize.Forest(result));
    }
}
