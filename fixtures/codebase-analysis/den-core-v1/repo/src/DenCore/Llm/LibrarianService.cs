using DenCore.Data;
using DenCore.Models;
using Microsoft.Extensions.Logging;

namespace DenCore.Llm;

/// <summary>
/// The librarian service provides context-aware retrieval for agents.
/// It queries tasks, documents, and messages to build relevant context
/// packets, optionally using an LLM for summarization.
/// </summary>
public sealed class LibrarianService
{
    private readonly TaskRepository _taskRepository;
    private readonly DocumentRepository _documentRepository;
    private readonly MessageRepository _messageRepository;
    private readonly ILlmClient _llmClient;
    private readonly ILogger<LibrarianService> _logger;

    public LibrarianService(
        TaskRepository taskRepository,
        DocumentRepository documentRepository,
        MessageRepository messageRepository,
        ILlmClient llmClient,
        ILogger<LibrarianService> logger)
    {
        _taskRepository = taskRepository;
        _documentRepository = documentRepository;
        _messageRepository = messageRepository;
        _llmClient = llmClient;
        _logger = logger;
    }

    /// <summary>
    /// Retrieves relevant context for a given project and query.
    /// Returns a packet with matched tasks, documents, and messages.
    /// </summary>
    public async Task<LibrarianPacket> GetContextAsync(string projectId, string query, long? taskId = null)
    {
        _logger.LogInformation("Librarian context query: project={Project}, query={Query}", projectId, query);

        var packet = new LibrarianPacket
        {
            ProjectId = projectId,
            Query = query
        };

        // Gather tasks
        var tasks = await _taskRepository.ListByProjectAsync(projectId);
        packet.RelevantTasks = tasks
            .Where(t => t.Title.Contains(query, StringComparison.OrdinalIgnoreCase) ||
                        t.Description.Contains(query, StringComparison.OrdinalIgnoreCase))
            .Take(5)
            .ToList();

        // Gather documents
        var docs = await _documentRepository.ListByProjectAsync(projectId);
        packet.RelevantDocuments = docs
            .Where(d => d.Title.Contains(query, StringComparison.OrdinalIgnoreCase) ||
                        (d.Summary?.Contains(query, StringComparison.OrdinalIgnoreCase) ?? false))
            .Take(5)
            .ToList();

        // Gather recent messages
        var messages = await _messageRepository.ListByProjectAsync(projectId);
        packet.RecentMessages = messages.Take(10).ToList();

        // Optionally generate a summary via LLM
        if (packet.RelevantTasks.Count > 0 || packet.RelevantDocuments.Count > 0)
        {
            try
            {
                var summaryPrompt = $"Summarize the following context for project {projectId} related to: {query}";
                var contextItems = string.Join("\n",
                    packet.RelevantTasks.Select(t => $"- Task: {t.Title} ({t.Status})"));
                packet.Summary = await _llmClient.CompleteAsync(summaryPrompt, contextItems);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "LLM summarization failed for librarian query");
                packet.Summary = "Summary generation failed.";
            }
        }

        return packet;
    }
}

/// <summary>
/// Context packet returned by the librarian service.
/// </summary>
public sealed record LibrarianPacket
{
    public string ProjectId { get; init; } = string.Empty;
    public string Query { get; init; } = string.Empty;
    public IReadOnlyList<ProjectTask> RelevantTasks { get; init; } = Array.Empty<ProjectTask>();
    public IReadOnlyList<Document> RelevantDocuments { get; init; } = Array.Empty<Document>();
    public IReadOnlyList<Message> RecentMessages { get; init; } = Array.Empty<Message>();
    public string? Summary { get; init; }
    public DateTime GeneratedAt { get; init; } = DateTime.UtcNow;
}
