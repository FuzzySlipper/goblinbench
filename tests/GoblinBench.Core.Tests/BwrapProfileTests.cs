using GoblinBench.Candidates.Sandbox;

namespace GoblinBench.Core.Tests;

/// <summary>
/// Unit tests for the BwrapProfile builder. These run without invoking bwrap
/// itself — they verify argv construction, env handling, and that obvious
/// foot-guns (binding /, mounting outside /, relative inner command) are caught.
/// </summary>
public class BwrapProfileTests
{
    private static BwrapProfile Sample() => new()
    {
        WorkDir = "/tmp/agent-workspace",
        WorkDirSource = "/tmp/goblinbench/test-fixture",
        Command = new[] { "/usr/bin/node", "/agent/pi", "--print", "--no-session", "do the thing" },
        ReadOnlyBinds = new[]
        {
            new HostBind("/", "/"),
            new HostBind("/usr", "/usr"),
            new HostBind("/etc/resolv.conf", "/etc/resolv.conf"),
            new HostBind("/home/dev/goblinbench/.sandbox-runtime",
                         "/home/dev/goblinbench/.sandbox-runtime"),
        },
        Environment = new Dictionary<string, string>
        {
            ["HOME"] = "/tmp",
            ["PATH"] = "/usr/bin:/bin",
        },
    };

    [Fact]
    public void ToArgv_BeginsWithUnshareAllAndDiesWithParent()
    {
        var argv = Sample().ToArgv("bwrap");
        Assert.Equal("bwrap", argv[0]);
        Assert.Contains("--unshare-all", argv);
        Assert.Contains("--die-with-parent", argv);
    }

    [Fact]
    public void ToArgv_DefaultSharesNetwork_ForNuget()
    {
        var argv = Sample().ToArgv("bwrap");
        Assert.Contains("--share-net", argv);
    }

    [Fact]
    public void ToArgv_NetworkCanBeDisabled()
    {
        var profile = Sample();
        var noNet = new BwrapProfile
        {
            WorkDir = profile.WorkDir,
            WorkDirSource = profile.WorkDirSource,
            Command = profile.Command,
            ReadOnlyBinds = profile.ReadOnlyBinds,
            Environment = profile.Environment,
            ShareNetwork = false,
        };
        var argv = noNet.ToArgv("bwrap");
        Assert.DoesNotContain("--share-net", argv);
    }

    [Fact]
    public void ToArgv_RootIsReadOnlyBindBeforeWorkspace()
    {
        var argv = Sample().ToArgv("bwrap");
        // The first --ro-bind must target /, and the workspace --bind must
        // come after all the --ro-bind entries.
        var firstRoBind = IndexOf(argv, "--ro-bind");
        Assert.True(firstRoBind >= 0, "Expected at least one --ro-bind");
        Assert.Equal("/", argv[firstRoBind + 1]);
        Assert.Equal("/", argv[firstRoBind + 2]);

        var workBind = IndexOf(argv, "--bind");
        Assert.True(workBind > firstRoBind, "Workspace --bind must come after --ro-bind /");
        Assert.Equal("/tmp/agent-workspace", argv[workBind + 2]);
    }

    [Fact]
    public void ToArgv_WorkDirIsTheOnlyWritableBind()
    {
        var argv = Sample().ToArgv("bwrap");
        var writableBinds = 0;
        for (var i = 0; i < argv.Count; i++)
        {
            if (argv[i] == "--bind")
            {
                writableBinds++;
                // First --bind must be workspace, mapped to /tmp/agent-workspace.
                var dest = argv[i + 2];
                Assert.Equal("/tmp/agent-workspace", dest);
            }
            else if (argv[i] == "--ro-bind")
            {
                // None of the ro-binds should target the workspace or its children.
                var dest = argv[i + 2];
                Assert.False(dest == "/tmp/agent-workspace" || dest.StartsWith("/tmp/agent-workspace/"),
                    $"Read-only bind collides with writable workspace: {dest}");
            }
        }
        Assert.Equal(1, writableBinds);
    }

    [Fact]
    public void ToArgv_ClearsEnvBeforeSettingDeclared()
    {
        var argv = Sample().ToArgv("bwrap");
        var clearIdx = IndexOf(argv, "--clearenv");
        var homeIdx = IndexOf(argv, "--setenv");
        Assert.True(clearIdx >= 0);
        Assert.True(homeIdx > clearIdx);
        // HOME=/tmp must be present.
        Assert.Equal("HOME", argv[homeIdx + 1]);
        Assert.Equal("/tmp", argv[homeIdx + 2]);
    }

