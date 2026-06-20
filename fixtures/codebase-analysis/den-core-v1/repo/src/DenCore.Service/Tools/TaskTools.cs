using DenCore.Data;
using DenCore.Models;

namespace DenCore.Service.Tools;

/// <summary>
/// MCP tool handlers for task operations.
/// Tool descriptions must stay in sync with the route handlers.
/// </summary>
public static class TaskTools
{
    public static void Register(WebApplication app)
    {
        var tools = app.MapGroup("/api/tools");

        tools.MapPost("/list-tasks", async (TaskRepository repo, string projectId) =>
        {
            var results = await repo.ListByProjectAsync(projectId);
            return Results.Ok(results);
        });

        tools.MapPost("/get-task", async (TaskRepository repo, long taskId) =>
        {
            var task = await repo.GetByIdAsync(taskId);
            return task is not null ? Results.Ok(task) : Results.NotFound();
        });

        tools.MapPost("/create-task", async (TaskRepository repo, ProjectTask task) =>
        {
            var id = await repo.InsertAsync(task);
            return Results.Ok(new { taskId = id });
        });
    }
}
