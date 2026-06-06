namespace EvalLab.Core.Cases.TreePrune;

public sealed class Node
{
    public int Value { get; set; }
    public List<Node> Children { get; set; }

    public Node(int value)
    {
        Value = value;
        Children = new List<Node>();
    }

    public Node(int value, params Node[] children)
    {
        Value = value;
        Children = children.ToList();
    }
}

public static class Pruner
{
    // Baseline: filters recursively, dropping entire subtrees on removal.
    // Promotion of surviving descendants is missing — for input
    // [1(2(5,6), -3(7,8), 4)] with "remove if negative", baseline returns
    // [1(2(5,6), 4)] instead of the required [1(2(5,6), 7, 8, 4)].
    // The baseline does correctly avoid mutating the input.
    public static List<Node> Prune(List<Node> forest, Func<int, bool> shouldRemove)
    {
        ArgumentNullException.ThrowIfNull(forest);
        ArgumentNullException.ThrowIfNull(shouldRemove);

        var result = new List<Node>();
        foreach (var root in forest)
        {
            if (shouldRemove(root.Value)) continue;
            result.Add(CloneFiltered(root, shouldRemove));
        }
        return result;
    }

    private static Node CloneFiltered(Node node, Func<int, bool> shouldRemove)
    {
        var copy = new Node(node.Value);
        foreach (var child in node.Children)
        {
            if (shouldRemove(child.Value)) continue;
            copy.Children.Add(CloneFiltered(child, shouldRemove));
        }
        return copy;
    }
}
