namespace DenCore.Models;

/// <summary>
/// An entry in the background dispatch queue for outbound
/// message delivery, MCP tool invocations, and other async operations.
/// </summary>
public sealed record DispatchEntry
{
    public long Id { get; init; }
    public string ProjectId { get; init; } = string.Empty;

    /// <summary>Dispatch target kind — Direct, Gateway, Broadcast, MCPTool.</summary>
    public DeliveryKind DeliveryKind { get; init; }

    /// <summary>JSON-serialized payload for the dispatch handler.</summary>
    public string PayloadJson { get; init; } = string.Empty;

    /// <summary>Current processing phase.</summary>
    public DispatchPhase Phase { get; init; } = DispatchPhase.Queued;

    /// <summary>Number of retry attempts so far.</summary>
    public int RetryCount { get; init; }

    /// <summary>Maximum retries before permanent failure.</summary>
    public int MaxRetries { get; init; } = 3;

    /// <summary>Error message from last failed attempt, if any.</summary>
    public string? LastError { get; init; }

    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;
    public DateTime? NextAttemptAt { get; init; }
    public DateTime? CompletedAt { get; init; }
}
