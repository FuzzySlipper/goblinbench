# DenCore v1 — Codebase Analysis Fixture

## Project Brief

A synthetic C# .NET minimal-API service mimicking DenCore, 
the central orchestration service for the Den intelligent agent platform.
It exposes REST and MCP tool endpoints for task management, messaging,
document storage, worker pool orchestration, and LLM-powered context retrieval.

## Architecture

# DenCore v1 — Architecture Brief

## Overview

DenCore is the central service for the Den intelligent agent platform. It provides task management, messaging, document storage, worker pool orchestration, MCP tool routing, and LLM integration for agent-to-agent and agent-to-human collaboration.

## High-Level Architecture

```
┌──────────────────────────────────────────────────────┐
│                   DenCore.Service                     │
│  (ASP.NET Minimal API — Kestrel host, SQLite store)  │
│                                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │  Routes   │ │  Tools   │ │  MCP     │ │  LLM     │ │
│  │ (REST)    │ │ (MCP)    │ │ Registry │ │ Client   │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       │             │            │             │        │
│  ┌────┴─────────────┴────────────┴─────────────┴─────┐ │
│  │                  Services                          │ │
│  │  ReviewWorkflow  │  StaleAttention │  WorkerLife   │ │
│  └────────────────────────┬──────────────────────────┘ │
│                           │                             │
│  ┌────────────────────────┴──────────────────────────┐ │
│  │               Data Layer (Repositories)            │ │
│  │  Dapper + SQLite — tasks, messages, documents,     │ │
│  │  pool_members, worker_assignments, dispatch_queue  │ │
│  └───────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

## Key Components

### Models (`DenCore/Models/`)
Core domain types: `ProjectTask`, `Message`, `Document`, `PoolMember`, `WorkerAssignment`, `DispatchEntry`, `TaskHistory`, gateway contracts, and enumerations. Uses C# records with nullable reference types.

### Data Layer (`DenCore/Data/`)
Dapper-based SQLite repositories. Each repository owns its connection management. `DatabaseInitializer` creates schema and pre-loads config cache on startup.

### Services (`DenCore/Services/`)
- **ReviewWorkflowService**: Manages review lifecycle with a per-session verdict cache.
- **StaleAttentionRoutingService**: Background monitor for idle tasks.
- **WorkerLifecycleService**: Assignment/release orchestration for pool members.

### MCP (`DenCore/Mcp/`)
Tool profile registry mapping MCP tool names to schemas and handler routes. Used by the tool routing layer.

### LLM (`DenCore/Llm/`)
OpenAI-compatible client for completions and structured output. Used by the Librarian for context summarization.

### Service Layer (`DenCore.Service/`)
Minimal API endpoints for REST (routes) and MCP tool handlers (tools). Startup in `Program.cs` wires everything together.

## Data Flow

1. **Agent sends message** → `MessageRoutes` → `MessageRepository` → SQLite
2. **Worker assigned to task** → `WorkerRoutes` → `WorkerLifecycleService` → `WorkerPoolRepository`
3. **Review requested** → `ReviewWorkflowService` caches verdict
4. **Background dispatch** → `DispatchRepository.RunBackgroundLoopAsync()` polls queue
5. **LLM summarization** → `LibrarianService` → `OpenAiCompatibleLlmClient`

## Database

SQLite with 10 core tables. Connection string configurable via `ConnectionStrings:DefaultConnection`. Schema auto-created on startup.

## Decision Records

- **SQLite**: Simple single-file storage suitable for single-node deployment.
- **Dapper**: Lightweight ORM — full control over SQL, no EF Core overhead.
- **In-memory caching**: TaskRepository and ReviewWorkflowService use dictionaries for fast reads. Database remains authoritative source of truth.
- **Minimal API**: Modern ASP.NET pattern with less boilerplate than controllers.
- **MCP over HTTP**: Tool endpoints are HTTP POST handlers; no WebSocket transport in v1.

## API Contract

# DenCore v1 — API Contract

## Base URL

```
http://localhost:5000
```

## Authentication

All endpoints require a valid API key in the `X-Api-Key` header. *(Not yet implemented in v1.)*

## Endpoints

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health check |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks?projectId={id}` | List tasks in a project |
| GET | `/api/tasks/{id}` | Get task by ID |
| POST | `/api/tasks` | Create a new task |
| GET | `/api/tasks/{id}/messages` | Get messages for a task (offset pagination) |

### Messages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/messages?projectId={id}&cursor={c}&limit={n}` | List messages (cursor pagination) |
| GET | `/api/messages/{id}` | Get message by ID |
| POST | `/api/messages` | Send a message |

### Documents

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/documents/{id}` | Get document by ID |
| GET | `/api/documents/by-slug/{projectId}/{slug}` | Get document by project + slug |
| POST | `/api/documents` | Create document |
| PUT | `/api/documents/{id}` | Update document |
| DELETE | `/api/documents/{id}` | Delete document |
| GET | `/api/documents?projectId={id}` | List documents |

### Workers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/workers?role={role}` | List workers (optional role filter) |
| POST | `/api/workers/register` | Register a pool member |
| POST | `/api/workers/assign` | Assign worker to task |
| POST | `/api/workers/release` | Release worker from assignment |
| GET | `/api/workers/assignments?projectId={id}` | List active assignments |

