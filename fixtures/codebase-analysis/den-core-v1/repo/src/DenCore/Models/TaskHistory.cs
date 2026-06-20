namespace DenCore.Models;

/// <summary>
/// An audit record of a state transition on a project task.
/// Immutable after creation.
/// </summary>
public sealed record TaskHistory
{
    public long Id { get; init; }
    public long TaskId { get; init; }
    public string ProjectId { get; init; } = string.Empty;

    /// <summary>The agent that performed the transition.</summary>
    public string ChangedBy { get; init; } = string.Empty;

    /// <summary>Previous status value.</summary>
    public string? FromStatus { get; init; }

    /// <summary>New status value.</summary>
    public string? ToStatus { get; init; }

    /// <summary>Optional comment describing the change.</summary>
    public string? Comment { get; init; }

    /// <summary>Snapshot of the task fields after the change.</summary>
    public string? SnapshotJson { get; init; }

    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;
}
