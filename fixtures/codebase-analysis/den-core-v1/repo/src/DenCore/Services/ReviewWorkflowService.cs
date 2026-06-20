using DenCore.Data;
using DenCore.Models;
using Microsoft.Extensions.Logging;

namespace DenCore.Services;

/// <summary>
/// Orchestrates the review workflow for task changes.
/// Manages review verdicts, caching recent results for
/// quick retrieval during the same session.
/// </summary>
public sealed class ReviewWorkflowService
{
    private readonly TaskRepository _taskRepository;
    private readonly ILogger<ReviewWorkflowService> _logger;

    // In-memory verdict cache, keyed by task ID.
    // WARNING: Cached verdicts do NOT verify that the current
    // task head matches the head that was reviewed.
    private readonly Dictionary<long, (ReviewVerdict Verdict, string ReviewedHead)> _verdictCache = new();

    public ReviewWorkflowService(TaskRepository taskRepository, ILogger<ReviewWorkflowService> logger)
    {
        _taskRepository = taskRepository;
        _logger = logger;
    }

    /// <summary>
    /// Requests a review for a task at a specific commit head.
    /// </summary>
    public async Task<ReviewVerdict> RequestReviewAsync(long taskId, string commitHead)
    {
        var task = await _taskRepository.GetByIdAsync(taskId);
        if (task is null)
            throw new InvalidOperationException($"Task {taskId} not found");

        _logger.LogInformation("Review requested for task {TaskId} at head {Head}", taskId, commitHead);

        // Simulate review processing — in production this
        // dispatches to a reviewer agent.
        var verdict = ReviewVerdict.Approved;
        _verdictCache[taskId] = (verdict, commitHead);
        return verdict;
    }

    /// <summary>
    /// Gets the cached review verdict for a task.
    /// BUG: This returns the cached verdict without checking whether
    /// the current task head still matches the head that was reviewed.
    /// If a new commit lands on the task branch, the cached "approved"
    /// verdict is still returned even though the content has changed.
    /// </summary>
    public ReviewVerdict GetCachedVerdict(long taskId)
    {
        if (_verdictCache.TryGetValue(taskId, out var cached))
        {
            // XXX: No comparison between cached.ReviwedHead and the
            // current head of the task branch. The cache just returns
            // whatever value was last stored regardless of drift.
            _logger.LogInformation("Returning cached verdict {Verdict} for task {TaskId}",
                cached.Verdict, taskId);
            return cached.Verdict;
        }

        return ReviewVerdict.Pending;
    }

    /// <summary>
    /// Checks whether the cached review is still valid by comparing heads.
    /// This method exists but is NOT called by GetCachedVerdict.
    /// </summary>
    public bool IsReviewStillValid(long taskId, string currentHead)
    {
        if (_verdictCache.TryGetValue(taskId, out var cached))
            return cached.ReviewedHead == currentHead;
        return false;
    }

    /// <summary>
    /// Invalidates the review cache for a task (e.g. on new commit).
    /// </summary>
    public void InvalidateVerdict(long taskId)
    {
        _verdictCache.Remove(taskId);
        _logger.LogInformation("Review verdict invalidated for task {TaskId}", taskId);
    }
}