### MCP Tools

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tools/send-message` | Send a message (MCP) |
| POST | `/api/tools/get-messages` | Get messages (MCP) |
| POST | `/api/tools/list-tasks` | List tasks (MCP) |
| POST | `/api/tools/get-task` | Get task (MCP) |
| POST | `/api/tools/create-task` | Create task (MCP) |
| POST | `/api/tools/worker-complete` | Report worker completion |
| POST | `/api/tools/heartbeat` | Worker heartbeat |
| POST | `/api/tools/triage-complete` | Triage completion signal |
| POST | `/api/tools/generate-summary` | Generate context summary |

## Pagination

- **Messages (REST)**: Cursor-based. Response includes `nextCursor` field.
- **Task Messages (sub-resource)**: Offset-based. Uses `pageNumber` and `pageSize`.
- **Documents**: No pagination in v1.

## Error Responses

```json
{
  "error": "description of the problem"
}
```

Standard HTTP codes: 200, 201, 204, 400, 404, 409, 500.

## src/DenCore/Models/ProjectTask.cs

```csharp
namespace DenCore.Models;

/// <summary>
/// A unit of work tracked within a DenCore project.
/// Supports hierarchical subtasking and review workflows.
/// </summary>
public sealed record ProjectTask
{
    public long Id { get; init; }
    public string ProjectId { get; init; } = string.Empty;
    public string Title { get; init; } = string.Empty;
    public string Description { get; init; } = string.Empty;
    public TaskStatus Status { get; init; } = TaskStatus.Planned;
    public Priority Priority { get; init; } = Priority.Medium;

    /// <summary>Agent identity assigned to this task.</summary>
    public string? AssignedTo { get; init; }

    /// <summary>Parent task ID for subtasking hierarchy. Null for top-level tasks.</summary>
    public long? ParentId { get; init; }

    /// <summary>Optional comma-separated list of dependency task IDs.</summary>
    public string? DependsOn { get; init; }

    /// <summary>Comma-separated tag labels.</summary>
    public string? Tags { get; init; }

    // --- MCP profile hint (deprecated, do not use in new code) ---
    /// <summary>
    /// Optional hint for which MCP tool profile should handle this task.
    /// This field is a layering violation — it exposes MCP concepts in the core domain.
    /// Do NOT rely on this field in new code; use the profile registry instead.
    /// </summary>
    [Obsolete("Use McpToolProfileRegistry for profile resolution. This field will be removed in v2.")]
    public string? McpToolProfile { get; init; }

    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;
    public DateTime UpdatedAt { get; init; } = DateTime.UtcNow;
}

```

## src/DenCore/Models/Message.cs

```csharp
namespace DenCore.Models;

/// <summary>
/// A routed message within the DenCore system. Messages can be
/// project-level, attached to a task, or threaded replies.
/// </summary>
public sealed record Message
{
    public long Id { get; init; }
    public string ProjectId { get; init; } = string.Empty;
    public long? TaskId { get; init; }

    /// <summary>Agent or system identity that sent this message.</summary>
    public string Sender { get; init; } = string.Empty;

    /// <summary>Body content in markdown format.</summary>
    public string Content { get; init; } = string.Empty;

    /// <summary>Optional parent thread root message ID.</summary>
    public long? ThreadRootId { get; init; }

    /// <summary>
    /// Canonical intent label — e.g. "review_feedback", "handoff", "notification".
    /// </summary>
    public string? Intent { get; init; }

    /// <summary>
    /// Delivery routing kind for outbound dispatch.
    /// </summary>
    public DeliveryKind DeliveryKind { get; init; } = DeliveryKind.Direct;

    /// <summary>
    /// Optional JSON metadata payload.
    /// </summary>
    public string? MetadataJson { get; init; }

    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;

    // --- Wire-format compatibility fields ---

    /// <summary>
    /// Previously used sender identity. Kept for backward compatibility
    /// with older clients that still reference this field over the wire.
    /// New code should use <see cref="Sender"/> exclusively.
    /// </summary>
    [Obsolete("Use Sender instead. Retained for wire-format compatibility.")]
    public string? LegacySenderId { get; init; }
}

```

## src/DenCore/Models/Document.cs

```csharp
namespace DenCore.Models;

/// <summary>
/// A versioned document that captures project knowledge —
/// specs, ADRs, conventions, references, notes, and memories.
/// </summary>
public sealed record Document
{
    public long Id { get; init; }
    public string ProjectId { get; init; } = string.Empty;

    /// <summary>Unique slug within the project namespace.</summary>
    public string Slug { get; init; } = string.Empty;
    public string Title { get; init; } = string.Empty;
    public string Content { get; init; } = string.Empty;

    /// <summary>Document type taxonomy.</summary>
    public DocumentKind Kind { get; init; } = DocumentKind.Spec;

    /// <summary>Comma-separated tags.</summary>
    public string? Tags { get; init; }

    /// <summary>Optional brief summary for listing/indexing.</summary>
    public string? Summary { get; init; }

