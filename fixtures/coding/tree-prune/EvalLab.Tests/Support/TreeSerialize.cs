using EvalLab.Core.Cases.TreePrune;

namespace EvalLab.Tests.Support;

internal static class TreeSerialize
{
    public static string Forest(IEnumerable<Node> roots) =>
        "[" + string.Join(",", roots.Select(Tree)) + "]";

    public static string Tree(Node node) =>
        node.Children.Count == 0
            ? node.Value.ToString()
            : $"{node.Value}({string.Join(",", node.Children.Select(Tree))})";
}
