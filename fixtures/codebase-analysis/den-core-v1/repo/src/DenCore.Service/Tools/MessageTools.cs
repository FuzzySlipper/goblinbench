using DenCore.Data;
using DenCore.Models;

namespace DenCore.Service.Tools;

/// <summary>
/// MCP tool handlers for message operations.
/// These are invoked by the MCP protocol layer.
/// </summary>
public static class MessageTools
{
    public static void Register(WebApplication app)
    {
        var tools = app.MapGroup("/api/tools");

        tools.MapPost("/send-message", async (MessageRepository repo, Message message) =>
        {
            var id = await repo.InsertAsync(message);
            return Results.Ok(new { messageId = id });
        });

        tools.MapPost("/get-messages", async (MessageRepository repo,
            string projectId, int? cursor, int limit = 20) =>
        {
            var results = await repo.ListByProjectAsync(projectId, cursor, limit);
            var nextCursor = results.Count == limit ? results.Last().Id : (long?)null;
            return Results.Ok(new { items = results, nextCursor });
        });
    }
}