    /// <summary>Current version sequence number.</summary>
    public int Version { get; init; } = 1;

    /// <summary>Visibility: normal, hidden, archived.</summary>
    public string Visibility { get; init; } = "normal";

    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;
    public DateTime UpdatedAt { get; init; } = DateTime.UtcNow;

    /// <summary>Agent identity that last modified this document.</summary>
    public string? ModifiedBy { get; init; }
}

```

## src/DenCore/Models/WorkerPoolModels.cs

```csharp
namespace DenCore.Models;

/// <summary>
/// Represents a registered worker in the DenCore worker pool.
/// Workers are agents capable of executing tasks (coding, reviewing, etc.).
/// </summary>
public sealed record PoolMember
{
    public long Id { get; init; }

    /// <summary>Unique agent identity string (e.g. "spawned-coder-7").</summary>
    public string WorkerIdentity { get; init; } = string.Empty;

    /// <summary>Profile identity for role-based grouping.</summary>
    public string ProfileIdentity { get; init; } = string.Empty;

    /// <summary>Functional role (e.g. "coder", "reviewer").</summary>
    public string WorkerRole { get; init; } = string.Empty;

    public PoolMemberStatus Status { get; init; } = PoolMemberStatus.Available;

    /// <summary>Comma-separated capability identifiers.</summary>
    public string Capabilities { get; init; } = string.Empty;

    /// <summary>Optional label for preferred assignment targeting.</summary>
    public string? PreferredLabel { get; init; }

    public DateTime RegisteredAt { get; init; } = DateTime.UtcNow;
    public DateTime? LastHeartbeat { get; init; }
}

/// <summary>
/// Tracks an active assignment of a pool member to a task.
/// </summary>
public sealed record WorkerAssignment
{
    public long Id { get; init; }
    public string ProjectId { get; init; } = string.Empty;
    public long TaskId { get; init; }
    public long PoolMemberId { get; init; }
    public string WorkerRole { get; init; } = string.Empty;

    /// <summary>Current assignment state.</summary>
    public string State { get; init; } = "ack";

    /// <summary>Nonce for idempotent release operations.</summary>
    public string? ReleaseNonce { get; init; }

    public DateTime AssignedAt { get; init; } = DateTime.UtcNow;
    public DateTime? CompletedAt { get; init; }
    public DateTime? ExpiresAt { get; init; }

    /// <summary>Opaque run identifier supplied by the worker at startup.</summary>
    public string? RunId { get; init; }
}

/// <summary>
/// Records a lease denial for diagnostic purposes.
/// </summary>
public sealed record NoCapacityRecord
{
    public long Id { get; init; }
    public string ProjectId { get; init; } = string.Empty;
    public long? TaskId { get; init; }
    public string ReasonCode { get; init; } = string.Empty;
    public string DiagnosticMessage { get; init; } = string.Empty;
    public string? CandidateStatsJson { get; init; }
    public string? RequestParamsJson { get; init; }
    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;
}

```

## src/DenCore/Models/Enums.cs

```csharp
namespace DenCore.Models;

/// <summary>Core status values for task lifecycle.</summary>
public enum TaskStatus
{
    Planned = 0,
    InProgress = 1,
    Review = 2,
    Blocked = 3,
    Done = 4,
    Cancelled = 5
}

/// <summary>Priority levels. Lower number = higher urgency.</summary>
public enum Priority
{
    Critical = 1,
    High = 2,
    Medium = 3,
    Low = 4,
    Backlog = 5
}

/// <summary>Delivery routing for outbound messages.</summary>
public enum DeliveryKind
{
    Direct = 0,
    Gateway = 1,
    Broadcast = 2,
    MCPTool = 3
}

/// <summary>Worker pool membership state.</summary>
public enum PoolMemberStatus
{
    Available = 0,
    Busy = 1,
    Quarantined = 2,
    Offboarded = 3
}

/// <summary>Review verdict for change requests.</summary>
public enum ReviewVerdict
{
    Pending = 0,
    Approved = 1,
    ChangesRequested = 2,
    Rejected = 3
}

/// <summary>Document category taxonomy.</summary>
public enum DocumentKind
{
    Spec = 0,
    Adr = 1,
    Convention = 2,
    Reference = 3,
    Note = 4,
    Memory = 5
}

/// <summary>Background dispatch processing phase.</summary>
public enum DispatchPhase
{
    Queued = 0,
    Processing = 1,
    Completed = 2,
    Failed = 3
}

```

## src/DenCore/Data/MessageRepository.cs

```csharp
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

```

## src/DenCore/Data/TaskRepository.cs

```csharp
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

```

## src/DenCore/Data/DocumentRepository.cs

```csharp
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

```

## src/DenCore/Data/WorkerPoolRepository.cs

```csharp
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

```

## src/DenCore/Data/DispatchRepository.cs

```csharp
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

```

## src/DenCore/Data/DatabaseInitializer.cs

```csharp
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

```

## src/DenCore/Services/ReviewWorkflowService.cs

```csharp
using DenCore.Data;
using DenCore.Models;
using Microsoft.Extensions.Logging;

namespace DenCore.Services;

