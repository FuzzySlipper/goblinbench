using EvalLab.Core.Cases.CacheKeys;

namespace EvalLab.Tests.Visible;

public sealed class FilterCacheKeyVisibleTests
{
    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "cache-key")]
    public void Build_treats_tag_order_as_non_semantic()
    {
        var first = new FilterRequest("weekly", ["events", "featured"], false, 1);
        var second = new FilterRequest("weekly", ["featured", "events"], false, 1);

        Assert.Equal(FilterCacheKeyBuilder.Build(first), FilterCacheKeyBuilder.Build(second));
    }

    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "cache-key")]
    public void Build_keeps_page_in_the_cache_key()
    {
        var first = new FilterRequest("weekly", ["events"], false, 1);
        var second = new FilterRequest("weekly", ["events"], false, 2);

        Assert.NotEqual(FilterCacheKeyBuilder.Build(first), FilterCacheKeyBuilder.Build(second));
    }
}
