using DenCore.Data;
using DenCore.Models;

namespace DenCore.Service.Tools;

/// <summary>
/// MCP tool handlers for completion and summarization operations.
/// These tools are invoked by agents to signal task completion
/// and generate context summaries.
/// 
/// TOOL SCHEMA ISSUE: The tool description for "triage_complete"
/// documents 'projectId' as a required field, but the actual
/// route handler expects 'project_id' (snake_case). Similarly,
/// "generate_summary" expects 'taskId' but the route uses 'task_id'.
/// This mismatch means agents sending well-formed tool calls
/// will get parameter binding failures.
/// </summary>
public static class CompletionTools
{
    public static void Register(WebApplication app)
    {
        var tools = app.MapGroup("/api/tools");

        // MCP tool: "den_core_triage_complete"
        // Tool description says: projectId (required), runId (required), resultJson (required)
        // Actual route handler expects: project_id, run_id, result_json
        tools.MapPost("/triage-complete", async (DispatchRepository dispatchRepo,
            string project_id, string run_id, string result_json) =>
        {
            var entry = new DispatchEntry
            {
                ProjectId = project_id,
                DeliveryKind = DeliveryKind.MCPTool,
                PayloadJson = result_json,
                Phase = DispatchPhase.Queued
            };

            var id = await dispatchRepo.EnqueueAsync(entry);
            return Results.Ok(new { dispatchId = id, runId = run_id });
        });

        // MCP tool: "den_core_generate_summary"
        // Tool description says: taskId (required), format (optional)
        // Actual route handler expects: task_id, output_format
        tools.MapPost("/generate-summary", async (long task_id, string? output_format) =>
        {
            // In production, this would call the librarian to summarize
            // the task's context into the requested format.
            return Results.Ok(new
            {
                taskId = task_id,
                summary = $"Summary for task {task_id} (format: {output_format ?? "default"})",
                generatedAt = DateTime.UtcNow
            });
        });
    }
}
