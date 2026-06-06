using System.Text;

namespace GoblinBench.Candidates.Sandbox;

/// <summary>
/// Builds a bubblewrap (bwrap) argv for a coding-agent subprocess.
///
/// Design intent: helpful friction against dumb mistakes, not hard isolation.
/// The agent is untrusted only in the sense that we want defaults to fail safe
/// when a confused model does something unexpected (e.g. <c>rm -rf</c> the wrong
/// directory). We are NOT defending against a malicious agent or network
/// exfiltration — the network namespace is shared with the host on purpose so
/// that <c>dotnet restore</c> still works.
///
/// Properties the builder enforces:
/// <list type="bullet">
/// <item>The host root <c>/</c> is bound read-only. The agent can read any
/// file on the system but cannot damage any existing file.</item>
/// <item>Exactly one writable mount is allowed: the per-scenario workspace
/// (bound after the read-only binds so it shadows the read-only root).</item>
/// <item>All other bind mounts are read-only.</item>
/// <item>Env is cleared (<c>--clearenv</c>) and only declared vars are set.</item>
/// <item>Working directory is set explicitly inside the sandbox.</item>
/// <item><c>--die-with-parent</c> cleans up if the harness dies.</item>
/// </list>
///
/// Historical note: an earlier design started with <c>--tmpfs /</c> and
/// enumerated every needed read-only path. That broke on distros where
/// bwrap's execvp couldn't find inner commands through specific path binds
/// (e.g. <c>/lib64/ld-linux-x86-64.so.2</c> via <c>/lib64</c> symlink).
/// Binding the whole host read-only is simpler and strictly stronger
/// protection against destructive accidents.
/// </summary>
public sealed record BwrapProfile
{
    /// <summary>
    /// Path inside the sandbox used as the agent's working dir and writable workspace.
    /// Defaults to <c>/tmp/agent-workspace</c> — chosen because the parent <c>/tmp</c> is
    /// always a fresh tmpfs (see <see cref="TmpfsScratchDirs"/>), which is required
    /// for bwrap to create the mount point when the host root is read-only.
    /// </summary>
    public required string WorkDir { get; init; } = "/tmp/agent-workspace";

    /// <summary>Absolute path on the host to bind to <see cref="WorkDir"/> as the writable workspace.</summary>
    public required string WorkDirSource { get; init; }

    /// <summary>Inner command (executable + args) to run inside the sandbox.</summary>
    public required IReadOnlyList<string> Command { get; init; }

    /// <summary>Read-only bind mounts the agent needs (host path, sandbox path).</summary>
    public IReadOnlyList<HostBind> ReadOnlyBinds { get; init; } = Array.Empty<HostBind>();

    /// <summary>
    /// Environment variables explicitly set inside the sandbox. <c>--clearenv</c>
    /// is always applied first, so anything not listed here is dropped.
    /// </summary>
    public IReadOnlyDictionary<string, string> Environment { get; init; } =
        new Dictionary<string, string>(StringComparer.Ordinal);

    /// <summary>If true, share the network namespace with the host. Default: true (NuGet needs it).</summary>
    public bool ShareNetwork { get; init; } = true;

    /// <summary>Override hostname inside the sandbox. Default: "goblinbench-sandbox".</summary>
    public string Hostname { get; init; } = "goblinbench-sandbox";

    /// <summary>
    /// Build the full argv. The result is suitable for passing to <c>ProcessStartInfo</c>
    /// (as <c>FileName = "bwrap"</c> and <c>ArgumentList = ...</c>) or for storing
    /// in trace artifacts.
    /// </summary>
    public IReadOnlyList<string> ToArgv(string bwrapPath = "bwrap")
    {
        var argv = new List<string>
        {
            bwrapPath,
            "--unshare-all",
            "--die-with-parent",
            $"--hostname", Hostname,
        };

        if (ShareNetwork)
            argv.Add("--share-net");

        // Strategy: bind the whole host read-only first (caller adds the
        // --ro-bind / / as the first ReadOnlyBind), then bind the workspace
        // writable on top. This way the inner command can find its libraries
        // and tooling through /, but the only writable mount is WorkDir.
        foreach (var bind in ReadOnlyBinds)
        {
            if (bind.Mode == BindMode.ReadOnly)
                argv.AddRange(new[] { "--ro-bind", bind.Source, bind.Destination });
            else
                throw new InvalidOperationException(
                    $"BwrapProfile only allows read-only binds except for WorkDir; got writable bind " +
                    $"from {bind.Source} to {bind.Destination}.");
        }

        // Tmpfs scratch areas — agent can write here without polluting host.
        // /tmp covers generic scratch, /var/tmp is the FHS-canonical scratch,
        // /run is for runtime state (some agents want to put sockets here).
        foreach (var scratch in TmpfsScratchDirs)
            argv.AddRange(new[] { "--tmpfs", scratch });

        // Provide a fresh /dev so common subprocess plumbing works inside the
        // user namespace. With only --ro-bind / /, device nodes such as
        // /dev/null are visible but cannot be opened, which breaks shell
        // redirects and Node's spawn(..., { stdio: "ignore" }). Coding agents
        // frequently spawn test/build commands that rely on /dev/null.
        argv.AddRange(new[] { "--dev", "/dev" });

        // Writable workspace — must come after read-only binds, tmpfs, and /dev
        // overlays so the bind shadows whatever's under WorkDir in the
        // read-only root.
        argv.AddRange(new[] { "--bind", WorkDirSource, WorkDir });

        // Env handling: clear first, then explicitly set declared vars.
        argv.Add("--clearenv");
        foreach (var (k, v) in Environment)
            argv.AddRange(new[] { "--setenv", k, v });

        argv.AddRange(new[] { "--chdir", WorkDir, "--" });
        argv.AddRange(Command);
        return argv;
    }

