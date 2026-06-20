using DenCore.Data;
using DenCore.Services;
using DenCore.Llm;
using DenCore.Mcp;

namespace DenCore.Service;

public sealed class Program
{
    public static void Main(string[] args)
    {
        var builder = WebApplication.CreateBuilder(args);

        // Configure SQLite
        var connString = builder.Configuration.GetConnectionString("DefaultConnection")
            ?? "Data Source=dencore.db";

        // Register data layer
        builder.Services.AddSingleton(new MessageRepository(connString));
        builder.Services.AddSingleton(new TaskRepository(connString,
            builder.Services.BuildServiceProvider().GetRequiredService<MessageRepository>()));
        builder.Services.AddSingleton(new DocumentRepository(connString));
        builder.Services.AddSingleton(new WorkerPoolRepository(connString));
        builder.Services.AddSingleton(new DispatchRepository(connString,
            builder.Services.BuildServiceProvider().GetRequiredService<ILogger<DispatchRepository>>()));

        // Register services
        builder.Services.AddSingleton<ReviewWorkflowService>();
        builder.Services.AddSingleton<StaleAttentionRoutingService>();
        builder.Services.AddSingleton<WorkerLifecycleService>();

        // Register LLM
        builder.Services.AddHttpClient<ILlmClient, OpenAiCompatibleLlmClient>(client =>
        {
            client.BaseAddress = new Uri("http://192.168.1.10:8080");
        });

        // Register MCP
        builder.Services.AddSingleton<McpToolProfileRegistry>();

        // Register DatabaseInitializer
        builder.Services.AddSingleton<DatabaseInitializer>();

        var app = builder.Build();

        // Initialize database
        var dbInit = app.Services.GetRequiredService<DatabaseInitializer>();
        dbInit.InitializeAsync().GetAwaiter().GetResult();

        // Start dispatch background loop
        var dispatchRepo = app.Services.GetRequiredService<DispatchRepository>();
        dispatchRepo.RunBackgroundLoopAsync();

        // Health check endpoint — always returns OK regardless of DB state
        app.MapGet("/health", () =>
        {
            // XXX: Always returns "OK" without checking database connectivity
            // or migration state. Should probe DB and return 503 if unavailable.
            return Results.Ok(new { status = "OK", timestamp = DateTime.UtcNow });
        });

        // Register route groups
        Routes.MessageRoutes.Register(app);
        Routes.TaskRoutes.Register(app);
        Routes.WorkerRoutes.Register(app);
        Routes.DocumentRoutes.Register(app);

        // Register MCP tool endpoints
        Tools.MessageTools.Register(app);
        Tools.TaskTools.Register(app);
        Tools.WorkerTools.Register(app);
        Tools.CompletionTools.Register(app);

        // Configure URLs with a sensible default that can be overridden.
        // ASPNETCORE_URLS env var takes precedence per standard Kestrel behavior.
        app.Urls.Add("http://localhost:5000");

        app.Run();
    }
}
