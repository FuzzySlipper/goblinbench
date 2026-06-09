using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using GoblinBench.Core;

namespace GoblinBench.Core.Tests;

public class FakeDenMcpGeneratorTests
{
    [Fact]
    public async Task Generator_NormalizesMcpToolsListAndBuildsSideEffectSafeScenario()
    {
        var repoRoot = FindRepoRoot();
        var tempDir = Path.Combine(Path.GetTempPath(), "goblinbench-fake-den-mcp-" + Guid.NewGuid().ToString("N"));
        var catalogPath = Path.Combine(tempDir, "fixtures", "fake-den-mcp", "catalog.json");
        var scenarioPath = Path.Combine(tempDir, "suites", "fake-den-mcp", "generated.json");

        var result = await RunPythonAsync(repoRoot,
            "scripts/generate-fake-den-mcp-catalog.py",
            "--input", "tests/fixtures/den-mcp-tools-list.sample.json",
            "--include-regex", "^mcp_den_",
            "--catalog-output", catalogPath,
            "--scenario-output", scenarioPath,
            "--scenario-id", "fake-den-mcp.generated-task-read",
            "--prompt", "Use fake Den MCP to read task 2085. Do not update or store anything.",
            "--expected-tool", "mcp_den_get_task",
            "--expected-arg", "task_id=2085");

        Assert.Equal(0, result.ExitCode);
        Assert.True(File.Exists(catalogPath), result.StdErr);
        Assert.True(File.Exists(scenarioPath), result.StdErr);

        using var catalogDoc = JsonDocument.Parse(await File.ReadAllTextAsync(catalogPath));
        var fakeMcp = catalogDoc.RootElement.GetProperty("fake_mcp");
        var tools = fakeMcp.GetProperty("tools");
        Assert.Equal(4, tools.GetArrayLength());
        var getTask = tools.EnumerateArray().Single(t => t.GetProperty("name").GetString() == "mcp_den_get_task");
        Assert.True(getTask.TryGetProperty("input_schema", out var schema));
        Assert.True(schema.TryGetProperty("required", out _));

        using var scenarioDoc = JsonDocument.Parse(await File.ReadAllTextAsync(scenarioPath));
        var scenarioRoot = scenarioDoc.RootElement;
        Assert.Equal("fake-den-mcp.generated-task-read", scenarioRoot.GetProperty("id").GetString());
        Assert.Equal("fake-den-mcp", scenarioRoot.GetProperty("suite").GetString());
        Assert.Contains("mcp_den_update_task", scenarioRoot.GetProperty("scoring").GetProperty("parameters").GetProperty("mcp-tool-use").GetProperty("forbidden_tools").EnumerateArray().Select(x => x.GetString()));
        Assert.Contains("fake_den_mcp_side_effect_blocked", await File.ReadAllTextAsync(scenarioPath));
    }

