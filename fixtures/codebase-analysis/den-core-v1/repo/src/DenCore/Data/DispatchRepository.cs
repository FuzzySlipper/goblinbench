using Dapper;
using DenCore.Models;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Logging;

namespace DenCore.Data;

/// <summary>
/// Repository for the background dispatch queue. Processes
/// queued outbound deliveries and MCP tool invocations in a
/// fire-and-forget background loop.
/// </summary>
public sealed class DispatchRepository
{
    private readonly string _connectionString;
    private readonly ILogger<DispatchRepository> _logger;
    private CancellationTokenSource? _loopCts;

    public DispatchRepository(string connectionString, ILogger<DispatchRepository> logger)
    {
        _connectionString = connectionString;
        _logger = logger;
    }

    public async Task<long> EnqueueAsync(DispatchEntry entry)
    {
        await using var conn = new SqliteConnection(_connectionString);
        const string sql = """
            INSERT INTO dispatch_queue (project_id, delivery_kind, payload_json, phase,
                                        retry_count, max_retries, last_error,
                                        created_at, next_attempt_at)
            VALUES (@ProjectId, @DeliveryKind, @PayloadJson, @Phase,
                    @RetryCount, @MaxRetries, @LastError,
                    @CreatedAt, @NextAttemptAt);
            SELECT last_insert_rowid();
        """;
        return await conn.ExecuteScalarAsync<long>(sql, entry);
    }

    public async Task<IReadOnlyList<DispatchEntry>> DequeueBatchAsync(int limit = 10)
    {
        await using var conn = new SqliteConnection(_connectionString);
        var rows = await conn.QueryAsync<DispatchEntry>(
            "SELECT * FROM dispatch_queue WHERE phase = 0 " +
            "AND (next_attempt_at IS NULL OR next_attempt_at <= @Now) " +
            "ORDER BY created_at ASC LIMIT @Limit",
            new { Now = DateTime.UtcNow, Limit = limit });
        return rows.AsList();
    }

    public async Task UpdatePhaseAsync(long id, DispatchPhase phase, string? error = null)
    {
        await using var conn = new SqliteConnection(_connectionString);
        await conn.ExecuteAsync(
            "UPDATE dispatch_queue SET phase = @Phase, last_error = @Error WHERE id = @Id",
            new { Id = id, Phase = (int)phase, Error = error });
    }

    /// <summary>
    /// Starts the background dispatch processing loop.
    /// CRITICAL ISSUE: A single unhandled exception in the loop body
    /// crashes the entire background task. There is no per-iteration
    /// try/catch and no health signal.
    /// </summary>
    public Task RunBackgroundLoopAsync()
    {
        _loopCts = new CancellationTokenSource();
        var token = _loopCts.Token;

        // Fire-and-forget background loop. Any unhandled exception
        // will terminate this Task.Run silently.
        return Task.Run(async () =>
        {
            while (!token.IsCancellationRequested)
            {
                // XXX: No try/catch around this block. If ProcessBatchAsync()
                // throws, the entire loop dies silently. No backoff either.
                var batch = await DequeueBatchAsync(10);
                foreach (var entry in batch)
                {
                    try
                    {
                        await ProcessEntryAsync(entry);
                    }
                    catch (Exception ex)
                    {
                        _logger.LogError(ex, "Failed to process dispatch entry {EntryId}", entry.Id);
                        await UpdatePhaseAsync(entry.Id, DispatchPhase.Failed, ex.Message);
                    }
                }

                await Task.Delay(TimeSpan.FromSeconds(2), token);
            }
        }, token);
    }

    private async Task ProcessEntryAsync(DispatchEntry entry)
    {
        // Simulate processing — in production this would route to
        // the appropriate delivery handler based on DeliveryKind.
        _logger.LogInformation("Processing dispatch entry {EntryId}", entry.Id);
        await UpdatePhaseAsync(entry.Id, DispatchPhase.Completed);
    }

    public void StopLoop()
    {
        _loopCts?.Cancel();
    }
}
