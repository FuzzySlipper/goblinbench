namespace DenCore.Models;

/// <summary>
/// Contract for outbound message delivery via a gateway endpoint.
/// Gateways are external receivers (webhooks, bridges, relays).
/// </summary>
public sealed record GatewayContract
{
    public long Id { get; init; }
    public string ProjectId { get; init; } = string.Empty;
    public string GatewayUrl { get; init; } = string.Empty;

    /// <summary>HTTP method used for delivery (POST, PUT).</summary>
    public string HttpMethod { get; init; } = "POST";

    /// <summary>Optional bearer token or auth header value.</summary>
    public string? AuthToken { get; init; }

    /// <summary>Optional HMAC signing secret for payload integrity.</summary>
    public string? SigningSecret { get; init; }

    /// <summary>Content type header value.</summary>
    public string ContentType { get; init; } = "application/json";

    /// <summary>Optional JSON template for transforming payloads.</summary>
    public string? TransformTemplateJson { get; init; }

    /// <summary>Whether this gateway is currently active.</summary>
    public bool IsActive { get; init; } = true;

    /// <summary>Graceful drain flag — set false to stop new deliveries.</summary>
    public bool AcceptingDeliveries { get; init; } = true;

    public DateTime CreatedAt { get; init; } = DateTime.UtcNow;
    public DateTime? LastDeliveryAt { get; init; }
}
