namespace Cases.RetryPolicy;

public sealed record RetryPolicy(IReadOnlyList<TimeSpan> Delays, bool UseJitter);
