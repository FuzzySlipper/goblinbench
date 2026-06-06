using EvalLab.Core.Cases.ExportReport;

namespace EvalLab.Tests.Strict;

public sealed class ExportReportStrictTests
{
    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "export-report")]
    public void BuildSummary_sorts_categories_alphabetically_for_stable_output()
    {
        var summary = ExportReportGenerator.BuildSummary([
            new ExportRecord("Skins", 19.00m, true),
            new ExportRecord("Accessories", 12.50m, true),
            new ExportRecord("Bundles", 4.50m, true)
        ]);

        var categoryLines = Normalize(summary)
            .Split('\n', StringSplitOptions.RemoveEmptyEntries)
            .Where(line => line.StartsWith("- ", StringComparison.Ordinal))
            .ToArray();

        Assert.Equal(["- Accessories: 1", "- Bundles: 1", "- Skins: 1"], categoryLines);
    }

    [Fact]
    [Trait("Suite", "Strict")]
    [Trait("Case", "export-report")]
    public void BuildSummary_uses_successful_amounts_only_in_the_net_total()
    {
        var summary = ExportReportGenerator.BuildSummary([
            new ExportRecord("Skins", 19.00m, true),
            new ExportRecord("Skins", 99.00m, false)
        ]);

        Assert.Contains("Net Amount: 19.00", Normalize(summary));
    }

    private static string Normalize(string text) => text.ReplaceLineEndings("\n");
}