/// <summary>
/// Orchestrates the review workflow for task changes.
/// Manages review verdicts, caching recent results for
/// quick retrieval during the same session.
/// </summary>
public sealed class ReviewWorkflowService
{
    private readonly TaskRepository _taskRepository;
    private readonly ILogger<ReviewWorkflowService> _logger;

    // In-memory verdict cache, keyed by task ID.
    // WARNING: Cached verdicts do NOT verify that the current
    // task head matches the head that was reviewed.
    private readonly Dictionary<long, (ReviewVerdict Verdict, string ReviewedHead)> _verdictCache = new();

    public ReviewWorkflowService(TaskRepository taskRepository, ILogger<ReviewWorkflowService> logger)
    {
        _taskRepository = taskRepository;
        _logger = logger;
    }

    /// <summary>
    /// Requests a review for a task at a specific commit head.
    /// </summary>
    public async Task<ReviewVerdict> RequestReviewAsync(long taskId, string commitHead)
    {
        var task = await _taskRepository.GetByIdAsync(taskId);
        if (task is null)
            throw new InvalidOperationException($"Task {taskId} not found");

        _logger.LogInformation("Review requested for task {TaskId} at head {Head}", taskId, commitHead);

        // Simulate review processing — in production this
        // dispatches to a reviewer agent.
        var verdict = ReviewVerdict.Approved;
        _verdictCache[taskId] = (verdict, commitHead);
        return verdict;
    }

    /// <summary>
    /// Gets the cached review verdict for a task.
    /// BUG: This returns the cached verdict without checking whether
    /// the current task head still matches the head that was reviewed.
    /// If a new commit lands on the task branch, the cached "approved"
    /// verdict is still returned even though the content has changed.
    /// </summary>
    public ReviewVerdict GetCachedVerdict(long taskId)
    {
        if (_verdictCache.TryGetValue(taskId, out var cached))
        {
            // XXX: No comparison between cached.ReviwedHead and the
            // current head of the task branch. The cache just returns
            // whatever value was last stored regardless of drift.
            _logger.LogInformation("Returning cached verdict {Verdict} for task {TaskId}",
                cached.Verdict, taskId);
            return cached.Verdict;
        }

        return ReviewVerdict.Pending;
    }

    /// <summary>
    /// Checks whether the cached review is still valid by comparing heads.
    /// This method exists but is NOT called by GetCachedVerdict.
    /// </summary>
    public bool IsReviewStillValid(long taskId, string currentHead)
    {
        if (_verdictCache.TryGetValue(taskId, out var cached))
            return cached.ReviewedHead == currentHead;
        return false;
    }

    /// <summary>
    /// Invalidates the review cache for a task (e.g. on new commit).
    /// </summary>
    public void InvalidateVerdict(long taskId)
    {
        _verdictCache.Remove(taskId);
        _logger.LogInformation("Review verdict invalidated for task {TaskId}", taskId);
    }
}

```

## src/DenCore/Services/WorkerLifecycleService.cs

```csharp
using DenCore.Data;
using DenCore.Models;
using Microsoft.Extensions.Logging;

namespace DenCore.Services;

/// <summary>
/// Manages worker lifecycle — assignment, heartbeat monitoring,
/// and release of completed/failed worker runs.
/// </summary>
public sealed class WorkerLifecycleService
{
    private readonly WorkerPoolRepository _poolRepository;
    private readonly ILogger<WorkerLifecycleService> _logger;

    public WorkerLifecycleService(WorkerPoolRepository poolRepository, ILogger<WorkerLifecycleService> logger)
    {
        _poolRepository = poolRepository;
        _logger = logger;
    }

    /// <summary>
    /// Assigns a worker to a task and transitions their pool status to busy.
    /// </summary>
    public async Task<WorkerAssignment?> AssignWorkerAsync(
        string projectId, long taskId, PoolMember worker, string role, string? runId = null)
    {
        if (worker.Status != PoolMemberStatus.Available)
            return null;

        var assignment = new WorkerAssignment
        {
            ProjectId = projectId,
            TaskId = taskId,
            PoolMemberId = worker.Id,
            WorkerRole = role,
            State = "ack",
            ReleaseNonce = Guid.NewGuid().ToString("N"),
            AssignedAt = DateTime.UtcNow,
            ExpiresAt = DateTime.UtcNow.AddMinutes(30),
            RunId = runId
        };

        var id = await _poolRepository.CreateAssignmentAsync(assignment);
        await _poolRepository.SetMemberStatusAsync(worker.Id, PoolMemberStatus.Busy);

        _logger.LogInformation("Worker {Worker} assigned to task {TaskId} as {Role} (assignment {AssignmentId})",
            worker.WorkerIdentity, taskId, role, id);

        return assignment with { Id = id };
    }

