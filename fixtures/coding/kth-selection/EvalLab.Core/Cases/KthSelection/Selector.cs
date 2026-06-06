namespace EvalLab.Core.Cases.KthSelection;

public static class Selector
{
    // Baseline: sorts the input array in place and indexes into it.
    // Correct for finding the kth smallest VALUE, but violates the
    // "do not mutate input" constraint. Also allocates no auxiliary
    // storage beyond the recursion stack of Array.Sort (good on that
    // axis) but the mutation is the immediate problem.
    public static int KthSmallest(int[] arr, int k)
    {
        ArgumentNullException.ThrowIfNull(arr);

        if (k < 1 || k > arr.Length)
        {
            throw new ArgumentOutOfRangeException(nameof(k), k, $"k must be in [1, {arr.Length}].");
        }

        Array.Sort(arr);
        return arr[k - 1];
    }
}
