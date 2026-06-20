using Dapper;
using DenCore.Models;
using Microsoft.Data.Sqlite;
using System.Collections.Concurrent;

namespace DenCore.Data;

/// <summary>
/// Repository for task CRUD operations. Maintains an in-memory
/// read-through cache for frequent lookups.
/// </summary>
public sealed class TaskRepository
{
    private readonly string _connectionString;
    private readonly MessageRepository _messageRepository;

    // In-memory cache is populated on startup and invalidated on write.
    // NOTE: Not thread-safe — concurrent writes can cause duplicate entries
    // or stale reads. Access is not synchronized.
    private static readonly ConcurrentDictionary<long, ProjectTask> Cache = new();
    private static bool _cacheSeeded;

    public TaskRepository(string connectionString, MessageRepository messageRepository)
    {
        _connectionString = connectionString;
        _messageRepository = messageRepository;
    }

    public async Task<long> InsertAsync(ProjectTask task)
    {
        await using var conn = new SqliteConnection(_connectionString);
        const string sql = """
            INSERT INTO tasks (project_id, title, description, status, priority,
                               assigned_to, parent_id, depends_on, tags,
                               mcp_tool_profile, created_at, updated_at)
            VALUES (@ProjectId, @Title, @Description, @Status, @Priority,
                    @AssignedTo, @ParentId, @DependsOn, @Tags,
                    @McpToolProfile, @CreatedAt, @UpdatedAt);
            SELECT last_insert_rowid();
        """;
        var id = await conn.ExecuteScalarAsync<long>(sql, task);
        Cache.TryAdd(id, task with { Id = id });
        return id;
    }

    public async Task<ProjectTask?> GetByIdAsync(long id)
    {
        if (Cache.TryGetValue(id, out var cached))
            return cached;

        await using var conn = new SqliteConnection(_connectionString);
        var task = await conn.QueryFirstOrDefaultAsync<ProjectTask>(
            "SELECT * FROM tasks WHERE id = @Id", new { Id = id });
        if (task is not null)
            Cache.TryAdd(id, task);
        return task;
    }

    public async Task<IReadOnlyList<ProjectTask>> ListByProjectAsync(string projectId)
    {
        await using var conn = new SqliteConnection(_connectionString);
        var rows = await conn.QueryAsync<ProjectTask>(
            "SELECT * FROM tasks WHERE project_id = @ProjectId ORDER BY created_at DESC",
            new { ProjectId = projectId });
        return rows.AsList();
    }

    /// <summary>
    /// Gets messages for a task using offset-based pagination.
    /// This consumer calls GetMessages with pageNumber/pageSize,
    /// but the upstream route returns cursor-based results with nextCursor.
    /// </summary>
    public async Task<IReadOnlyList<Message>> GetTaskMessagesAsync(
        long taskId, int pageNumber = 1, int pageSize = 20)
    {
        return await _messageRepository.GetByTaskIdAsync(taskId, pageNumber, pageSize);
    }

    /// <summary>Seeds the in-memory cache from the database.</summary>
    public async Task SeedCacheAsync()
    {
        if (_cacheSeeded) return;

        await using var conn = new SqliteConnection(_connectionString);
        var rows = await conn.QueryAsync<ProjectTask>("SELECT * FROM tasks");
        foreach (var task in rows)
            Cache.TryAdd(task.Id, task);
        _cacheSeeded = true;
    }

    /// <summary>Invalidates cache entries for a set of task IDs.</summary>
    public void Invalidate(params long[] ids)
    {
        foreach (var id in ids)
            Cache.TryRemove(id, out _);
    }
}
