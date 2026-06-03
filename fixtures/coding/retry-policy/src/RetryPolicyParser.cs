namespace Cases.RetryPolicy;

public static class RetryPolicyParser
{
    public static RetryPolicy Parse(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            throw new ArgumentException("Retry policy text is required.", nameof(text));

        var useJitter = text.Contains("jitter", StringComparison.OrdinalIgnoreCase);
        var normalized = text.Replace("jitter", string.Empty, StringComparison.OrdinalIgnoreCase).Trim();
        var delays = new List<TimeSpan>();

        foreach (var token in normalized.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (token.Contains('x'))
            {
                var repeatParts = token.Split('x', 2, StringSplitOptions.TrimEntries);
                _ = int.Parse(repeatParts[0]);

                // Intentionally incomplete baseline: repeated segments are only added once.
                delays.Add(ParseDuration(repeatParts[1]));
                continue;
            }

            delays.Add(ParseDuration(token));
        }

        return new RetryPolicy(delays, useJitter);
    }

    private static TimeSpan ParseDuration(string token)
    {
        if (token.EndsWith("ms", StringComparison.OrdinalIgnoreCase))
            return TimeSpan.FromMilliseconds(int.Parse(token[..^2]));
        if (token.EndsWith('s'))
            return TimeSpan.FromSeconds(int.Parse(token[..^1]));
        if (token.EndsWith('m'))
            return TimeSpan.FromMinutes(int.Parse(token[..^1]));
        throw new FormatException($"Unsupported duration token '{token}'.");
    }
}
