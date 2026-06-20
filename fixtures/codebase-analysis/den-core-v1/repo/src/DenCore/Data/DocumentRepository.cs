using Dapper;
using DenCore.Models;
using Microsoft.Data.Sqlite;

namespace DenCore.Data;

/// <summary>Repository for document persistence.</summary>
public sealed class DocumentRepository
{
    private readonly string _connectionString;

    public DocumentRepository(string connectionString)
    {
        _connectionString = connectionString;
    }

    public async Task<long> InsertAsync(Document doc)
    {
        await using var conn = new SqliteConnection(_connectionString);
        const string sql = """
            INSERT INTO documents (project_id, slug, title, content, kind, tags,
                                   summary, version, visibility, created_at, updated_at, modified_by)
            VALUES (@ProjectId, @Slug, @Title, @Content, @Kind, @Tags,
                    @Summary, @Version, @Visibility, @CreatedAt, @UpdatedAt, @ModifiedBy);
            SELECT last_insert_rowid();
        """;
        return await conn.ExecuteScalarAsync<long>(sql, doc);
    }

    /// <summary>
    /// Gets a document by ID. Returns null if not found — callers
    /// should handle the null case and convert to 404.
    /// </summary>
    public async Task<Document?> GetByIdAsync(long id)
    {
        await using var conn = new SqliteConnection(_connectionString);
        return await conn.QueryFirstOrDefaultAsync<Document>(
            "SELECT * FROM documents WHERE id = @Id", new { Id = id });
    }

    public async Task<Document?> GetBySlugAsync(string projectId, string slug)
    {
        await using var conn = new SqliteConnection(_connectionString);
        return await conn.QueryFirstOrDefaultAsync<Document>(
            "SELECT * FROM documents WHERE project_id = @ProjectId AND slug = @Slug",
            new { ProjectId = projectId, Slug = slug });
    }

    public async Task<IReadOnlyList<Document>> ListByProjectAsync(string projectId)
    {
        await using var conn = new SqliteConnection(_connectionString);
        var rows = await conn.QueryAsync<Document>(
            "SELECT * FROM documents WHERE project_id = @ProjectId ORDER BY updated_at DESC",
            new { ProjectId = projectId });
        return rows.AsList();
    }

    public async Task<bool> UpdateAsync(Document doc)
    {
        await using var conn = new SqliteConnection(_connectionString);
        const string sql = """
            UPDATE documents SET title = @Title, content = @Content, kind = @Kind,
                                 tags = @Tags, summary = @Summary,
                                 version = version + 1, updated_at = @UpdatedAt,
                                 modified_by = @ModifiedBy
            WHERE id = @Id
        """;
        return await conn.ExecuteAsync(sql, doc) > 0;
    }

    public async Task<bool> DeleteAsync(long id)
    {
        await using var conn = new SqliteConnection(_connectionString);
        return await conn.ExecuteAsync(
            "DELETE FROM documents WHERE id = @Id", new { Id = id }) > 0;
    }
}
