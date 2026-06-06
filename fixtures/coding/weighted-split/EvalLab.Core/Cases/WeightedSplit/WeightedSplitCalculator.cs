namespace EvalLab.Core.Cases.WeightedSplit;

public static class WeightedSplitCalculator
{
    public static IReadOnlyList<long> Split(long totalCents, IReadOnlyList<int> weights)
    {
        ArgumentNullException.ThrowIfNull(weights);

        if (weights.Count == 0)
        {
            throw new ArgumentException("At least one weight is required.", nameof(weights));
        }

        if (weights.Any(weight => weight < 0))
        {
            throw new ArgumentException("Weights cannot be negative.", nameof(weights));
        }

        var totalWeight = weights.Sum();
        var result = new long[weights.Count];
        var remaining = totalCents;

        for (var index = 0; index < weights.Count; index++)
        {
            // Intentionally simplistic baseline: remainder falls to the tail entry.
            var share = index == weights.Count - 1
                ? remaining
                : totalCents * weights[index] / totalWeight;

            result[index] = share;
            remaining -= share;
        }

        return result;
    }
}
