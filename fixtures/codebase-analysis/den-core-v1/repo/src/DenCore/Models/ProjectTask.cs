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
