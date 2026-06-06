using EvalLab.Core.Cases.TreePrune;
using EvalLab.Tests.Support;

namespace EvalLab.Tests.Strict;

public sealed class TreePruneStrictTests
{
    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "tree-prune")]
    public void Prune_preserves_order_across_promoted_descendants()
    {
        // 10's children: [1(kept), -2(removed, children [20, 21]), 3(kept), -4(removed, children [40]), 5(kept)]
        // expected: 10(1, 20, 21, 3, 40, 5)
        var forest = new List<Node>
        {
            new(10,
                new Node(1),
                new Node(-2, new Node(20), new Node(21)),
                new Node(3),
                new Node(-4, new Node(40)),
                new Node(5)),
        };

        var result = Pruner.Prune(forest, v => v < 0);

        Assert.Equal("[10(1,20,21,3,40,5)]", TreeSerialize.Forest(result));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "tree-prune")]
    public void Prune_handles_chain_of_two_removals()
    {
        // 1 → -2 → -3 → 7  ("remove if negative")
        // -2 and -3 removed; 7 should bubble up to be a child of 1.
        var forest = new List<Node>
        {
            new(1,
                new Node(-2,
                    new Node(-3,
                        new Node(7)))),
        };

        var result = Pruner.Prune(forest, v => v < 0);

        Assert.Equal("[1(7)]", TreeSerialize.Forest(result));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "tree-prune")]
    public void Prune_handles_chain_of_three_removals()
    {
        // 1 → -2 → -3 → -4 → 7  ("remove if negative")
        // 7 bubbles up three levels.
        var forest = new List<Node>
        {
            new(1,
                new Node(-2,
                    new Node(-3,
                        new Node(-4,
                            new Node(7))))),
        };

        var result = Pruner.Prune(forest, v => v < 0);

        Assert.Equal("[1(7)]", TreeSerialize.Forest(result));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "tree-prune")]
    public void Prune_root_removal_promotes_children_to_forest()
    {
        // root -1 removed; its children (2, 3) become independent roots.
        var forest = new List<Node>
        {
            new(-1, new Node(2), new Node(3)),
        };

        var result = Pruner.Prune(forest, v => v < 0);

        Assert.Equal("[2,3]", TreeSerialize.Forest(result));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "tree-prune")]
    public void Prune_root_removal_in_multi_tree_forest_preserves_position()
    {
        // input forest: [-1(2), 3, -4(5, 6)]
        // -1 removed → 2 takes its slot
        // 3 kept
        // -4 removed → 5, 6 take its slot
        // expected: [2, 3, 5, 6]
        var forest = new List<Node>
        {
            new(-1, new Node(2)),
            new(3),
            new(-4, new Node(5), new Node(6)),
        };

        var result = Pruner.Prune(forest, v => v < 0);

        Assert.Equal("[2,3,5,6]", TreeSerialize.Forest(result));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "tree-prune")]
    public void Prune_all_removed_returns_empty()
    {
        var forest = new List<Node>
        {
            new(-1, new Node(-2), new Node(-3)),
        };

        var result = Pruner.Prune(forest, v => v < 0);

        Assert.Equal("[]", TreeSerialize.Forest(result));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "tree-prune")]
    public void Prune_handles_deep_scattered_removals()
    {
        // 1
        // ├── 2
        // │   ├── -3
        // │   │   ├── 4
        // │   │   └── 5
        // │   └── 6
        // ├── -7
        // │   ├── 8
        // │   └── -9
        // │       └── 10
        // expected: 1(2(4, 5, 6), 8, 10)
        var forest = new List<Node>
        {
            new(1,
                new Node(2,
                    new Node(-3, new Node(4), new Node(5)),
                    new Node(6)),
                new Node(-7,
                    new Node(8),
                    new Node(-9, new Node(10)))),
        };

        var result = Pruner.Prune(forest, v => v < 0);

        Assert.Equal("[1(2(4,5,6),8,10)]", TreeSerialize.Forest(result));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "tree-prune")]
    public void Prune_does_not_mutate_input()
    {
        var forest = new List<Node>
        {
            new(1,
                new Node(2, new Node(5), new Node(6)),
                new Node(-3, new Node(7), new Node(8)),
                new Node(4)),
        };
        var before = TreeSerialize.Forest(forest);

        _ = Pruner.Prune(forest, v => v < 0);

        var after = TreeSerialize.Forest(forest);
        Assert.Equal(before, after);
    }
}