    /// <summary>
    /// Releases a worker from their assignment and returns them to the pool.
    /// BUG: The pool assignment is released (member status set to available)
    /// BEFORE waiting for the completion packet to be durably written/acked.
    /// This means another run can pick up the same assignment before the
    /// completion is visible, causing duplicate work or state corruption.
    /// </summary>
    public async Task ReleaseWorkerAsync(long assignmentId, long poolMemberId)
    {
        // STEP 1: Release the assignment — makes the pool member available
        // for new work immediately.
        await _poolRepository.ReleaseAssignmentAsync(assignmentId);
        await _poolRepository.SetMemberStatusAsync(poolMemberId, PoolMemberStatus.Available);

        _logger.LogInformation("Assignment {AssignmentId} released, member {MemberId} is available",
            assignmentId, poolMemberId);

        // STEP 2: "Write" the completion packet — simulated as a log message.
        // This happens AFTER the release, so the member can be re-assigned before
        // the completion is visible.
        await WriteCompletionPacketAsync(assignmentId);

        _logger.LogInformation("Completion packet written for assignment {AssignmentId} (after release)", assignmentId);
    }

    /// <summary>
    /// Simulates writing a completion packet to durable storage.
    /// </summary>
    private async Task WriteCompletionPacketAsync(long assignmentId)
    {
        // Simulate a 100ms async write
        await Task.Delay(100);
        _logger.LogDebug("Completion packet for assignment {AssignmentId} durably stored", assignmentId);
    }

    /// <summary>
    /// Records a heartbeat from a pool member.
    /// </summary>
    public async Task HeartbeatAsync(string workerIdentity)
    {
        // In production this updates last_heartbeat in the database.
        await Task.CompletedTask;
    }
}

```

## src/DenCore/Services/StaleAttentionRoutingService.cs

```csharp
using DenCore.Models;
using Microsoft.Extensions.Logging;

namespace DenCore.Services;

/// <summary>
/// Routes stale attention signals for tasks that have been
/// idle beyond configured thresholds. Runs on a background
/// timer and posts attention-grabbing messages.
/// </summary>
public sealed class StaleAttentionRoutingService
{
    private readonly ILogger<StaleAttentionRoutingService> _logger;
    private readonly TimeSpan _staleThreshold;
    private CancellationTokenSource? _loopCts;

    public StaleAttentionRoutingService(ILogger<StaleAttentionRoutingService> logger, TimeSpan? staleThreshold = null)
    {
        _logger = logger;
        _staleThreshold = staleThreshold ?? TimeSpan.FromMinutes(30);
    }

    /// <summary>
    /// Starts the stale-attention monitoring loop.
    /// Runs every 60 seconds checking for stale tasks.
    /// </summary>
    public Task StartMonitoringAsync()
    {
        _loopCts = new CancellationTokenSource();
        var token = _loopCts.Token;

        return Task.Run(async () =>
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    await CheckForStaleTasksAsync(token);
                }
                catch (Exception ex)
                {
                    // Per-iteration catch prevents loop crash.
                    _logger.LogError(ex, "Stale attention check failed");
                }

                await Task.Delay(TimeSpan.FromSeconds(60), token);
            }
        }, token);
    }

    private Task CheckForStaleTasksAsync(CancellationToken token)
    {
        // In production this would query for tasks with no updates
        // past the threshold and route attention notifications.
        _logger.LogDebug("Stale attention check completed (threshold: {Threshold})", _staleThreshold);
        return Task.CompletedTask;
    }

    public void StopMonitoring()
    {
        _loopCts?.Cancel();
    }
}

```

## src/DenCore.Service/Program.cs

```csharp
using DenCore.Data;
using DenCore.Services;
using DenCore.Llm;
using DenCore.Mcp;

namespace DenCore.Service;

public sealed class Program
{
    public static void Main(string[] args)
    {
        var builder = WebApplication.CreateBuilder(args);

        // Configure SQLite
        var connString = builder.Configuration.GetConnectionString("DefaultConnection")
            ?? "Data Source=dencore.db";

        // Register data layer
        builder.Services.AddSingleton(new MessageRepository(connString));
        builder.Services.AddSingleton(new TaskRepository(connString,
            builder.Services.BuildServiceProvider().GetRequiredService<MessageRepository>()));
        builder.Services.AddSingleton(new DocumentRepository(connString));
        builder.Services.AddSingleton(new WorkerPoolRepository(connString));
        builder.Services.AddSingleton(new DispatchRepository(connString,
            builder.Services.BuildServiceProvider().GetRequiredService<ILogger<DispatchRepository>>()));

        // Register services
        builder.Services.AddSingleton<ReviewWorkflowService>();
        builder.Services.AddSingleton<StaleAttentionRoutingService>();
        builder.Services.AddSingleton<WorkerLifecycleService>();

        // Register LLM
        builder.Services.AddHttpClient<ILlmClient, OpenAiCompatibleLlmClient>(client =>
        {
            client.BaseAddress = new Uri("http://192.168.1.10:8080");
        });

        // Register MCP
        builder.Services.AddSingleton<McpToolProfileRegistry>();

        // Register DatabaseInitializer
        builder.Services.AddSingleton<DatabaseInitializer>();

        var app = builder.Build();

        // Initialize database
        var dbInit = app.Services.GetRequiredService<DatabaseInitializer>();
        dbInit.InitializeAsync().GetAwaiter().GetResult();

        // Start dispatch background loop
        var dispatchRepo = app.Services.GetRequiredService<DispatchRepository>();
        dispatchRepo.RunBackgroundLoopAsync();

        // Health check endpoint — always returns OK regardless of DB state
        app.MapGet("/health", () =>
        {
            // XXX: Always returns "OK" without checking database connectivity
            // or migration state. Should probe DB and return 503 if unavailable.
            return Results.Ok(new { status = "OK", timestamp = DateTime.UtcNow });
        });

        // Register route groups
        Routes.MessageRoutes.Register(app);
        Routes.TaskRoutes.Register(app);
        Routes.WorkerRoutes.Register(app);
        Routes.DocumentRoutes.Register(app);

        // Register MCP tool endpoints
        Tools.MessageTools.Register(app);
        Tools.TaskTools.Register(app);
        Tools.WorkerTools.Register(app);
        Tools.CompletionTools.Register(app);

        // Configure URLs with a sensible default that can be overridden.
        // ASPNETCORE_URLS env var takes precedence per standard Kestrel behavior.
        app.Urls.Add("http://localhost:5000");

        app.Run();
    }
}