    [Fact]
    public async Task Generator_FetchesStreamableHttpMcpToolsListFromSseEndpoint()
    {
        var repoRoot = FindRepoRoot();
        var tempDir = Path.Combine(Path.GetTempPath(), "goblinbench-fake-den-mcp-http-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);
        var serverPath = Path.Combine(tempDir, "fake_streamable_mcp_server.py");
        var catalogPath = Path.Combine(tempDir, "catalog.json");
        var port = GetFreeTcpPort();

        await File.WriteAllTextAsync(serverPath, """
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_POST(self):
        length = int(self.headers.get('content-length', '0'))
        body = json.loads(self.rfile.read(length).decode('utf-8'))
        if body.get('method') == 'initialize':
            payload = {
                'jsonrpc': '2.0',
                'id': body.get('id'),
                'result': {
                    'protocolVersion': '2024-11-05',
                    'serverInfo': {'name': 'FakeDenCore.Service', 'version': '0.0-test'},
                    'capabilities': {'tools': {}}
                }
            }
            self._send_sse(payload, session='test-session-123')
            return
        if body.get('method') == 'tools/list':
            payload = {
                'jsonrpc': '2.0',
                'id': body.get('id'),
                'result': {
                    'tools': [
                        {'name': 'update_task', 'description': 'Update task', 'inputSchema': {'type': 'object', 'properties': {'task_id': {'type': 'integer'}}}},
                        {'name': 'get_task', 'description': 'Get task', 'inputSchema': {'type': 'object', 'properties': {'task_id': {'type': 'integer'}}, 'required': ['task_id']}},
                    ]
                }
            }
            self._send_sse(payload)
            return
        self.send_response(404)
        self.send_header('content-length', '0')
        self.end_headers()

    def log_message(self, *_):
        pass

    def _send_sse(self, payload, session=None):
        data = ('data: ' + json.dumps(payload) + '\n\n').encode('utf-8')
        self.send_response(200)
        self.send_header('content-type', 'text/event-stream')
        self.send_header('content-length', str(len(data)))
        if session:
            self.send_header('Mcp-Session-Id', session)
        self.end_headers()
        self.wfile.write(data)

ThreadingHTTPServer(('127.0.0.1', __PORT__), Handler).serve_forever()
""".Replace("__PORT__", port.ToString()));

        using var server = StartPython(repoRoot, serverPath);
        try
        {
            await WaitForServerAsync(port);

            var result = await RunPythonAsync(repoRoot,
                "scripts/generate-fake-den-mcp-catalog.py",
                "--mcp-url", $"http://127.0.0.1:{port}/mcp",
                "--name-prefix", "mcp_den_",
                "--include-regex", "^mcp_den_",
                "--catalog-output", catalogPath);

            Assert.True(result.ExitCode == 0, result.StdErr + result.StdOut);
            Assert.True(File.Exists(catalogPath), result.StdErr);

            using var catalogDoc = JsonDocument.Parse(await File.ReadAllTextAsync(catalogPath));
            var root = catalogDoc.RootElement;
            Assert.Equal("mcp-http:http://127.0.0.1:" + port + "/mcp", root.GetProperty("source").GetString());
            Assert.Equal(2, root.GetProperty("tool_count").GetInt32());
            Assert.Equal("FakeDenCore.Service", root.GetProperty("mcp_server_info").GetProperty("name").GetString());
            Assert.Equal("2024-11-05", root.GetProperty("mcp_protocol_version").GetString());
            var toolNames = root.GetProperty("fake_mcp").GetProperty("tools").EnumerateArray().Select(t => t.GetProperty("name").GetString()).ToArray();
            Assert.Equal(new[] { "mcp_den_get_task", "mcp_den_update_task" }, toolNames);
        }
        finally
        {
            if (!server.HasExited)
                server.Kill(entireProcessTree: true);
        }
    }

    [Fact]
    public async Task StaticFakeDenMcpScenario_IsDiscoverableAndUsesMcpToolUseScorer()
    {
        var repoRoot = FindRepoRoot();
        var scenarios = await ScenarioDiscovery.DiscoverAsync(Path.Combine(repoRoot, "suites"));
        var scenario = Assert.Single(scenarios, s => s.Id == "fake-den-mcp.task-read-vs-update");

        Assert.Equal("fake-den-mcp", scenario.Suite);
        Assert.Contains("mcp-tool-use", scenario.Scoring!.Scorers);
        Assert.True(scenario.Input.ContainsKey("fake_mcp"));
        Assert.True(scenario.Input.ContainsKey("scripted_tool_calls"));
    }

    [Fact]
    public async Task DenMcpAmbiguitySuite_CoversNamedRegressionAndRoutingCases()
    {
        var repoRoot = FindRepoRoot();
        var scenarios = await ScenarioDiscovery.DiscoverAsync(Path.Combine(repoRoot, "suites"));
        var ambiguityScenarios = scenarios.Where(s => s.Suite == "den-mcp-ambiguity").ToList();

        Assert.True(ambiguityScenarios.Count >= 6);
        Assert.Contains(ambiguityScenarios, s => s.Id == "den-mcp-ambiguity.den-mcp-doc-system-planner");
        Assert.Contains(ambiguityScenarios, s => s.Id.Contains("project-explicit", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(ambiguityScenarios, s => s.Id.Contains("persona-not-project", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(ambiguityScenarios, s => s.Id.Contains("search-vs-get", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(ambiguityScenarios, s => s.Id.Contains("comment-vs-update", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(ambiguityScenarios, s => s.Id.Contains("clarify-destructive", StringComparison.OrdinalIgnoreCase));

        Assert.All(ambiguityScenarios, scenario =>
        {
            Assert.Contains("mcp-tool-use", scenario.Scoring!.Scorers);
            Assert.True(scenario.Input.ContainsKey("fake_mcp"));
            Assert.True(scenario.Input.ContainsKey("scripted_tool_calls"));
        });
    }

    [Fact]
    public async Task DenMcpAmbiguityGenerator_CanEmitHintedToolDescriptionVariant()
    {
        var repoRoot = FindRepoRoot();
        var tempDir = Path.Combine(Path.GetTempPath(), "goblinbench-den-mcp-ambiguity-hinted-" + Guid.NewGuid().ToString("N"));
        var outputDir = Path.Combine(tempDir, "suites", "den-mcp-ambiguity-hinted");

        var result = await RunPythonAsync(repoRoot,
            "scripts/generate-den-mcp-ambiguity-suite.py",
            "--variant", "hinted",
            "--output-dir", outputDir);

        Assert.Equal(0, result.ExitCode);

        var scenarios = await ScenarioDiscovery.DiscoverAsync(Path.Combine(tempDir, "suites"));
        var hinted = scenarios.Where(s => s.Suite == "den-mcp-ambiguity-hinted").ToList();
        Assert.Equal(6, hinted.Count);
        Assert.Contains(hinted, s => s.Id == "den-mcp-ambiguity-hinted.den-mcp-doc-system-planner");

        var scenarioPath = Path.Combine(outputDir, "den-mcp-doc-system-planner.json");
        var json = await File.ReadAllTextAsync(scenarioPath);
        Assert.Contains("TOOL HINT", json);
        Assert.Contains("persona phrases such as planner", json);
        Assert.Contains("tool_description_variant", json);

        using var doc = JsonDocument.Parse(json);
        var storeDocument = doc.RootElement
            .GetProperty("input")
            .GetProperty("fake_mcp")
            .GetProperty("tools")
            .EnumerateArray()
            .Single(t => t.GetProperty("name").GetString() == "mcp_den_store_document");
        Assert.Contains("den-mcp doc", storeDocument.GetProperty("description").GetString());
        var projectIdDescription = storeDocument
            .GetProperty("input_schema")
            .GetProperty("properties")
            .GetProperty("project_id")
            .GetProperty("description")
            .GetString();
        Assert.Contains("Do not use planner", projectIdDescription);
    }

    [Fact]
    public async Task GeneratedScenario_IsDiscoverableAndUsesMcpToolUseScorer()
    {
        var repoRoot = FindRepoRoot();
        var tempDir = Path.Combine(Path.GetTempPath(), "goblinbench-fake-den-mcp-discover-" + Guid.NewGuid().ToString("N"));
        var scenarioPath = Path.Combine(tempDir, "suites", "fake-den-mcp", "generated.json");

        var result = await RunPythonAsync(repoRoot,
            "scripts/generate-fake-den-mcp-catalog.py",
            "--input", "tests/fixtures/den-mcp-tools-list.sample.json",
            "--catalog-output", Path.Combine(tempDir, "catalog.json"),
            "--scenario-output", scenarioPath,
            "--scenario-id", "fake-den-mcp.generated-task-read",
            "--expected-tool", "mcp_den_get_task");

        Assert.Equal(0, result.ExitCode);

        var scenarios = await ScenarioDiscovery.DiscoverAsync(Path.Combine(tempDir, "suites"));
        var scenario = Assert.Single(scenarios);
        Assert.Equal("fake-den-mcp.generated-task-read", scenario.Id);
        Assert.Equal("fake-den-mcp", scenario.Suite);
        Assert.Contains("mcp-tool-use", scenario.Scoring!.Scorers);
        Assert.True(scenario.Input.ContainsKey("fake_mcp"));
        Assert.True(scenario.Input.ContainsKey("scripted_tool_calls"));
    }

    private static async Task<ProcessResult> RunPythonAsync(string workdir, string script, params string[] args)
    {
        var start = new ProcessStartInfo
        {
            FileName = "python3",
            WorkingDirectory = workdir,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.ArgumentList.Add(script);
        foreach (var arg in args)
            start.ArgumentList.Add(arg);

        using var process = Process.Start(start) ?? throw new InvalidOperationException("failed to start python3");
        var stdout = await process.StandardOutput.ReadToEndAsync();
        var stderr = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        return new ProcessResult(process.ExitCode, stdout, stderr);
    }

    private static string FindRepoRoot()
    {
        var dir = AppContext.BaseDirectory;
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir, "suites")) && Directory.Exists(Path.Combine(dir, "src")))
                return dir;
            dir = Path.GetDirectoryName(dir);
        }
        return Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../"));
    }

    private static Process StartPython(string workdir, string script)
    {
        var start = new ProcessStartInfo
        {
            FileName = "python3",
            WorkingDirectory = workdir,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.ArgumentList.Add(script);
        return Process.Start(start) ?? throw new InvalidOperationException("failed to start python3");
    }

    private static int GetFreeTcpPort()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }

    private static async Task WaitForServerAsync(int port)
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromMilliseconds(200) };
        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (DateTime.UtcNow < deadline)
        {
            try
            {
                using var content = new StringContent("{\"jsonrpc\":\"2.0\",\"id\":0,\"method\":\"ping\"}");
                _ = await client.PostAsync($"http://127.0.0.1:{port}/mcp", content);
                return;
            }
            catch
            {
                await Task.Delay(50);
            }
        }

        throw new TimeoutException("fake MCP server did not start");
    }

    private sealed record ProcessResult(int ExitCode, string StdOut, string StdErr);
}
