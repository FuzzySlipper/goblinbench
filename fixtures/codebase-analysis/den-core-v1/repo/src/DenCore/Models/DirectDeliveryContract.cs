namespace DenCore.Models;

/// <summary>
/// Contract for direct (non-gateway) message delivery to an agent instance.
/// Used when the delivery routing is Direct rather than Gateway.
/// </summary>
public sealed record DirectDeliveryContract
{
    public long Id { get; init; }
    public string ProjectId { get; init; } = string.Empty;

    /// <summary>Target agent identity for delivery.</summary>
    public string TargetAgentIdentity { get; init; } = string.Empty;

    /// <summary>Transport kind (e.g. "mcp", "websocket", "channel").</summary>
    public string TransportKind { get; init; } = "mcp";

    /// <summary>Endpoint URL or transport address.</summary>
    public string EndpointUrl { get; init; } = string.Empty;

    /// <summary>Optional session or connection ID for routed delivery.</summary>
    public string? SessionId { get; init; }

    /// <summary>Whether this delivery contract is active.</summary>
    public bool IsActive { get; init; } = true;

    /// <summary>Delivery priority hint (higher = more urgent).</summary>
    public int PriorityHint { get; init; } = 0;

    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;
}
