using DenCore.Data;

namespace DenCore.Service.Tools;

/// <summary>
/// MCP tool handlers for worker pool interactions.
/// </summary>
public static class WorkerTools
{
    public static void Register(WebApplication app)
    {
        var tools = app.MapGroup("/api/tools");

        tools.MapPost("/worker-complete", async (WorkerPoolRepository repo,
            long assignmentId, string resultJson) =>
        {
            // Record completion acknowledgement.
            // In production this would parse resultJson and store
            // the completion packet durably before releasing.
            return Results.Ok(new { status = "acknowledged", assignmentId });
        });

        tools.MapPost("/heartbeat", async (string workerIdentity) =>
        {
            return Results.Ok(new { status = "ok", workerIdentity });
        });
    }
}
