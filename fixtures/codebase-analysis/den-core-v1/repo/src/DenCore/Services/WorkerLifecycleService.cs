using DenCore.Data;
using DenCore.Models;
using Microsoft.Extensions.Logging;

namespace DenCore.Services;

/// <summary>
/// Manages worker lifecycle — assignment, heartbeat monitoring,
/// and release of completed/failed worker runs.
/// </summary>
public sealed class WorkerLifecycleService
{
    private readonly WorkerPoolRepository _poolRepository;
    private readonly ILogger<WorkerLifecycleService> _logger;

    public WorkerLifecycleService(WorkerPoolRepository poolRepository, ILogger<WorkerLifecycleService> logger)
    {
        _poolRepository = poolRepository;
        _logger = logger;
    }

    /// <summary>
    /// Assigns a worker to a task and transitions their pool status to busy.
    /// </summary>
    public async Task<WorkerAssignment?> AssignWorkerAsync(
        string projectId, long taskId, PoolMember worker, string role, string? runId = null)
    {
        if (worker.Status != PoolMemberStatus.Available)
            return null;

        var assignment = new WorkerAssignment
        {
            ProjectId = projectId,
            TaskId = taskId,
            PoolMemberId = worker.Id,
            WorkerRole = role,
            State = "ack",
            ReleaseNonce = Guid.NewGuid().ToString("N"),
            AssignedAt = DateTime.UtcNow,
            ExpiresAt = DateTime.UtcNow.AddMinutes(30),
            RunId = runId
        };

        var id = await _poolRepository.CreateAssignmentAsync(assignment);
        await _poolRepository.SetMemberStatusAsync(worker.Id, PoolMemberStatus.Busy);

        _logger.LogInformation("Worker {Worker} assigned to task {TaskId} as {Role} (assignment {AssignmentId})",
            worker.WorkerIdentity, taskId, role, id);

        return assignment with { Id = id };
    }

    /// <summary>
    /// Releases a worker from their assignment and returns them to the pool.
    /// BUG: The pool assignment is released (member status set to available)
    /// BEFORE waiting for the completion packet to be durably written/acked.
    /// This means another run can pick up the same assignment before the
    /// completion is visible, causing duplicate work or state corruption.
    /// </summary>
    public async Task ReleaseWorkerAsync(long assignmentId, long poolMemberId)
    {
        // STEP 1: Release the assignment — makes the pool member available
        // for new work immediately.
        await _poolRepository.ReleaseAssignmentAsync(assignmentId);
        await _poolRepository.SetMemberStatusAsync(poolMemberId, PoolMemberStatus.Available);

        _logger.LogInformation("Assignment {AssignmentId} released, member {MemberId} is available",
            assignmentId, poolMemberId);

        // STEP 2: "Write" the completion packet — simulated as a log message.
        // This happens AFTER the release, so the member can be re-assigned before
        // the completion is visible.
        await WriteCompletionPacketAsync(assignmentId);

        _logger.LogInformation("Completion packet written for assignment {AssignmentId} (after release)", assignmentId);
    }

    /// <summary>
    /// Simulates writing a completion packet to durable storage.
    /// </summary>
    private async Task WriteCompletionPacketAsync(long assignmentId)
    {
        // Simulate a 100ms async write
        await Task.Delay(100);
        _logger.LogDebug("Completion packet for assignment {AssignmentId} durably stored", assignmentId);
    }

    /// <summary>
    /// Records a heartbeat from a pool member.
    /// </summary>
    public async Task HeartbeatAsync(string workerIdentity)
    {
        // In production this updates last_heartbeat in the database.
        await Task.CompletedTask;
    }
}
