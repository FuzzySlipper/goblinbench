using EvalLab.Core.Cases.CacheKeys;

namespace EvalLab.Tests.Strict;

public sealed class FilterCacheKeyStrictTests
{
    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "cache-key")]
    public void Build_normalizes_search_text_for_equivalent_queries()
    {
        var first = new FilterRequest("  Weekly Sale ", ["events"], false, 1);
        var second = new FilterRequest("weekly sale", ["events"], false, 1);

        Assert.Equal(FilterCacheKeyBuilder.Build(first), FilterCacheKeyBuilder.Build(second));
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "cache-key")]
    public void Build_removes_duplicate_tags_when_they_do_not_change_the_filter()
    {
        var first = new FilterRequest(null, ["events", "featured", "events"], true, 1);
        var second = new FilterRequest(null, ["featured", "events"], true, 1);

        Assert.Equal(FilterCacheKeyBuilder.Build(first), FilterCacheKeyBuilder.Build(second));
    }
}