```

## src/DenCore.Service/Routes/MessageRoutes.cs

```csharp
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

```

## src/DenCore.Service/Routes/TaskRoutes.cs

```csharp
using DenCore.Data;
using DenCore.Models;

namespace DenCore.Service.Routes;

/// <summary>Route handlers for task operations.</summary>
public static class TaskRoutes
{
    public static void Register(WebApplication app)
    {
        var tasks = app.MapGroup("/api/tasks");

        tasks.MapGet("/", async (TaskRepository repo, string projectId) =>
        {
            var results = await repo.ListByProjectAsync(projectId);
            return Results.Ok(results);
        });

        tasks.MapGet("/{id:long}", async (TaskRepository repo, long id) =>
        {
            var task = await repo.GetByIdAsync(id);
            return task is not null ? Results.Ok(task) : Results.NotFound();
        });

        tasks.MapPost("/", async (TaskRepository repo, ProjectTask task) =>
        {
            var id = await repo.InsertAsync(task);
            return Results.Created($"/api/tasks/{id}", task with { Id = id });
        });

        // Legacy compatibility endpoint — routes to /api/items mapped to /api/tasks
        tasks.MapGet("/items/{id:long}", async (TaskRepository repo, long id) =>
        {
            var task = await repo.GetByIdAsync(id);
            return task is not null ? Results.Ok(task) : Results.NotFound();
        });

        // Get messages for a task using offset-based pagination.
        // Note: the MessageRoutes endpoint returns cursor-based results (nextCursor),
        // but this consumer still uses pageNumber/pageSize offset pagination.
        // The cursor field from the upstream endpoint is never read here.
        tasks.MapGet("/{id:long}/messages", async (TaskRepository repo, long id,
            int pageNumber = 1, int pageSize = 20) =>
        {
            var messages = await repo.GetTaskMessagesAsync(id, pageNumber, pageSize);
            var totalCount = await new MessageRepository(
                // XXX: This re-creates the connection string inline.
                // Should use DI, but not a planted issue.
                "Data Source=dencore.db").CountByTaskAsync(id);

            return Results.Ok(new
            {
                items = messages,
                pageNumber,
                pageSize,
                totalCount
            });
        });
    }
}

```

## src/DenCore.Service/Routes/DocumentRoutes.cs

```csharp
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

```

## src/DenCore.Service/Routes/WorkerRoutes.cs

```csharp
using DenCore.Data;
using DenCore.Models;
using DenCore.Services;

namespace DenCore.Service.Routes;

/// <summary>Route handlers for worker pool operations.</summary>
public static class WorkerRoutes
{
    public static void Register(WebApplication app)
    {
        var workers = app.MapGroup("/api/workers");

        workers.MapGet("/", async (WorkerPoolRepository repo, string? role) =>
        {
            if (!string.IsNullOrEmpty(role))
            {
                var available = await repo.ListAvailableByRoleAsync(role);
                return Results.Ok(available);
            }

            // Return all members (unfiltered) — just a stub for listing
            return Results.Ok(Array.Empty<PoolMember>());
        });

        workers.MapPost("/register", async (WorkerPoolRepository repo, PoolMember member) =>
        {
            var id = await repo.RegisterMemberAsync(member);
            return Results.Created($"/api/workers/{id}", member with { Id = id });
        });

        workers.MapPost("/assign", async (WorkerPoolRepository poolRepo,
            WorkerLifecycleService lifecycle, string projectId, long taskId,
            long workerId, string role) =>
        {
            var worker = await poolRepo.GetMemberByIdentityAsync(workerId.ToString());
            if (worker is null)
                return Results.NotFound(new { error = "Worker not found" });

            var assignment = await lifecycle.AssignWorkerAsync(projectId, taskId, worker, role);
            if (assignment is null)
                return Results.Conflict(new { error = "Worker is not available" });

            return Results.Ok(assignment);
        });

        workers.MapPost("/release", async (WorkerPoolRepository poolRepo,
            WorkerLifecycleService lifecycle, long assignmentId, long poolMemberId) =>
        {
            await lifecycle.ReleaseWorkerAsync(assignmentId, poolMemberId);
            return Results.Ok(new { status = "released" });
        });

        workers.MapGet("/assignments", async (WorkerPoolRepository repo, string projectId) =>
        {
            var assignments = await repo.ListActiveAssignmentsAsync(projectId);
            return Results.Ok(assignments);
        });
    }
}

