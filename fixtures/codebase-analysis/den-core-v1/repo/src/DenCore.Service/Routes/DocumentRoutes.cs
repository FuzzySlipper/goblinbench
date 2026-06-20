using DenCore.Data;
using DenCore.Models;

namespace DenCore.Service.Routes;

/// <summary>Route handlers for document CRUD operations.</summary>
public static class DocumentRoutes
{
    public static void Register(WebApplication app)
    {
        var docs = app.MapGroup("/api/documents");

        docs.MapGet("/by-id/{id:long}", async (DocumentRepository repo, long id) =>
        {
            var doc = await repo.GetByIdAsync(id);
            // XXX: GetByIdAsync returns null for missing documents,
            // but we return Ok(null) instead of NotFound().
            // This means clients get a 200 with null body instead of 404.
            return Results.Ok(doc);
        });

        docs.MapGet("/by-slug/{projectId}/{slug}", async (DocumentRepository repo,
            string projectId, string slug) =>
        {
            var doc = await repo.GetBySlugAsync(projectId, slug);
            return doc is not null ? Results.Ok(doc) : Results.NotFound();
        });

        docs.MapPost("/", async (DocumentRepository repo, Document doc) =>
        {
            var id = await repo.InsertAsync(doc);
            return Results.Created($"/api/documents/by-id/{id}", doc with { Id = id });
        });

        docs.MapPut("/{id:long}", async (DocumentRepository repo, long id, Document doc) =>
        {
            var updated = await repo.UpdateAsync(doc with { Id = id });
            return updated ? Results.Ok(doc with { Id = id }) : Results.NotFound();
        });

        docs.MapDelete("/{id:long}", async (DocumentRepository repo, long id) =>
        {
            var deleted = await repo.DeleteAsync(id);
            return deleted ? Results.NoContent() : Results.NotFound();
        });

        docs.MapGet("/", async (DocumentRepository repo, string projectId) =>
        {
            var results = await repo.ListByProjectAsync(projectId);
            return Results.Ok(results);
        });
    }
}
