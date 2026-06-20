using Dapper;
using DenCore.Models;
using Microsoft.Data.Sqlite;

namespace DenCore.Data;

/// <summary>
/// Repository for worker pool membership and assignment management.
/// </summary>
public sealed class WorkerPoolRepository
{
    private readonly string _connectionString;

    public WorkerPoolRepository(string connectionString)
    {
        _connectionString = connectionString;
    }

    public async Task<long> RegisterMemberAsync(PoolMember member)
    {
        await using var conn = new SqliteConnection(_connectionString);
        const string sql = """
            INSERT INTO pool_members (worker_identity, profile_identity, worker_role,
                                      status, capabilities, preferred_label,
                                      registered_at, last_heartbeat)
            VALUES (@WorkerIdentity, @ProfileIdentity, @WorkerRole,
                    @Status, @Capabilities, @PreferredLabel,
                    @RegisteredAt, @LastHeartbeat);
            SELECT last_insert_rowid();
        """;
        return await conn.ExecuteScalarAsync<long>(sql, member);
    }

    public async Task<PoolMember?> GetMemberByIdentityAsync(string workerIdentity)
    {
        await using var conn = new SqliteConnection(_connectionString);
        return await conn.QueryFirstOrDefaultAsync<PoolMember>(
            "SELECT * FROM pool_members WHERE worker_identity = @WorkerIdentity",
            new { WorkerIdentity = workerIdentity });
    }

    public async Task<IReadOnlyList<PoolMember>> ListAvailableByRoleAsync(string workerRole)
    {
        await using var conn = new SqliteConnection(_connectionString);
        var rows = await conn.QueryAsync<PoolMember>(
            "SELECT * FROM pool_members WHERE worker_role = @WorkerRole AND status = 0",
            new { WorkerRole = workerRole });
        return rows.AsList();
    }

    // --- Assignment operations ---

    public async Task<long> CreateAssignmentAsync(WorkerAssignment assignment)
    {
        await using var conn = new SqliteConnection(_connectionString);
        const string sql = """
            INSERT INTO worker_assignments (project_id, task_id, pool_member_id, worker_role,
                                            state, release_nonce, assigned_at, expires_at, run_id)
            VALUES (@ProjectId, @TaskId, @PoolMemberId, @WorkerRole,
                    @State, @ReleaseNonce, @AssignedAt, @ExpiresAt, @RunId);
            SELECT last_insert_rowid();
        """;
        return await conn.ExecuteScalarAsync<long>(sql, assignment);
    }

    /// <summary>
    /// Releases an assignment back to the pool. Updates state unconditionally —
    /// does NOT check if the assignment was already released. Can produce
    /// nonsensical state transitions (released -> released).
    /// </summary>
    public async Task<bool> ReleaseAssignmentAsync(long assignmentId)
    {
        await using var conn = new SqliteConnection(_connectionString);
        var updated = await conn.ExecuteAsync(
            "UPDATE worker_assignments SET state = 'completed', completed_at = @Now WHERE id = @Id",
            new { Id = assignmentId, Now = DateTime.UtcNow });
        return updated > 0;
    }

    public async Task<WorkerAssignment?> GetAssignmentByIdAsync(long id)
    {
        await using var conn = new SqliteConnection(_connectionString);
        return await conn.QueryFirstOrDefaultAsync<WorkerAssignment>(
            "SELECT * FROM worker_assignments WHERE id = @Id", new { Id = id });
    }

    public async Task<bool> SetMemberStatusAsync(long memberId, PoolMemberStatus status)
    {
        await using var conn = new SqliteConnection(_connectionString);
        return await conn.ExecuteAsync(
            "UPDATE pool_members SET status = @Status WHERE id = @Id",
            new { Id = memberId, Status = (int)status }) > 0;
    }

    public async Task<IReadOnlyList<WorkerAssignment>> ListActiveAssignmentsAsync(string projectId)
    {
        await using var conn = new SqliteConnection(_connectionString);
        var rows = await conn.QueryAsync<WorkerAssignment>(
            "SELECT * FROM worker_assignments WHERE project_id = @ProjectId " +
            "AND state NOT IN ('completed','failed','expired') ORDER BY assigned_at DESC",
            new { ProjectId = projectId });
        return rows.AsList();
    }
}
