using DenCore.Data;
using DenCore.Models;
using DenCore.Services;

namespace DenCore.Service.Routes;

/// <summary>Route handlers for worker pool operations.</summary>
public static class WorkerRoutes
{
    public static void Register(WebApplication app)
    {
        var workers = app.MapGroup("/api/workers");

        workers.MapGet("/", async (WorkerPoolRepository repo, string? role) =>
        {
            if (!string.IsNullOrEmpty(role))
            {
                var available = await repo.ListAvailableByRoleAsync(role);
                return Results.Ok(available);
            }

            // Return all members (unfiltered) — just a stub for listing
            return Results.Ok(Array.Empty<PoolMember>());
        });

        workers.MapPost("/register", async (WorkerPoolRepository repo, PoolMember member) =>
        {
            var id = await repo.RegisterMemberAsync(member);
            return Results.Created($"/api/workers/{id}", member with { Id = id });
        });

        workers.MapPost("/assign", async (WorkerPoolRepository poolRepo,
            WorkerLifecycleService lifecycle, string projectId, long taskId,
            long workerId, string role) =>
        {
            var worker = await poolRepo.GetMemberByIdentityAsync(workerId.ToString());
            if (worker is null)
                return Results.NotFound(new { error = "Worker not found" });

            var assignment = await lifecycle.AssignWorkerAsync(projectId, taskId, worker, role);
            if (assignment is null)
                return Results.Conflict(new { error = "Worker is not available" });

            return Results.Ok(assignment);
        });

        workers.MapPost("/release", async (WorkerPoolRepository poolRepo,
            WorkerLifecycleService lifecycle, long assignmentId, long poolMemberId) =>
        {
            await lifecycle.ReleaseWorkerAsync(assignmentId, poolMemberId);
            return Results.Ok(new { status = "released" });
        });

        workers.MapGet("/assignments", async (WorkerPoolRepository repo, string projectId) =>
        {
            var assignments = await repo.ListActiveAssignmentsAsync(projectId);
            return Results.Ok(assignments);
        });
    }
}
