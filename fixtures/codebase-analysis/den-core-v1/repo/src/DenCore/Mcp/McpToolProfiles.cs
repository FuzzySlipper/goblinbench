namespace DenCore.Mcp;

/// <summary>
/// Static definitions of MCP tool names and their expected
/// input/output schemas. These are used by the MCP routing
/// layer and must stay in sync with actual route handlers.
/// </summary>
public static class McpToolProfiles
{
    // Task tools
    public const string ListTasks = "den_core_list_tasks";
    public const string GetTask = "den_core_get_task";
    public const string CreateTask = "den_core_create_task";

    // Message tools
    public const string SendMessage = "den_core_send_message";
    public const string GetMessages = "den_core_get_messages";

    // Document tools
    public const string GetDocument = "den_core_get_document";
    public const string StoreDocument = "den_core_store_document";

    // Worker tools
    public const string WorkerComplete = "den_core_worker_complete";
    public const string Heartbeat = "den_core_heartbeat";

    // Agent-to-agent
    public const string AgentNotify = "den_core_agent_notify";

    // Completion / summarization
    public const string TriageComplete = "den_core_triage_complete";
    public const string GenerateSummary = "den_core_generate_summary";
}
