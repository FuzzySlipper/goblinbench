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
