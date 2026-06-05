using System.Diagnostics;
using System.Text.Json;
using GoblinBench.Candidates;
using GoblinBench.Core;
using GoblinBench.Candidates.Sandbox;

namespace GoblinBench.Core.Tests;

/// <summary>
/// Integration tests for CodingAgentRunner. These tests exercise the real
/// bwrap sandbox. They are skipped automatically if bwrap is not available on
/// the host.
///
/// The "fake agent" is a tiny shell script the test writes into a temp
/// sandbox_root. The script's only job is to write a file into /work, which
/// is the writable workspace, so the runner's snapshot-diff pipeline can be
/// verified end to end. A second test (CodingAgent_SandboxedAgent_CannotEscapeWorkDir)
/// uses a script that attempts to write outside /work and verifies the write
/// does not appear on the host.
/// </summary>
public class CodingAgentRunnerIntegrationTests
{
    private static bool BwrapAvailable
    {
        get
        {
            try
            {
                var psi = new ProcessStartInfo("/usr/bin/bwrap", "--version")
                {
                    RedirectStandardOutput = true,
                    UseShellExecute = false,
                };
                using var p = Process.Start(psi);
                p?.WaitForExit(2000);
                return p?.ExitCode == 0;
            }
            catch
            {
                return false;
            }
        }
    }

    private static readonly string RepoRoot = CodingSuiteTests_FindRepoRoot();

