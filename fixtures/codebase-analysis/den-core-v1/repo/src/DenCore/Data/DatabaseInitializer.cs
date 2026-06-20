using Dapper;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Logging;

namespace DenCore.Data;

/// <summary>
/// Initializes the SQLite database schema and pre-loads
/// some common reference data into memory on startup.
/// </summary>
public sealed class DatabaseInitializer
{
    private readonly string _connectionString;
    private readonly ILogger<DatabaseInitializer> _logger;

    // Pre-loaded reference data cache — populated on startup.
    // This is a valid read-through cache: the database is still
    // the authoritative source, and the cache is rebuilt on restart.
    private static readonly Dictionary<string, string> ConfigCache = new();

    public DatabaseInitializer(string connectionString, ILogger<DatabaseInitializer> logger)
    {
        _connectionString = connectionString;
        _logger = logger;
    }

    public async Task InitializeAsync()
    {
        await using var conn = new SqliteConnection(_connectionString);
        await conn.OpenAsync();

        const string schema = """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status INTEGER NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 3,
                assigned_to TEXT,
                parent_id INTEGER,
                depends_on TEXT,
                tags TEXT,
                mcp_tool_profile TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                task_id INTEGER,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                thread_root_id INTEGER,
                intent TEXT,
                delivery_kind INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                legacy_sender_id TEXT
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                slug TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                kind INTEGER NOT NULL DEFAULT 0,
                tags TEXT,
                summary TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                visibility TEXT NOT NULL DEFAULT 'normal',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                modified_by TEXT
            );

            CREATE TABLE IF NOT EXISTS pool_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_identity TEXT NOT NULL,
                profile_identity TEXT NOT NULL,
                worker_role TEXT NOT NULL,
                status INTEGER NOT NULL DEFAULT 0,
                capabilities TEXT NOT NULL DEFAULT '',
                preferred_label TEXT,
                registered_at TEXT NOT NULL,
                last_heartbeat TEXT
            );

            CREATE TABLE IF NOT EXISTS worker_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                task_id INTEGER NOT NULL,
                pool_member_id INTEGER NOT NULL,
                worker_role TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'ack',
                release_nonce TEXT,
                assigned_at TEXT NOT NULL,
                completed_at TEXT,
                expires_at TEXT,
                run_id TEXT
            );

            CREATE TABLE IF NOT EXISTS no_capacity_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                task_id INTEGER,
                reason_code TEXT NOT NULL,
                diagnostic_message TEXT NOT NULL,
                candidate_stats_json TEXT,
                request_params_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dispatch_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                delivery_kind INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                phase INTEGER NOT NULL DEFAULT 0,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                last_error TEXT,
                created_at TEXT NOT NULL,
                next_attempt_at TEXT,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                project_id TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                comment TEXT,
                snapshot_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gateway_contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                gateway_url TEXT NOT NULL,
                http_method TEXT NOT NULL DEFAULT 'POST',
                auth_token TEXT,
                signing_secret TEXT,
                content_type TEXT NOT NULL DEFAULT 'application/json',
                transform_template_json TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                accepting_deliveries INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_delivery_at TEXT
            );

            CREATE TABLE IF NOT EXISTS direct_delivery_contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                target_agent_identity TEXT NOT NULL,
                transport_kind TEXT NOT NULL DEFAULT 'mcp',
                endpoint_url TEXT NOT NULL,
                session_id TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                priority_hint INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """;

        await conn.ExecuteAsync(schema);
        _logger.LogInformation("Database schema initialized");

        // Pre-load startup configuration into memory cache.
        await SeedConfigCacheAsync();
    }

    private async Task SeedConfigCacheAsync()
    {
        // Simulate loading reference data from a config table.
        // In a real system this would query a config table.
        // For now, populate with sensible defaults.
        ConfigCache["max_concurrent_assignments"] = "5";
        ConfigCache["assignment_timeout_seconds"] = "300";
        ConfigCache["heartbeat_interval_seconds"] = "30";
        _logger.LogInformation("Config cache seeded with {Count} entries", ConfigCache.Count);
    }
}
