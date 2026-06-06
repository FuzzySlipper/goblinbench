using GoblinBench.Core;
using GoblinBench.Runner;

namespace GoblinBench.Core.Tests;

public class RunnerCliTests
{
    [Fact]
    public void FilterCandidatesById_WithNoFilter_ReturnsAllCandidates()
    {
        var candidates = new List<CandidateConfig>
        {
            new() { Id = "coding-scripted" },
            new() { Id = "pi-coding-qwen-local" }
        };

        var filtered = Program.FilterCandidatesById(candidates, []);

        Assert.Equal(["coding-scripted", "pi-coding-qwen-local"], filtered.Select(c => c.Id).ToArray());
    }

    [Fact]
    public void FilterCandidatesById_WithSingleFilter_ReturnsOnlyMatchingCandidate()
    {
        var candidates = new List<CandidateConfig>
        {
            new() { Id = "coding-scripted" },
            new() { Id = "pi-coding-qwen-local" }
        };

        var filtered = Program.FilterCandidatesById(candidates, ["coding-scripted"]);

        var only = Assert.Single(filtered);
        Assert.Equal("coding-scripted", only.Id);
    }

    [Fact]
    public void FilterCandidatesById_WithCommaSeparatedFilter_PreservesCandidateFileOrder()
    {
        var candidates = new List<CandidateConfig>
        {
            new() { Id = "coding-scripted" },
            new() { Id = "pi-coding-qwen-local" },
            new() { Id = "qwen3-35b-local" }
        };

        var filtered = Program.FilterCandidatesById(candidates, ["qwen3-35b-local,coding-scripted"]);

        Assert.Equal(["coding-scripted", "qwen3-35b-local"], filtered.Select(c => c.Id).ToArray());
    }
}