```

## src/DenCore.Service/Tools/CompletionTools.cs

```csharp
using DenCore.Data;
using DenCore.Models;

namespace DenCore.Service.Tools;

/// <summary>
/// MCP tool handlers for completion and summarization operations.
/// These tools are invoked by agents to signal task completion
/// and generate context summaries.
/// 
/// TOOL SCHEMA ISSUE: The tool description for "triage_complete"
/// documents 'projectId' as a required field, but the actual
/// route handler expects 'project_id' (snake_case). Similarly,
/// "generate_summary" expects 'taskId' but the route uses 'task_id'.
/// This mismatch means agents sending well-formed tool calls
/// will get parameter binding failures.
/// </summary>
public static class CompletionTools
{
    public static void Register(WebApplication app)
    {
        var tools = app.MapGroup("/api/tools");

        // MCP tool: "den_core_triage_complete"
        // Tool description says: projectId (required), runId (required), resultJson (required)
        // Actual route handler expects: project_id, run_id, result_json
        tools.MapPost("/triage-complete", async (DispatchRepository dispatchRepo,
            string project_id, string run_id, string result_json) =>
        {
            var entry = new DispatchEntry
            {
                ProjectId = project_id,
                DeliveryKind = DeliveryKind.MCPTool,
                PayloadJson = result_json,
                Phase = DispatchPhase.Queued
            };

            var id = await dispatchRepo.EnqueueAsync(entry);
            return Results.Ok(new { dispatchId = id, runId = run_id });
        });

        // MCP tool: "den_core_generate_summary"
        // Tool description says: taskId (required), format (optional)
        // Actual route handler expects: task_id, output_format
        tools.MapPost("/generate-summary", async (long task_id, string? output_format) =>
        {
            // In production, this would call the librarian to summarize
            // the task's context into the requested format.
            return Results.Ok(new
            {
                taskId = task_id,
                summary = $"Summary for task {task_id} (format: {output_format ?? "default"})",
                generatedAt = DateTime.UtcNow
            });
        });
    }
}

```

## docs/architecture-brief.md

# DenCore v1 — Architecture Brief

## Overview

DenCore is the central service for the Den intelligent agent platform. It provides task management, messaging, document storage, worker pool orchestration, MCP tool routing, and LLM integration for agent-to-agent and agent-to-human collaboration.

## High-Level Architecture

```
┌──────────────────────────────────────────────────────┐
│                   DenCore.Service                     │
│  (ASP.NET Minimal API — Kestrel host, SQLite store)  │
│                                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │  Routes   │ │  Tools   │ │  MCP     │ │  LLM     │ │
│  │ (REST)    │ │ (MCP)    │ │ Registry │ │ Client   │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       │             │            │             │        │
│  ┌────┴─────────────┴────────────┴─────────────┴─────┐ │
│  │                  Services                          │ │
│  │  ReviewWorkflow  │  StaleAttention │  WorkerLife   │ │
│  └────────────────────────┬──────────────────────────┘ │
│                           │                             │
│  ┌────────────────────────┴──────────────────────────┐ │
│  │               Data Layer (Repositories)            │ │
│  │  Dapper + SQLite — tasks, messages, documents,     │ │
│  │  pool_members, worker_assignments, dispatch_queue  │ │
│  └───────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

## Key Components

### Models (`DenCore/Models/`)
Core domain types: `ProjectTask`, `Message`, `Document`, `PoolMember`, `WorkerAssignment`, `DispatchEntry`, `TaskHistory`, gateway contracts, and enumerations. Uses C# records with nullable reference types.

### Data Layer (`DenCore/Data/`)
Dapper-based SQLite repositories. Each repository owns its connection management. `DatabaseInitializer` creates schema and pre-loads config cache on startup.

### Services (`DenCore/Services/`)
- **ReviewWorkflowService**: Manages review lifecycle with a per-session verdict cache.
- **StaleAttentionRoutingService**: Background monitor for idle tasks.
- **WorkerLifecycleService**: Assignment/release orchestration for pool members.

### MCP (`DenCore/Mcp/`)
Tool profile registry mapping MCP tool names to schemas and handler routes. Used by the tool routing layer.

### LLM (`DenCore/Llm/`)
OpenAI-compatible client for completions and structured output. Used by the Librarian for context summarization.

### Service Layer (`DenCore.Service/`)
Minimal API endpoints for REST (routes) and MCP tool handlers (tools). Startup in `Program.cs` wires everything together.

## Data Flow

1. **Agent sends message** → `MessageRoutes` → `MessageRepository` → SQLite
2. **Worker assigned to task** → `WorkerRoutes` → `WorkerLifecycleService` → `WorkerPoolRepository`
3. **Review requested** → `ReviewWorkflowService` caches verdict
4. **Background dispatch** → `DispatchRepository.RunBackgroundLoopAsync()` polls queue
5. **LLM summarization** → `LibrarianService` → `OpenAiCompatibleLlmClient`

## Database

SQLite with 10 core tables. Connection string configurable via `ConnectionStrings:DefaultConnection`. Schema auto-created on startup.

