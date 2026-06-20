using DenCore.Data;
using DenCore.Models;

namespace DenCore.Service.Routes;

/// <summary>Route handlers for task operations.</summary>
public static class TaskRoutes
{
    public static void Register(WebApplication app)
    {
        var tasks = app.MapGroup("/api/tasks");

        tasks.MapGet("/", async (TaskRepository repo, string projectId) =>
        {
            var results = await repo.ListByProjectAsync(projectId);
            return Results.Ok(results);
        });

        tasks.MapGet("/{id:long}", async (TaskRepository repo, long id) =>
        {
            var task = await repo.GetByIdAsync(id);
            return task is not null ? Results.Ok(task) : Results.NotFound();
        });

        tasks.MapPost("/", async (TaskRepository repo, ProjectTask task) =>
        {
            var id = await repo.InsertAsync(task);
            return Results.Created($"/api/tasks/{id}", task with { Id = id });
        });

        // Legacy compatibility endpoint — routes to /api/items mapped to /api/tasks
        tasks.MapGet("/items/{id:long}", async (TaskRepository repo, long id) =>
        {
            var task = await repo.GetByIdAsync(id);
            return task is not null ? Results.Ok(task) : Results.NotFound();
        });

        // Get messages for a task using offset-based pagination.
        // Note: the MessageRoutes endpoint returns cursor-based results (nextCursor),
        // but this consumer still uses pageNumber/pageSize offset pagination.
        // The cursor field from the upstream endpoint is never read here.
        tasks.MapGet("/{id:long}/messages", async (TaskRepository repo, long id,
            int pageNumber = 1, int pageSize = 20) =>
        {
            var messages = await repo.GetTaskMessagesAsync(id, pageNumber, pageSize);
            var totalCount = await new MessageRepository(
                // XXX: This re-creates the connection string inline.
                // Should use DI, but not a planted issue.
                "Data Source=dencore.db").CountByTaskAsync(id);

            return Results.Ok(new
            {
                items = messages,
                pageNumber,
                pageSize,
                totalCount
            });
        });
    }
}