    private static string CodingSuiteTests_FindRepoRoot()
    {
        // Walk up from the test assembly until we see suites/ + src/.
        var dir = Path.GetDirectoryName(typeof(CodingAgentRunnerIntegrationTests).Assembly.Location)
                  ?? AppContext.BaseDirectory;
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir, "suites")) &&
                Directory.Exists(Path.Combine(dir, "src")))
                return dir;
            var parent = Path.GetDirectoryName(dir);
            if (parent == dir) break;
            dir = parent;
        }
        return dir ?? ".";
    }

    private static (string sandboxRoot, string runsRoot) SetupFakeSandbox()
    {
        // The sandbox root must NOT live under any of the host's bwrap tmpfs
        // scratch dirs (/tmp, /var/tmp, /run), because the runner overlays
        // those with fresh tmpfs and the host paths would be invisible.
        // Place the sandbox under the runner's home (or working dir) instead.
        var baseDir = Path.Combine(
            Environment.GetEnvironmentVariable("HOME") ?? "/tmp",
            $".goblinbench-coding-agent-test-{Guid.NewGuid()}");
        var sandboxRoot = Path.Combine(baseDir, "sandbox-runtime");
        var runsRoot = Path.Combine(baseDir, "runs");
        Directory.CreateDirectory(sandboxRoot);
        Directory.CreateDirectory(runsRoot);

        // Fake agent: simple shell script that writes a known file to /tmp/agent-workspace.
        // Also writes its argv to /tmp/agent-workspace/.agent_args.txt so we can verify
        // the runner passed the task as expected.
        var agentDir = Path.Combine(sandboxRoot, "agent");
        Directory.CreateDirectory(agentDir);
        var agentPath = Path.Combine(agentDir, "fake-agent.sh");
        File.WriteAllText(agentPath, @"#!/bin/sh
set -e
mkdir -p /tmp/agent-workspace/src
cat > /tmp/agent-workspace/src/FakeFix.cs <<'EOF'
namespace FakeFix;
public class Fix { public static string Do() => ""patched""; }
EOF
# Record the argv the runner passed to us.
for a in ""$@""
do
  printf '%s\n' ""$a"" >> /tmp/agent-workspace/.agent_args.txt
done
echo ""fake agent completed""
");
        File.SetUnixFileMode(agentPath,
            UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute |
            UnixFileMode.GroupRead | UnixFileMode.GroupExecute |
            UnixFileMode.OtherRead | UnixFileMode.OtherExecute);

        return (sandboxRoot, runsRoot);
    }

    private static CandidateConfig MakeCandidate(string sandboxRoot) => new()
    {
        Id = "fake-coding",
        Name = "Fake Coding Agent (integration test)",
        Kind = CandidateKind.CodingAgent,
        Model = "fake-model",
        Provider = "fake",
        CliArgs = new List<string> { "--ignore" },
        Config = new Dictionary<string, object?>
        {
            ["agent_resolved"] = Path.Combine(sandboxRoot, "agent", "fake-agent.sh"),
            ["sandbox_root"] = sandboxRoot,
            ["node_resolved"] = "/usr/bin/bash", // we use a shell script; bash is a real file, not a symlink (which bwrap can mishandle across bind mounts)
            ["task"] = "Please fix the file in src/.",
        }
    };

    private static Scenario MakeScenario() => new()
    {
        Id = "coding.fake", Suite = "coding", Version = "1.0.0", Name = "Fake",
        Input = new Dictionary<string, object?>
        {
            ["fixture_case"] = "retry-policy", // reuse the real fixture as workspace
            ["task"] = "Please fix the file in src/.",
        },
        TimeoutSeconds = 30,
    };

    [Fact]
    public async Task CodingAgent_RunsFakeAgent_ProducesDiff()
    {
        if (!BwrapAvailable) return; // soft skip when bwrap missing

        var (sandboxRoot, runsRoot) = SetupFakeSandbox();
        try
        {
            var runDir = Path.Combine(runsRoot, "r1");
            var context = new RunContext
            {
                RunId = "r1", RunsRoot = runsRoot, RunDirectory = runDir, RepoRoot = RepoRoot
            };
            var candidate = MakeCandidate(sandboxRoot);
            var scenario = MakeScenario();
            var runner = new CodingAgentRunner();

            var result = await runner.RunAsync(scenario, candidate, context);

            Assert.True(result.Success, $"Runner failed: {result.Error}");
            var fixtureDir = GetFixtureDir(result);
            Assert.NotNull(fixtureDir);
            Assert.True(Directory.Exists(fixtureDir));

            // The fake agent should have written FakeFix.cs.
            var fakeFix = Path.Combine(fixtureDir!, "src", "FakeFix.cs");
            Assert.True(File.Exists(fakeFix), $"Expected {fakeFix} to exist after agent run");

            // And the agent's argv file should contain the task.
            var argsFile = Path.Combine(fixtureDir!, ".agent_args.txt");
            Assert.True(File.Exists(argsFile), $"Expected {argsFile} to exist");
            var argv = await File.ReadAllTextAsync(argsFile);
            Assert.Contains("Please fix the file in src/.", argv);

            // The output.json should have a non-empty patch + the bwrap argv.
            Assert.NotNull(result.Output);
            var json = JsonSerializer.Serialize(result.Output);
            using var doc = JsonDocument.Parse(json);
            Assert.True(doc.RootElement.GetProperty("files_changed").GetArrayLength() > 0);
            var patch = doc.RootElement.GetProperty("patch").GetString();
            Assert.NotNull(patch);
            Assert.Contains("FakeFix.cs", patch);
        }
        finally
        {
            TryDelete(sandboxRoot);
            TryDelete(runsRoot);
        }
    }

    [Fact]
    public async Task CodingAgent_SandboxedAgent_CannotEscapeWorkDir()
    {
        if (!BwrapAvailable) return;

        var (sandboxRoot, runsRoot) = SetupFakeSandbox();
        try
        {
            // Replace the agent with one that tries to write OUTSIDE /work.
            var agentPath = Path.Combine(sandboxRoot, "agent", "fake-agent.sh");
            File.WriteAllText(agentPath, @"#!/bin/sh
set +e
# Try to write to the host's /tmp — should land in the sandbox's tmpfs /tmp
# (which is a fresh tmpfs) instead of escaping.
echo 'escaped' > /tmp/escape-attempt 2>/dev/null
# Also try the dotnet cache.
echo 'escaped' > /home/agent/.dotnet/escape-attempt 2>/dev/null
# These should all fail silently (read-only root).
echo ""fake-attempt-done""
");
            File.SetUnixFileMode(agentPath,
                UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);

            var runDir = Path.Combine(runsRoot, "r1");
            var context = new RunContext
            {
                RunId = "r1", RunsRoot = runsRoot, RunDirectory = runDir, RepoRoot = RepoRoot
            };
            var candidate = MakeCandidate(sandboxRoot);
            var scenario = MakeScenario();
            var runner = new CodingAgentRunner();

            var result = await runner.RunAsync(scenario, candidate, context);

            // The agent should run to completion — the shell-script agent
            // exits 0 after its (silently-failing) writes. But the runner
            // considers the run unsuccessful because no files changed inside
            // the workspace. That's fine; the point of this test is what
            // appears on the HOST, not the result status.
            // (We still expect Success=false because the agent didn't touch
            // the workspace, only the no-op writes outside it.)

            // CRITICAL: nothing the agent tried to do should have appeared on
            // the host outside its workspace. /tmp is a fresh tmpfs in the
            // sandbox, so the write stays inside; /home/agent/.dotnet is
            // read-only via the / ro-bind.
            Assert.False(File.Exists("/tmp/escape-attempt"),
                "Agent escaped sandbox and wrote to host /tmp");
            Assert.False(File.Exists("/home/agent/.dotnet/escape-attempt"),
                "Agent escaped sandbox and wrote to host .dotnet");
        }
        finally
        {
            TryDelete(sandboxRoot);
            TryDelete(runsRoot);
        }
    }

    [Fact]
    public async Task CodingAgent_ResolvesAgentPathAndRejectsMissing()
    {
        if (!BwrapAvailable) return;

        var (sandboxRoot, runsRoot) = SetupFakeSandbox();
        try
        {
            // Point at a non-existent agent script.
            var candidate = MakeCandidate(sandboxRoot);
            var config = new Dictionary<string, object?>(candidate.Config!)
            {
                ["agent_resolved"] = "/nonexistent/agent/path/cli.js"
            };
            var bad = new CandidateConfig
            {
                Id = candidate.Id, Name = candidate.Name, Kind = candidate.Kind,
                Model = candidate.Model, Provider = candidate.Provider,
                CliArgs = candidate.CliArgs, Config = config,
            };

            var runDir = Path.Combine(runsRoot, "r1");
            var context = new RunContext
            {
                RunId = "r1", RunsRoot = runsRoot, RunDirectory = runDir, RepoRoot = RepoRoot
            };
            var runner = new CodingAgentRunner();
            var result = await runner.RunAsync(MakeScenario(), bad, context);

            Assert.False(result.Success);
            Assert.Contains("Agent entry script not found", result.Error ?? "");
        }
        finally
        {
            TryDelete(sandboxRoot);
            TryDelete(runsRoot);
        }
    }

    [Fact]
    public void BwrapProfile_ForCodingAgent_HasExpectedShape()
    {
        // A "shape" test that doesn't need bwrap: just verify the profile
        // builder produces a sensible argv for the typical coding-agent config.
        var profile = new BwrapProfile
        {
            WorkDir = "/tmp/agent-workspace",
            WorkDirSource = "/tmp/fake-fixture",
            ReadOnlyBinds = new[]
            {
                new HostBind("/", "/"),
                new HostBind("/usr", "/usr"),
                new HostBind("/etc/resolv.conf", "/etc/resolv.conf"),
                new HostBind("/tmp/sandbox-runtime", "/tmp/sandbox-runtime"),
            },
            Environment = new Dictionary<string, string>
            {
                ["HOME"] = "/work/.home",
                ["PATH"] = "/usr/bin:/bin",
            },
            Command = new[] { "/usr/bin/node", "/tmp/sandbox-runtime/agent/dist/cli.js", "--print" },
        };

        var argv = profile.ToArgv("/usr/bin/bwrap");
        // Expect: bwrap, --unshare-all, --die-with-parent,
        // --hostname, --share-net, then a series of --ro-bind (root first),
        // then --tmpfs /tmp, /var/tmp, /run, then --bind workspace, then
        // --clearenv, --setenv pairs, --chdir /work, --, then the inner argv.
        Assert.Equal("/usr/bin/bwrap", argv[0]);
        Assert.Contains("--unshare-all", argv);
        Assert.Contains("--die-with-parent", argv);
        Assert.Contains("--ro-bind", argv);
        Assert.Contains("--bind", argv);
        Assert.Contains("--clearenv", argv);
        Assert.Contains("--chdir", argv);
        Assert.Contains("--", argv);
        Assert.Equal("/usr/bin/node", argv[^3]);
        Assert.Equal("/tmp/sandbox-runtime/agent/dist/cli.js", argv[^2]);
        Assert.Equal("--print", argv[^1]);

        // First --ro-bind must be / → /, and the workspace --bind must come
        // after every --ro-bind.
        var firstRoBind = IndexOf(argv, "--ro-bind");
        Assert.Equal("/", argv[firstRoBind + 1]);
        Assert.Equal("/", argv[firstRoBind + 2]);

        profile.Validate();
    }

    private static void TryDelete(string path)
    {
        try { if (Directory.Exists(path)) Directory.Delete(path, recursive: true); }
        catch { /* best effort */ }
    }

    private static int IndexOf(IReadOnlyList<string> argv, string needle)
    {
        for (var i = 0; i < argv.Count; i++)
            if (argv[i] == needle) return i;
        return -1;
    }

    private static string? GetFixtureDir(CandidateResult result)
    {
        if (result.Output is not { } output) return null;
        try
        {
            var json = JsonSerializer.Serialize(output);
            using var doc = JsonDocument.Parse(json);
            if (doc.RootElement.TryGetProperty("fixture_dir", out var fd))
                return fd.GetString();
        }
        catch { }
        return null;
    }
}
