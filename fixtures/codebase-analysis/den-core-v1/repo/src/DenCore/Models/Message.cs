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
