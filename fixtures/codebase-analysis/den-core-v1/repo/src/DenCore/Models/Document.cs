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
