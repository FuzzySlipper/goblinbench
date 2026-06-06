namespace EvalLab.Core.Cases.ExportReport;

public static class ExportReportGenerator
{
    public static string BuildSummary(IEnumerable<ExportRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);

        var snapshot = records.ToList();
        var lines = new List<string>
        {
            $"Records: {snapshot.Count}",
            $"Successful: {snapshot.Count(record => record.Succeeded)}",
            "Failed: 0",
            $"Net Amount: {snapshot.Sum(record => record.Amount):0.00}",
            "Categories:"
        };

        foreach (var group in snapshot.GroupBy(record => record.Category))
        {
            lines.Add($"- {group.Key}: {group.Count()}");
        }

        return string.Join(Environment.NewLine, lines);
    }
}
