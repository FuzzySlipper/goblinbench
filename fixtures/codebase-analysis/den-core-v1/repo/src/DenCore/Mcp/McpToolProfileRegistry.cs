using DenCore.Models;

namespace DenCore.Mcp;

/// <summary>
/// Defines an MCP tool profile — a named capability offered
/// to agents through the MCP protocol layer.
/// </summary>
public sealed record McpToolProfile
{
    public string Name { get; init; } = string.Empty;
    public string Description { get; init; } = string.Empty;
    public string InputSchemaJson { get; init; } = "{}";
    public bool IsEnabled { get; init; } = true;
    public string? HandlerRoute { get; init; }
}

/// <summary>
/// Registry of all MCP tool profiles available in the system.
/// Profiles map tool names to handler routes and input schemas.
/// </summary>
public sealed class McpToolProfileRegistry
{
    private readonly Dictionary<string, McpToolProfile> _profiles = new(StringComparer.OrdinalIgnoreCase);

    public McpToolProfileRegistry()
    {
        RegisterBuiltInProfiles();
    }

    private void RegisterBuiltInProfiles()
    {
        Register(new McpToolProfile
        {
            Name = "den_core_list_tasks",
            Description = "Lists tasks in a project with optional filters",
            InputSchemaJson = """{"type":"object","properties":{"projectId":{"type":"string"},"status":{"type":"string"}}}""",
            HandlerRoute = "/api/tasks"
        });

        Register(new McpToolProfile
        {
            Name = "den_core_get_task",
            Description = "Gets full task details by ID",
            InputSchemaJson = """{"type":"object","properties":{"taskId":{"type":"integer"}}}""",
            HandlerRoute = "/api/tasks/{taskId}"
        });

        Register(new McpToolProfile
        {
            Name = "den_core_send_message",
            Description = "Sends a message in a project",
            InputSchemaJson = """{"type":"object","properties":{"projectId":{"type":"string"},"content":{"type":"string"},"sender":{"type":"string"}}}""",
            HandlerRoute = "/api/messages"
        });

        Register(new McpToolProfile
        {
            Name = "den_core_worker_complete",
            Description = "Reports completion of a worker run with results",
            InputSchemaJson = """{"type":"object","properties":{"runId":{"type":"string"},"resultJson":{"type":"string"},"project_id":{"type":"string"}}}""",
            HandlerRoute = "/api/tools/worker-complete"
        });
    }

    public void Register(McpToolProfile profile)
    {
        _profiles[profile.Name] = profile;
    }

    public McpToolProfile? GetProfile(string name)
    {
        return _profiles.GetValueOrDefault(name);
    }

    public IReadOnlyList<McpToolProfile> ListAll()
    {
        return _profiles.Values.ToList();
    }

    public IReadOnlyList<McpToolProfile> ListEnabled()
    {
        return _profiles.Values.Where(p => p.IsEnabled).ToList();
    }
}
