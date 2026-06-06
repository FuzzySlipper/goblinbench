using EvalLab.Core.Cases.ExportReport;

namespace EvalLab.Tests.Visible;

public sealed class ExportReportVisibleTests
{
    [Fact]
    [Trait("Suite", "Visible")]
    [Trait("Case", "export-report")]
    public void BuildSummary_formats_the_main_counts()
    {
        var summary = ExportReportGenerator.BuildSummary([
            new ExportRecord("Accessories", 12.50m, true),
            new ExportRecord("Skins", 19.00m, true),
            new ExportRecord("Skins", 0.00m, false)
        ]);

        const string expected =
            "Records: 3" + "\n" +
            "Successful: 2" + "\n" +
            "Failed: 1" + "\n" +
            "Net Amount: 31.50" + "\n" +
            "Categories:" + "\n" +
            "- Accessories: 1" + "\n" +
            "- Skins: 2";

        Assert.Equal(Normalize(expected), Normalize(summary));
    }

    private static string Normalize(string text) => text.ReplaceLineEndings("\n");
}
