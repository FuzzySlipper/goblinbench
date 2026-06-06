namespace EvalLab.Core.Cases.CacheKeys;

public static class FilterCacheKeyBuilder
{
    public static string Build(FilterRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);

        var search = request.Search?.Trim() ?? string.Empty;
        var tagBlock = string.Join(",", request.Tags.Select(tag => tag.Trim()));

        return $"search={search}|tags={tagBlock}|archived={request.IncludeArchived}|page={request.Page}";
    }
}
