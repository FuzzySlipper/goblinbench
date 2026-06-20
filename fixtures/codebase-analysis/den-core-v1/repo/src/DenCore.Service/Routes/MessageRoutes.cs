using DenCore.Models;

namespace DenCore.Service.Routes;

/// <summary>Route handlers for message operations.</summary>
public static class MessageRoutes
{
    public static void Register(WebApplication app)
    {
        var messages = app.MapGroup("/api/messages");

        messages.MapGet("/", async (Data.MessageRepository repo, string projectId,
            int? cursor, int limit = 20) =>
        {
            var results = await repo.ListByProjectAsync(projectId, cursor, limit);

            // Returns cursor-based pagination with nextCursor field.
            var nextCursor = results.Count == limit ? results.Last().Id : (long?)null;

            return Results.Ok(new
            {
                items = results,
                nextCursor
            });
        });

        messages.MapGet("/{id:long}", async (Data.MessageRepository repo, long id) =>
        {
            var msg = await repo.GetByIdAsync(id);
            return msg is not null ? Results.Ok(msg) : Results.NotFound();
        });

        messages.MapPost("/", async (Data.MessageRepository repo, Message message) =>
        {
            var id = await repo.InsertAsync(message);
            return Results.Created($"/api/messages/{id}", message with { Id = id });
        });
    }
}