    /// <summary>
    /// Directories that should be a fresh tmpfs inside the sandbox, so the
    /// agent can write there without polluting the host. Override by
    /// instantiating with a custom value via the <see cref="TmpfsScratchDirs"/>
    /// property.
    /// </summary>
    public IReadOnlyList<string> TmpfsScratchDirs { get; init; } = new[]
    {
        "/tmp",
        "/var/tmp",
        "/run",
    };

    /// <summary>
    /// Build a single shell-escaped command line for logging/trace purposes.
    /// Does NOT parse — only produces a human-readable view.
    /// </summary>
    public string ToCommandLine(string bwrapPath = "bwrap")
    {
        var sb = new StringBuilder();
        foreach (var a in ToArgv(bwrapPath))
        {
            if (sb.Length > 0) sb.Append(' ');
            if (a.IndexOfAny(new[] { ' ', '\t', '"', '\\' }) < 0) { sb.Append(a); continue; }
            sb.Append('"').Append(a.Replace("\\", "\\\\").Replace("\"", "\\\"")).Append('"');
        }
        return sb.ToString();
    }

    /// <summary>
    /// Catch obvious foot-guns. Throws <see cref="InvalidOperationException"/>
    /// with a descriptive message; otherwise no-op.
    /// </summary>
    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(WorkDir))
            throw new InvalidOperationException("WorkDir must be set.");
        if (!WorkDir.StartsWith("/"))
            throw new InvalidOperationException($"WorkDir must be an absolute path inside the sandbox; got '{WorkDir}'.");
        if (string.IsNullOrWhiteSpace(WorkDirSource))
            throw new InvalidOperationException("WorkDirSource must be an absolute host path.");
        if (!Path.IsPathRooted(WorkDirSource))
            throw new InvalidOperationException($"WorkDirSource must be absolute; got '{WorkDirSource}'.");
        if (Command.Count == 0)
            throw new InvalidOperationException("Command must contain at least the executable.");

        foreach (var bind in ReadOnlyBinds)
        {
            if (!Path.IsPathRooted(bind.Source))
                throw new InvalidOperationException($"Read-only bind source must be absolute: {bind.Source}");
            if (!bind.Destination.StartsWith("/"))
                throw new InvalidOperationException(
                    $"Read-only bind destination must be absolute inside sandbox: {bind.Destination}");
            if (bind.Destination == WorkDir || bind.Destination.StartsWith(WorkDir + "/"))
                throw new InvalidOperationException(
                    $"Read-only bind {bind.Destination} collides with the writable WorkDir {WorkDir}.");
            // Binding over / is allowed when it's a read-only bind (e.g. the
            // common "host root read-only" pattern). Only the writable
            // workspace is forbidden from being /.
            if (bind.Destination == "/" && bind.Mode == BindMode.ReadOnly)
                continue;
        }

        if (WorkDir == "/")
            throw new InvalidOperationException("WorkDir cannot be /; pick a subdirectory like /tmp/agent-workspace.");

        // The parent of WorkDir must be writable. We provide that by listing
        // /tmp (and /var/tmp, /run) as tmpfs overlays in TmpfsScratchDirs. If
        // a caller picks a custom WorkDir under a non-tmpfs path, refuse.
        if (!TmpfsScratchDirs.Any(d => WorkDir == d || WorkDir.StartsWith(d + "/")))
            throw new InvalidOperationException(
                $"WorkDir '{WorkDir}' must live under one of the tmpfs scratch dirs: " +
                $"[{string.Join(", ", TmpfsScratchDirs)}]. Pick a path like /tmp/agent-workspace.");

        // We expect the inner command to be absolute. Relative paths inside the
        // sandbox can refer to a different FS — make this explicit.
        if (!Path.IsPathRooted(Command[0]))
            throw new InvalidOperationException(
                $"Inner command executable must be an absolute path: '{Command[0]}'.");
    }
}

/// <summary>Describes a host→sandbox bind mount. <see cref="Mode"/> is always ReadOnly except for WorkDir.</summary>
public sealed record HostBind(string Source, string Destination, BindMode Mode = BindMode.ReadOnly);

public enum BindMode
{
    ReadOnly,
}
