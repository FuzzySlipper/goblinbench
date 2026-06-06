namespace EvalLab.Core.Cases.CacheKeys;

public sealed record FilterRequest(
    string? Search,
    IReadOnlyList<string> Tags,
    bool IncludeArchived,
    int Page);