## Decision Records

- **SQLite**: Simple single-file storage suitable for single-node deployment.
- **Dapper**: Lightweight ORM — full control over SQL, no EF Core overhead.
- **In-memory caching**: TaskRepository and ReviewWorkflowService use dictionaries for fast reads. Database remains authoritative source of truth.
- **Minimal API**: Modern ASP.NET pattern with less boilerplate than controllers.
- **MCP over HTTP**: Tool endpoints are HTTP POST handlers; no WebSocket transport in v1.

## docs/api-contract.md

# DenCore v1 — API Contract

## Base URL

```
http://localhost:5000
```

## Authentication

All endpoints require a valid API key in the `X-Api-Key` header. *(Not yet implemented in v1.)*

## Endpoints

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health check |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks?projectId={id}` | List tasks in a project |
| GET | `/api/tasks/{id}` | Get task by ID |
| POST | `/api/tasks` | Create a new task |
| GET | `/api/tasks/{id}/messages` | Get messages for a task (offset pagination) |

### Messages

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/messages?projectId={id}&cursor={c}&limit={n}` | List messages (cursor pagination) |
| GET | `/api/messages/{id}` | Get message by ID |
| POST | `/api/messages` | Send a message |

### Documents

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/documents/{id}` | Get document by ID |
| GET | `/api/documents/by-slug/{projectId}/{slug}` | Get document by project + slug |
| POST | `/api/documents` | Create document |
| PUT | `/api/documents/{id}` | Update document |
| DELETE | `/api/documents/{id}` | Delete document |
| GET | `/api/documents?projectId={id}` | List documents |

### Workers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/workers?role={role}` | List workers (optional role filter) |
| POST | `/api/workers/register` | Register a pool member |
| POST | `/api/workers/assign` | Assign worker to task |
| POST | `/api/workers/release` | Release worker from assignment |
| GET | `/api/workers/assignments?projectId={id}` | List active assignments |

### MCP Tools

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tools/send-message` | Send a message (MCP) |
| POST | `/api/tools/get-messages` | Get messages (MCP) |
| POST | `/api/tools/list-tasks` | List tasks (MCP) |
| POST | `/api/tools/get-task` | Get task (MCP) |
| POST | `/api/tools/create-task` | Create task (MCP) |
| POST | `/api/tools/worker-complete` | Report worker completion |
| POST | `/api/tools/heartbeat` | Worker heartbeat |
| POST | `/api/tools/triage-complete` | Triage completion signal |
| POST | `/api/tools/generate-summary` | Generate context summary |

## Pagination

- **Messages (REST)**: Cursor-based. Response includes `nextCursor` field.
- **Task Messages (sub-resource)**: Offset-based. Uses `pageNumber` and `pageSize`.
- **Documents**: No pagination in v1.

## Error Responses

```json
{
  "error": "description of the problem"
}
```

Standard HTTP codes: 200, 201, 204, 400, 404, 409, 500.

## docs/deployment.md

# DenCore v1 — Deployment Guide

## Prerequisites

- .NET 8 SDK
- SQLite 3 (runtime dependency, auto-created)
- Optional: LLM endpoint for librarian features

## Build

```bash
cd repo
dotnet restore
dotnet build -c Release
```

## Configuration

Configuration is read from `appsettings.json` and environment variables. Key settings:

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `ConnectionStrings:DefaultConnection` | `CONNECTIONSTRINGS__DEFAULTCONNECTION` | `Data Source=dencore.db` | SQLite connection string |
| LLM endpoint (hardcoded) | — | `http://192.168.1.10:8080` | OpenAI-compatible API base URL |
| `ASPNETCORE_URLS` | `ASPNETCORE_URLS` | `http://localhost:5000` | Kestrel listen URLs |

> **Note**: The LLM endpoint is currently hardcoded in `Program.cs` (line 30).
> Change `192.168.1.10` to your LLM host before deploying to production.
> This should be externalized to configuration in a future release.

## Run

```bash
cd repo/src/DenCore.Service
dotnet run -c Release
```

Or as a published deployment:

```bash
dotnet publish -c Release -o ./publish
cd publish
./DenCore.Service
```

## Health Check

```
GET http://localhost:5000/health
```

Expected response: `{"status":"OK","timestamp":"..."}`

## Database

The SQLite database file is created automatically at startup in the working directory.
To reset, delete the `dencore.db` file and restart the service.

## Logging

Structured logging via `ILogger<T>`. Configure log levels in `appsettings.json`.
Default level: Information.

## Known Limitations (v1)

1. Single-node only — no horizontal scaling
2. In-memory caches do not persist across restarts
3. LLM endpoint IP is hardcoded (see Configuration note above)
4. No authentication/authorization
5. Health endpoint does not verify database connectivity
6. Background dispatch loop has no health signal

## Deprecation Notes

- The `/api/items/{id}` compat route is kept alongside `/api/tasks/{id}` and will be removed in v2.
- `McpToolProfile` field on `ProjectTask` model is deprecated in favor of `McpToolProfileRegistry`.
- `LegacySenderId` on `Message` is kept for wire-format compatibility.