    [Fact]
    public void ToArgv_InnerCommandAppearsAfterSandboxSetup()
    {
        var argv = Sample().ToArgv("bwrap");
        var sepIdx = Array.IndexOf(argv.ToArray(), "--");
        Assert.True(sepIdx >= 0);
        Assert.Equal("/usr/bin/node", argv[sepIdx + 1]);
        Assert.Equal("/agent/pi", argv[sepIdx + 2]);
    }

    [Fact]
    public void ToArgv_ChdirIsWorkDir()
    {
        var argv = Sample().ToArgv("bwrap");
        var chdirIdx = IndexOf(argv, "--chdir");
        Assert.True(chdirIdx >= 0);
        Assert.Equal("/tmp/agent-workspace", argv[chdirIdx + 1]);
    }

    [Fact]
    public void ToCommandLine_IsRoundTrippableForLog()
    {
        var profile = Sample();
        var line = profile.ToCommandLine("/usr/bin/bwrap");
        Assert.StartsWith("/usr/bin/bwrap ", line);
        Assert.Contains("--unshare-all", line);
        Assert.Contains("--die-with-parent", line);
        Assert.Contains("do the thing", line);
    }

    [Fact]
    public void Validate_RejectsRelativeWorkDir()
    {
        var bad = Sample() with { WorkDir = "work" };
        Assert.Throws<InvalidOperationException>(() => bad.Validate());
    }

    [Fact]
    public void Validate_RejectsRelativeWorkDirSource()
    {
        var bad = Sample() with { WorkDirSource = "tmp/x" };
        Assert.Throws<InvalidOperationException>(() => bad.Validate());
    }

    [Fact]
    public void Validate_RejectsRelativeInnerCommand()
    {
        var bad = Sample() with
        {
            Command = new[] { "pi", "--print" }
        };
        Assert.Throws<InvalidOperationException>(() => bad.Validate());
    }

    [Fact]
    public void Validate_RejectsRoBindOverlappingWorkDir()
    {
        var bad = Sample() with
        {
            ReadOnlyBinds = new[] { new HostBind("/etc", "/tmp/agent-workspace/etc") }
        };
        Assert.Throws<InvalidOperationException>(() => bad.Validate());
    }

    [Fact]
    public void Validate_RejectsWorkdirAsRoot()
    {
        var bad = Sample() with { WorkDir = "/", WorkDirSource = "/some/host/path" };
        Assert.Throws<InvalidOperationException>(() => bad.Validate());
    }

    [Fact]
    public void Validate_RejectsWorkdirOutsideTmpfsScratch()
    {
        var bad = Sample() with
        {
            WorkDir = "/home/agent-workspace",
            WorkDirSource = "/some/host/path"
        };
        var ex = Assert.Throws<InvalidOperationException>(() => bad.Validate());
        Assert.Contains("tmpfs scratch", ex.Message);
    }

    [Fact]
    public void Validate_AllowsReadOnlyBindOverRoot()
    {
        // The "host root read-only" pattern is the recommended way to let
        // bwrap find the inner command's libraries without enumerating every
        // possible path. It must be accepted.
        var ok = Sample() with
        {
            ReadOnlyBinds = new[] { new HostBind("/", "/") }
        };
        ok.Validate();
    }

    [Fact]
    public void Validate_RejectsRelativeRoBindDestination()
    {
        var bad = Sample() with
        {
            ReadOnlyBinds = new[] { new HostBind("/usr", "usr") }
        };
        Assert.Throws<InvalidOperationException>(() => bad.Validate());
    }

    [Fact]
    public void Validate_RejectsEmptyCommand()
    {
        var bad = Sample() with { Command = Array.Empty<string>() };
        Assert.Throws<InvalidOperationException>(() => bad.Validate());
    }

    [Fact]
    public void ToArgv_HonorsCustomHostname()
    {
        var profile = Sample();
        var custom = new BwrapProfile
        {
            WorkDir = profile.WorkDir,
            WorkDirSource = profile.WorkDirSource,
            Command = profile.Command,
            ReadOnlyBinds = profile.ReadOnlyBinds,
            Environment = profile.Environment,
            Hostname = "gandalf",
        };
        var argv = custom.ToArgv("bwrap");
        var idx = IndexOf(argv, "--hostname");
        Assert.True(idx >= 0);
        Assert.Equal("gandalf", argv[idx + 1]);
    }

    [Fact]
    public void ToArgv_HonorsCustomBwrapPath()
    {
        var argv = Sample().ToArgv("/opt/bwrap/bwrap");
        Assert.Equal("/opt/bwrap/bwrap", argv[0]);
    }

    private static int IndexOf(IReadOnlyList<string> argv, string needle)
    {
        for (var i = 0; i < argv.Count; i++)
            if (argv[i] == needle) return i;
        return -1;
    }
}
