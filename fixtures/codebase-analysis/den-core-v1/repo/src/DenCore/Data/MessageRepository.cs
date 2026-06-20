using Dapper;
using DenCore.Models;
using Microsoft.Data.Sqlite;

namespace DenCore.Data;

/// <summary>Repository for message persistence and retrieval.</summary>
public sealed class MessageRepository
{
    private readonly string _connectionString;

    public MessageRepository(string connectionString)
    {
        _connectionString = connectionString;
    }

    public async Task<long> InsertAsync(Message message)
    {
        await using var conn = new SqliteConnection(_connectionString);
        const string sql = """
            INSERT INTO messages (project_id, task_id, sender, content, thread_root_id,
                                  intent, delivery_kind, metadata_json, created_at,
                                  legacy_sender_id)
            VALUES (@ProjectId, @TaskId, @Sender, @Content, @ThreadRootId,
                    @Intent, @DeliveryKind, @MetadataJson, @CreatedAt,
                    @LegacySenderId);
            SELECT last_insert_rowid();
        """;
        return await conn.ExecuteScalarAsync<long>(sql, message);
    }

    public async Task<Message?> GetByIdAsync(long id)
    {
        await using var conn = new SqliteConnection(_connectionString);
        return await conn.QueryFirstOrDefaultAsync<Message>(
            "SELECT * FROM messages WHERE id = @Id", new { Id = id });
    }

    /// <summary>
    /// Gets messages with offset-based pagination. Used by TaskRepository
    /// when loading messages attached to a task.
    /// </summary>
    public async Task<IReadOnlyList<Message>> GetByTaskIdAsync(
        long taskId, int pageNumber = 1, int pageSize = 20)
    {
        await using var conn = new SqliteConnection(_connectionString);
        var offset = (pageNumber - 1) * pageSize;
        var rows = await conn.QueryAsync<Message>(
            "SELECT * FROM messages WHERE task_id = @TaskId ORDER BY created_at DESC LIMIT @Limit OFFSET @Offset",
            new { TaskId = taskId, Limit = pageSize, Offset = offset });
        return rows.AsList();
    }

    public async Task<IReadOnlyList<Message>> ListByProjectAsync(
        string projectId, long? cursor, int limit = 20)
    {
        await using var conn = new SqliteConnection(_connectionString);
        var sql = cursor.HasValue
            ? "SELECT * FROM messages WHERE project_id = @ProjectId AND id > @Cursor ORDER BY id DESC LIMIT @Limit"
            : "SELECT * FROM messages WHERE project_id = @ProjectId ORDER BY id DESC LIMIT @Limit";
        var rows = await conn.QueryAsync<Message>(sql,
            new { ProjectId = projectId, Cursor = cursor, Limit = limit });
        return rows.AsList();
    }

    public async Task<int> CountByTaskAsync(long taskId)
    {
        await using var conn = new SqliteConnection(_connectionString);
        return await conn.ExecuteScalarAsync<int>(
            "SELECT COUNT(*) FROM messages WHERE task_id = @TaskId",
            new { TaskId = taskId });
    }
}
