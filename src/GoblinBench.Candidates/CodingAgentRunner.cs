using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using GoblinBench.Candidates.Sandbox;
using GoblinBench.Core;

namespace GoblinBench.Candidates;

/// <summary>
/// Candidate runner that launches a coding agent CLI (pi, codex, claude) inside
/// a bubblewrap sandbox, against a copied fixture workspace, captures the
/// resulting file edits as a unified diff, and hands them to <c>CodingTestScorer</c>.
///
/// The agent is given exactly one writable mount: the per-candidate fixture
/// directory, bound to <c>/work</c> inside the sandbox. Everything else
/// (toolchain, agent tree, dotnet SDK) is read-only. This is "helpful friction
/// against dumb mistakes" — a confused model under context pressure cannot
/// accidentally rm -rf the host filesystem, the agent's own install, the dotnet
/// cache, or any other fixture. We are NOT isolating network or defending
/// against a malicious actor.
///
/// Required candidate config (kind = "coding-agent"):
/// <list type="bullet">
/// <item><c>cli_args</c>: arguments passed to the agent's entry script.</item>
/// <item><c>config.agent_resolved</c>: absolute path to the agent's actual entry script.</item>
/// <item><c>config.sandbox_root</c>: absolute host path to the agent's installed node_modules (e.g. <c>.sandbox-runtime/</c>).</item>
/// <item><c>config.node_resolved</c> (optional): absolute path to <c>node</c>. Auto-resolved from PATH otherwise.</item>
/// <item><c>config.task</c>: prompt text for the agent (usually the scenario's input.task).</item>
/// <item><c>config.api_key_env</c> (optional): env var name whose value is passed to the agent.</item>
/// </list>
///
/// Output:
/// <list type="bullet">
/// <item><c>Output["fixture_dir"]</c>: path the agent edited (used by CodingTestScorer).</item>
/// <item><c>Output["patch"]</c>: unified diff of the agent's edits.</item>
/// <item><c>Output["files_changed"]</c>: list of relative file paths touched.</item>
/// <item><c>Output["bwrap_argv"]</c>: exact bwrap argv used (for trace/debug).</item>
/// <item><c>RawResponse</c>: agent stdout (model text).</item>
/// </list>
/// </summary>
public sealed class CodingAgentRunner : ICandidateRunner
{
    public string Name => "coding-agent";

    private const int MaxInlineRawResponseChars = 32_768;

    private static readonly HashSet<string> SkipDirs =
        new(StringComparer.OrdinalIgnoreCase)
        {
            "obj", "bin", ".git", ".vs",
            // Runner-owned scratch directories created inside the writable
            // workspace by the sandbox environment. pi's jiti extension loader
            // writes transpiled modules to cwd/.tmp/jiti; dotnet/node caches can
            // similarly appear under the HOME/XDG paths we intentionally point
            // at the workspace. These are execution artifacts, not candidate
            // edits, so keep them out of agent.patch/files_changed.
            ".tmp", ".cache", ".home", ".dotnet-home", ".local",
            "__pycache__", ".pytest_cache", ".venv", "node_modules", "coverage", "dist", "target", "uv.lock"
        };

    public bool CanHandle(CandidateConfig candidate) =>
        candidate.Kind == CandidateKind.CodingAgent;

    public async Task<CandidateResult> RunAsync(
        Scenario scenario,
        CandidateConfig candidate,
        RunContext context,
        CancellationToken ct = default)
    {
        var startedAt = DateTime.UtcNow;
        var stopwatch = Stopwatch.StartNew();
        var trace = new List<TraceEvent>();

        CandidateResult BuildFailure(string error) => new()
        {
            CandidateId = candidate.Id,
            CandidateName = candidate.Name,
            CandidateKind = candidate.Kind,
            Success = false,
            Error = error,
            DurationMs = stopwatch.ElapsedMilliseconds,
            Trace = trace,
            ArtifactDirectory = context.GetCandidateArtifactsDirectory(candidate.Id),
        };

        try
        {
            // 1. Resolve and verify the agent binary and host-side dependencies.
            var cfg = SandboxConfig.From(candidate);
            // The task prompt can come from either the candidate config or the
            // scenario input; prefer the scenario's natural source.
            var scenarioTask = GetStringFromInput(scenario, "task");
            if (string.IsNullOrEmpty(scenarioTask) && string.IsNullOrEmpty(cfg.Task))
                return BuildFailure(
                    "No task prompt: provide scenario.input.task or candidate.config.task.");
            var resolved = ResolveAgentPaths(cfg, trace);

            // 2. Locate fixture source and copy to per-candidate workspace.
            var repoRoot = context.RepoRoot ?? FindRepoRoot(context.RunsRoot);
            var fixtureCase = GetStringFromInput(scenario, "fixture_case");
            if (string.IsNullOrEmpty(fixtureCase))
                return BuildFailure("Scenario input missing 'fixture_case'.");

            var fixtureSource = Path.Combine(repoRoot, "fixtures", "coding", fixtureCase);
            if (!Directory.Exists(fixtureSource))
                return BuildFailure($"Fixture directory not found: {fixtureSource}");

            var fixtureDest = Path.Combine(
                context.GetCandidateDirectory(candidate.Id), "fixture");
            CopyDirectory(fixtureSource, fixtureDest);
            EnsureSandboxScratchDirs(fixtureDest);
            EnsureFixtureRuntime(fixtureDest, resolved.SandboxRoot, trace);

            trace.Add(new TraceEvent
            {
                Timestamp = DateTime.UtcNow, Event = "coding.fixture.copied",
                Data = new { source = fixtureSource, destination = fixtureDest }
            });

            // 3. Snapshot the fixture before the agent runs.
            var snapshotBefore = SnapshotDirectory(fixtureDest);
            trace.Add(new TraceEvent
            {
                Timestamp = DateTime.UtcNow, Event = "coding.snapshot.before",
                Data = new { file_count = snapshotBefore.Count }
            });

            // 4. Build the bwrap profile.
            var effectiveTask = !string.IsNullOrEmpty(cfg.Task) ? cfg.Task : scenarioTask;
            var bwrap = BuildBwrapProfile(cfg, resolved, fixtureDest, effectiveTask, trace);
            bwrap.Validate();

            var bwrapArgv = bwrap.ToArgv(resolved.BwrapPath);
            var bwrapCommandLine = bwrap.ToCommandLine(resolved.BwrapPath);
            trace.Add(new TraceEvent
            {
                Timestamp = DateTime.UtcNow, Event = "coding.bwrap.starting",
                Data = new { argv = bwrapArgv, command_line = bwrapCommandLine }
            });

            // 5. Launch the agent inside the sandbox.
            var psi = new ProcessStartInfo
            {
                FileName = resolved.BwrapPath,
                WorkingDirectory = fixtureDest,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            // argv[0] is bwrap itself (we used it as FileName); append the rest.
            foreach (var a in bwrapArgv.Skip(1)) psi.ArgumentList.Add(a);

            using var process = new Process { StartInfo = psi };
            process.Start();

            // pi --mode json emits high-frequency JSONL message_update events.
            // Those events contain cumulative "partial" payloads, so reasoning-heavy
            // models can amplify a normal run into hundreds of MB of stdout.
            // Drain the pipe continuously, but do not retain those cumulative
            // update lines in memory/artifacts; final message/tool events remain.
            var stdoutTask = ReadFilteredStdoutAsync(process.StandardOutput);
            var stderrTask = ReadProcessStreamAsync(process.StandardError);

            using var timeoutCts = new CancellationTokenSource(
                TimeSpan.FromSeconds(scenario.TimeoutSeconds > 0 ? scenario.TimeoutSeconds : 300));
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(ct, timeoutCts.Token);
            try
            {
                await process.WaitForExitAsync(linked.Token);
            }
            catch (OperationCanceledException)
            {
                TryKill(process);
                throw;
            }

            stopwatch.Stop();
            var stdout = await stdoutTask;
            var stderr = await stderrTask;

            trace.Add(new TraceEvent
            {
                Timestamp = DateTime.UtcNow, Event = "coding.bwrap.exited",
                Data = new
                {
                    exit_code = process.ExitCode,
                    stdout_length = stdout.RawLength,
                    stdout_retained_length = stdout.Text.Length,
                    stdout_filtered_message_update_lines = stdout.FilteredMessageUpdateLines,
                    stdout_filtered_message_update_chars = stdout.FilteredMessageUpdateChars,
                    stderr_length = stderr.RawLength,
                    duration_ms = stopwatch.ElapsedMilliseconds
                }
            });

            // 6. Snapshot after, diff, write artifacts.
            var snapshotAfter = SnapshotDirectory(fixtureDest);
            var diff = ComputeUnifiedDiff(snapshotBefore, snapshotAfter, fixtureDest);
            var filesChanged = diff.FilesChanged;

            trace.Add(new TraceEvent
            {
                Timestamp = DateTime.UtcNow, Event = "coding.snapshot.after",
                Data = new
                {
                    file_count = snapshotAfter.Count,
                    files_changed = filesChanged.Count,
                    diff_lines = diff.UnifiedDiffText.Count(c => c == '\n')
                }
            });

            await WriteArtifactsAsync(
                candidate, context, fixtureDest, diff, stdout, stderr,
                bwrapCommandLine, ct);

            var success = process.ExitCode == 0;
            var producedChanges = filesChanged.Count > 0;
            string? error = (success, producedChanges) switch
            {
                (true, true) => null,
                (true, false) => "Agent exited 0 but produced no file changes.",
                (false, _) => $"Agent exited with code {process.ExitCode}: " +
                    (stderr.Text.Length > 0
                        ? stderr.Text[..Math.Min(stderr.Text.Length, 500)]
                        : "(no stderr)"),
            };

            return new CandidateResult
            {
                CandidateId = candidate.Id,
                CandidateName = candidate.Name,
                CandidateKind = candidate.Kind,
                ModelIdentity = new ModelIdentity
                {
                    Model = candidate.Model,
                    Provider = candidate.Provider ?? "coding-agent",
                    DisplayName = $"coding-agent:{candidate.Id}"
                },
                Success = success && producedChanges,
                Error = error,
                DurationMs = stopwatch.ElapsedMilliseconds,
                RawResponse = TruncateForInline(stdout.Text),
                Output = new Dictionary<string, object?>
                {
                    ["fixture_dir"] = fixtureDest,
                    ["fixture_case"] = fixtureCase,
                    ["patch"] = diff.UnifiedDiffText,
                    ["files_changed"] = filesChanged,
                    ["stdout_length"] = stdout.RawLength,
                    ["stdout_retained_length"] = stdout.Text.Length,
                    ["stdout_filtered_message_update_lines"] = stdout.FilteredMessageUpdateLines,
                    ["stdout_filtered_message_update_chars"] = stdout.FilteredMessageUpdateChars,
                    ["stderr_length"] = stderr.RawLength,
                    ["raw_response_truncated"] = stdout.Text.Length > MaxInlineRawResponseChars,
                    ["bwrap_argv"] = bwrapArgv,
                    ["bwrap_command_line"] = bwrapCommandLine,
                    ["agent_command"] = cfg.CliArgs,
                    ["agent_resolved_path"] = resolved.AgentEntryScript,
                    ["agent_resolved_sha256"] = resolved.AgentEntrySha256,
                },
                Trace = trace,
                ArtifactDirectory = context.GetCandidateArtifactsDirectory(candidate.Id)
            };
        }
        catch (OperationCanceledException)
        {
            return BuildFailure("Coding-agent run timed out or was cancelled.");
        }
        catch (Exception ex)
        {
            return BuildFailure($"CodingAgentRunner failed: {ex.Message}");
        }
    }

    // ── Path resolution + integrity check ─────────────────────────────────

    private static ResolvedAgentPaths ResolveAgentPaths(
        SandboxConfig cfg, List<TraceEvent> trace)
    {
        var bwrapPath = ResolveBwrapPath();
        var nodePath = ResolveNodePath(cfg.NodeResolved);

        if (!File.Exists(nodePath))
            throw new FileNotFoundException(
                $"Node binary not found at '{nodePath}'. Set config.node_resolved in the candidate.",
                nodePath);

        if (!File.Exists(cfg.AgentResolved))
            throw new FileNotFoundException(
                $"Agent entry script not found at '{cfg.AgentResolved}'. " +
                "Set config.agent_resolved to the absolute path inside .sandbox-runtime/node_modules/...",
                cfg.AgentResolved);

        if (!Directory.Exists(cfg.SandboxRoot))
            throw new DirectoryNotFoundException(
                $"Sandbox root not found at '{cfg.SandboxRoot}'. " +
                "Run 'npm install --ignore-scripts' under .sandbox-runtime/ first.");

        // Resolve symlinks so bwrap binds the real file, not a relative path
        // that won't exist once the namespace is unshared, AND so bwrap's execvp
        // can find the binary through the bind mount.
        var agentEntryReal = ResolveRealPath(cfg.AgentResolved);
        var nodeReal = ResolveRealPath(nodePath);
        var sandboxRootReal = Path.GetFullPath(cfg.SandboxRoot);
        var agentSha = Sha256OfFile(agentEntryReal);

        trace.Add(new TraceEvent
        {
            Timestamp = DateTime.UtcNow, Event = "coding.paths.resolved",
            Data = new
            {
                bwrap = bwrapPath,
                node = nodeReal,
                agent = agentEntryReal,
                agent_sha256 = agentSha,
                sandbox_root = sandboxRootReal,
            }
        });

        return new ResolvedAgentPaths(
            BwrapPath: bwrapPath,
            NodePath: nodeReal,
            AgentEntryScript: agentEntryReal,
            AgentEntrySha256: agentSha,
            SandboxRoot: sandboxRootReal);
    }

    private static string ResolveBwrapPath()
    {
        foreach (var c in new[] { "/usr/bin/bwrap", "/usr/local/bin/bwrap" })
            if (File.Exists(c)) return c;
        return "bwrap"; // PATH fallback
    }

    private static string ResolveNodePath(string? configured)
    {
        if (!string.IsNullOrEmpty(configured) && File.Exists(configured))
            return configured;
        var which = LocateOnPath("node");
        if (which != null) return which;
        foreach (var c in new[] { "/usr/bin/node", "/usr/local/bin/node" })
            if (File.Exists(c)) return c;
        return configured ?? "node";
    }

    /// <summary>
    /// Resolve a path to its realpath (following symlinks all the way) so that
    /// bwrap binds the actual file, not a symlink. bwrap's execvp on a symlinked
    /// inner command can fail with "No such file or directory" when the symlink
    /// target's directory is bound but the symlink itself isn't in the lookup
    /// path the kernel uses. Realpath is the safe path.
    /// </summary>
    private static string ResolveRealPath(string path)
    {
        try
        {
            // File.ResolveLinkTarget throws if path is not a link or doesn't exist;
            // we want a chained resolution regardless.
            var current = path;
            for (var i = 0; i < 32; i++) // 32 is the kernel symlink depth limit
            {
                var target = File.ResolveLinkTarget(current, returnFinalTarget: false);
                if (target == null) return current;
                current = target.FullName;
            }
            return current;
        }
        catch
        {
            return path; // fall back to the original if resolution fails
        }
    }

    private static string? LocateOnPath(string name)
    {
        var path = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrEmpty(path)) return null;
        foreach (var dir in path.Split(Path.PathSeparator))
        {
            try
            {
                var candidate = Path.Combine(dir, name);
                if (File.Exists(candidate)) return candidate;
            }
            catch { /* skip unreadable PATH entries */ }
        }
        return null;
    }

    private static string Sha256OfFile(string path)
    {
        using var stream = File.OpenRead(path);
        using var sha = SHA256.Create();
        var hash = sha.ComputeHash(stream);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    // ── Bwrap profile construction ────────────────────────────────────────

    private static BwrapProfile BuildBwrapProfile(
        SandboxConfig cfg,
        ResolvedAgentPaths resolved,
        string fixtureDest,
        string task,
        List<TraceEvent> trace)
    {
        // Read-only binds. We bind the entire host filesystem read-only so
        // the agent can read whatever it needs (libraries, the dotnet SDK,
        // the agent's own node_modules) but cannot damage any existing file
        // on the host. The only writable mount is /work (set in the base
        // profile). This is strictly stronger than the previous "tmpfs root
        // + enumerate every needed path" design — it catches the
        // "rm -rf the wrong dir trying to remove tmp files" case the user
        // specifically called out, and also handles path-enumeration drift
        // across distros (/lib, /lib64, /etc/alternatives, etc.).
        var candidateBinds = new (string Source, string Destination)[]
        {
            // The whole host, read-only.
            ("/", "/"),

            // Sandbox runtime tree (agent + its deps) — re-bound to itself
            // for clarity in trace output, even though / already covers it.
            (resolved.SandboxRoot, resolved.SandboxRoot),
        };
        var binds = new List<HostBind>();
        foreach (var (src, dest) in candidateBinds)
        {
            if (File.Exists(src) || Directory.Exists(src))
                binds.Add(new HostBind(src, dest));
            else
                trace.Add(new TraceEvent
                {
                    Timestamp = DateTime.UtcNow, Event = "coding.bwrap.bind_skipped",
                    Data = new { source = src, destination = dest,
                        reason = "source does not exist on host" }
                });
        }

        // $HOME/.dotnet is the SDK install for `dotnet` to be on PATH.
        // This is implicit in the / bind but we re-bind it for visibility.
        var userDotnet = Path.Combine(
            Environment.GetEnvironmentVariable("HOME") ?? "/root", ".dotnet");
        if (Directory.Exists(userDotnet)) binds.Add(new HostBind(userDotnet, userDotnet));

        // /tmp, /var/tmp, /run get tmpfs overlays by default in BwrapProfile
        // (see TmpfsScratchDirs) so the agent can scratch there without
        // polluting the host.

        // Env: only the keys the agent needs. HOME, TMPDIR, and XDG_CACHE_HOME
        // are all under /tmp/agent-workspace so the agent's scratch state
        // (npm cache, etc.) lives for the duration of the run and gets thrown
        // away with the workspace.
        var env = new Dictionary<string, string>
        {
            ["HOME"] = "/tmp/agent-workspace/.home",
            ["PATH"] = resolved.SandboxRoot + "/python-fixture-venv/bin:/usr/bin:/bin",
            ["TMPDIR"] = "/tmp/agent-workspace/.tmp",
            ["XDG_CACHE_HOME"] = "/tmp/agent-workspace/.cache",
            ["DOTNET_CLI_HOME"] = "/tmp/agent-workspace/.dotnet-home",
            ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1",
            ["DOTNET_NOLOGO"] = "1",
            ["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1",
            ["PI_SUPPRESS_JSON_MESSAGE_UPDATES"] = "1",
        };

        var hostNuGetPackages = Path.Combine(
            Environment.GetEnvironmentVariable("HOME") ?? "/root", ".nuget", "packages");
        if (Directory.Exists(hostNuGetPackages))
            env["NUGET_PACKAGES"] = hostNuGetPackages;

        // Agent config dir: pi looks for <PI_CODING_AGENT_DIR>/models.json
        // when discovering custom providers. Default to <sandbox_root>/agent
        // (which the runner binds read-only into the sandbox) so the same
        // models.json the user maintains on the host is visible inside.
        // The path passed to pi here MUST be the in-sandbox path; the runner
        // binds sandbox_root to itself, so the host path and the sandbox
        // path are identical.
        // Override via candidate config "agent_dir" (host path; will be
        // realpath'd and must live under sandbox_root so it's visible inside).
        var agentDirInSandbox = !string.IsNullOrEmpty(cfg.AgentDir)
            ? cfg.AgentDir
            : resolved.SandboxRoot + "/agent";
        env["PI_CODING_AGENT_DIR"] = agentDirInSandbox;
        // Pass through API key if configured.
        if (!string.IsNullOrEmpty(cfg.ApiKeyEnv))
        {
            var key = Environment.GetEnvironmentVariable(cfg.ApiKeyEnv);
            if (!string.IsNullOrEmpty(key))
                env[cfg.ApiKeyEnv] = key;
        }

        // Inner command: node <agent> <cli_args...> <task>
        var innerCommand = new List<string> { resolved.NodePath, resolved.AgentEntryScript };
        innerCommand.AddRange(cfg.CliArgs);
        innerCommand.Add(task);

        trace.Add(new TraceEvent
        {
            Timestamp = DateTime.UtcNow, Event = "coding.bwrap.profile_built",
            Data = new
            {
                workspace = fixtureDest,
                ro_bind_count = binds.Count,
                env_var_count = env.Count,
                inner_argv_length = innerCommand.Count
            }
        });

        return new BwrapProfile
        {
            // /tmp/agent-workspace is under the /tmp tmpfs overlay, which is
            // required for bwrap to mount a writable dir over a read-only /.
            WorkDir = "/tmp/agent-workspace",
            WorkDirSource = fixtureDest,
            ReadOnlyBinds = binds,
            Environment = env,
            Command = innerCommand,
        };
    }

    // ── Filesystem snapshot + diff ────────────────────────────────────────

    private sealed record FileSnapshot(
        string RelativePath,
        long Size,
        string Sha256);

    private static Dictionary<string, FileSnapshot> SnapshotDirectory(string root)
    {
        var result = new Dictionary<string, FileSnapshot>(StringComparer.Ordinal);
        foreach (var file in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories))
        {
            var rel = Path.GetRelativePath(root, file).Replace(Path.DirectorySeparatorChar, '/');
            var segments = rel.Split('/');
            if (segments.Any(s => SkipDirs.Contains(s))) continue;
            var info = new FileInfo(file);
            result[rel] = new FileSnapshot(rel, info.Length, Sha256OfFile(file));
        }
        return result;
    }

    private sealed record DiffResult(string UnifiedDiffText, IReadOnlyList<string> FilesChanged);

    private static DiffResult ComputeUnifiedDiff(
        Dictionary<string, FileSnapshot> before,
        Dictionary<string, FileSnapshot> after,
        string root)
    {
        var sb = new StringBuilder();
        var changed = new SortedSet<string>(StringComparer.Ordinal);

        foreach (var (path, snap) in after)
        {
            if (!before.TryGetValue(path, out var prev) || prev.Sha256 != snap.Sha256)
            {
                changed.Add(path);
                var fullPath = Path.Combine(root, path.Replace('/', Path.DirectorySeparatorChar));
                sb.AppendLine($"diff --git a/{path} b/{path}");
                sb.AppendLine("new file mode 100644");
                sb.AppendLine("--- /dev/null");
                sb.AppendLine($"+++ b/{path}");
                if (File.Exists(fullPath))
                {
                    foreach (var line in File.ReadAllLines(fullPath))
                        sb.AppendLine("+" + line);
                }
            }
        }

        foreach (var (path, _) in before)
        {
            if (!after.ContainsKey(path))
            {
                changed.Add(path);
                sb.AppendLine($"diff --git a/{path} b/{path}");
                sb.AppendLine("deleted file mode 100644");
                sb.AppendLine($"--- a/{path}");
                sb.AppendLine("+++ /dev/null");
                sb.AppendLine($"@@ -1,{LineCountOf(root, path)} +0,0 @@");
            }
        }

        return new DiffResult(sb.ToString(), changed.ToList());
    }

    private static int LineCountOf(string root, string relativePath)
    {
        var full = Path.Combine(root, relativePath.Replace('/', Path.DirectorySeparatorChar));
        if (!File.Exists(full)) return 0;
        return File.ReadAllLines(full).Length;
    }

    // ── Artifacts ─────────────────────────────────────────────────────────

    private static async Task WriteArtifactsAsync(
        CandidateConfig candidate,
        RunContext context,
        string fixtureDir,
        DiffResult diff,
        ProcessOutputCapture stdout,
        ProcessOutputCapture stderr,
        string bwrapCommandLine,
        CancellationToken ct)
    {
        var outputPath = context.GetCandidateOutputPath(candidate.Id);
        var outputDir = Path.GetDirectoryName(outputPath)!;
        Directory.CreateDirectory(outputDir);

        var stdoutPath = Path.Combine(outputDir, "stdout.log");
        var stderrPath = Path.Combine(outputDir, "stderr.log");
        await File.WriteAllTextAsync(stdoutPath, stdout.Text, ct);
        await File.WriteAllTextAsync(stderrPath, stderr.Text, ct);

        var output = new
        {
            fixture_dir = fixtureDir,
            patch = diff.UnifiedDiffText,
            files_changed = diff.FilesChanged,
            bwrap_command_line = bwrapCommandLine,
            stdout_path = Path.GetFileName(stdoutPath),
            stdout_length = stdout.RawLength,
            stdout_retained_length = stdout.Text.Length,
            stdout_filtered_message_update_lines = stdout.FilteredMessageUpdateLines,
            stdout_filtered_message_update_chars = stdout.FilteredMessageUpdateChars,
            stdout_tail = TruncateForInline(stdout.Text),
            stderr_path = Path.GetFileName(stderrPath),
            stderr_length = stderr.RawLength,
            stderr_tail = TruncateForInline(stderr.Text),
        };
        await File.WriteAllTextAsync(outputPath,
            JsonSerializer.Serialize(output, new JsonSerializerOptions { WriteIndented = true }),
            ct);

        var patchPath = Path.Combine(outputDir, "agent.patch");
        await File.WriteAllTextAsync(patchPath, diff.UnifiedDiffText, ct);
    }

    // ── Process output capture ─────────────────────────────────────────────

    private sealed record ProcessOutputCapture(
        string Text,
        long RawLength,
        int FilteredMessageUpdateLines = 0,
        long FilteredMessageUpdateChars = 0);

    private static async Task<ProcessOutputCapture> ReadProcessStreamAsync(
        StreamReader reader)
    {
        var sb = new StringBuilder();
        var rawLength = 0L;
        var buffer = new char[8192];
        int read;
        while ((read = await reader.ReadAsync(buffer, 0, buffer.Length)) > 0)
        {
            rawLength += read;
            sb.Append(buffer, 0, read);
        }
        return new ProcessOutputCapture(sb.ToString(), rawLength);
    }

    private static async Task<ProcessOutputCapture> ReadFilteredStdoutAsync(
        StreamReader reader)
    {
        var sb = new StringBuilder();
        var rawLength = 0L;
        var filteredLines = 0;
        var filteredChars = 0L;

        string? line;
        while ((line = await reader.ReadLineAsync()) != null)
        {
            var lineLength = line.Length + 1; // ReadLine strips the newline.
            rawLength += lineLength;
            if (IsJsonLineOfType(line, "message_update"))
            {
                filteredLines++;
                filteredChars += lineLength;
                continue;
            }

            sb.AppendLine(line);
        }

        return new ProcessOutputCapture(
            sb.ToString(), rawLength, filteredLines, filteredChars);
    }

    private static bool IsJsonLineOfType(string line, string expectedType)
    {
        if (string.IsNullOrWhiteSpace(line) || line[0] != '{') return false;
        try
        {
            using var doc = JsonDocument.Parse(line);
            if (!doc.RootElement.TryGetProperty("type", out var type)) return false;
            return type.ValueKind == JsonValueKind.String &&
                   string.Equals(type.GetString(), expectedType, StringComparison.Ordinal);
        }
        catch (JsonException)
        {
            return false;
        }
    }

    // ── Misc helpers ──────────────────────────────────────────────────────

    private static string TruncateForInline(string text)
    {
        if (text.Length <= MaxInlineRawResponseChars)
            return text;
        var omitted = text.Length - MaxInlineRawResponseChars;
        return $"[truncated {omitted} chars; see stdout.log/stderr.log artifact for full stream]\n" +
               text[^MaxInlineRawResponseChars..];
    }

    private static void CopyDirectory(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (var file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories))
        {
            var relative = Path.GetRelativePath(source, file);
            var segments = relative.Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            if (segments.Any(s => SkipDirs.Contains(s))) continue;
            var destFile = Path.Combine(destination, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(destFile)!);
            File.Copy(file, destFile, overwrite: true);
        }
    }

    private static void EnsureSandboxScratchDirs(string fixtureDest)
    {
        foreach (var relative in new[] { ".tmp", ".cache", ".home", ".dotnet-home" })
            Directory.CreateDirectory(Path.Combine(fixtureDest, relative));
    }

    private static void EnsureFixtureRuntime(
        string fixtureDest,
        string sandboxRoot,
        List<TraceEvent> trace)
    {
        if (!File.Exists(Path.Combine(fixtureDest, "pyproject.toml")) &&
            !File.Exists(Path.Combine(fixtureDest, "pytest.ini")))
            return;

        var runtimeDir = Path.Combine(sandboxRoot, "python-fixture-venv");
        var venvPython = Path.Combine(runtimeDir, "bin", "python");
        if (File.Exists(venvPython)) return;

        var uv = LocateOnPath("uv");
        try
        {
            if (!string.IsNullOrEmpty(uv))
            {
                RunSetupCommand(
                    uv,
                    new[] { "venv", "--python", "3.14", runtimeDir },
                    sandboxRoot,
                    TimeSpan.FromSeconds(90));
                RunSetupCommand(
                    uv,
                    new[] { "pip", "install", "--python", venvPython, "pytest" },
                    sandboxRoot,
                    TimeSpan.FromSeconds(120));
                trace.Add(new TraceEvent
                {
                    Timestamp = DateTime.UtcNow,
                    Event = "coding.fixture_runtime.prepared",
                    Data = new { kind = "python", tool = "uv", path = runtimeDir }
                });
                return;
            }

            var python = LocateOnPath("python3") ?? LocateOnPath("python");
            if (python == null) return;
            RunSetupCommand(
                python,
                new[] { "-m", "venv", runtimeDir },
                sandboxRoot,
                TimeSpan.FromSeconds(90));
            RunSetupCommand(
                venvPython,
                new[] { "-m", "pip", "install", "pytest" },
                sandboxRoot,
                TimeSpan.FromSeconds(120));
            trace.Add(new TraceEvent
            {
                Timestamp = DateTime.UtcNow,
                Event = "coding.fixture_runtime.prepared",
                Data = new { kind = "python", tool = "venv+pip", path = runtimeDir }
            });
        }
        catch (Exception ex)
        {
            // Runtime prep is an optimization for agent time, not a hard
            // fixture requirement. Scorers still run from the host if this fails.
            trace.Add(new TraceEvent
            {
                Timestamp = DateTime.UtcNow,
                Event = "coding.fixture_runtime.prepare_failed",
                Data = new { kind = "python", error = ex.Message }
            });
        }
    }

    private static void RunSetupCommand(
        string fileName,
        IReadOnlyList<string> args,
        string workingDirectory,
        TimeSpan timeout)
    {
        var psi = new ProcessStartInfo
        {
            FileName = fileName,
            WorkingDirectory = workingDirectory,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (var arg in args) psi.ArgumentList.Add(arg);
        using var process = Process.Start(psi) ??
            throw new InvalidOperationException($"Failed to start {fileName}");
        if (!process.WaitForExit(timeout))
        {
            TryKill(process);
            throw new TimeoutException($"Setup command timed out: {fileName} {string.Join(' ', args)}");
        }
        if (process.ExitCode != 0)
        {
            var stderr = process.StandardError.ReadToEnd();
            throw new InvalidOperationException(
                $"Setup command failed ({process.ExitCode}): {fileName} {string.Join(' ', args)}: {stderr[..Math.Min(stderr.Length, 500)]}");
        }
    }

    private static void TryKill(Process p)
    {
        try { if (!p.HasExited) p.Kill(entireProcessTree: true); }
        catch { /* best effort */ }
    }

    private static string GetStringFromInput(Scenario scenario, string key)
    {
        if (!scenario.Input.TryGetValue(key, out var v) || v == null) return string.Empty;
        if (v is string s) return s;
        if (v is JsonElement je && je.ValueKind == JsonValueKind.String)
            return je.GetString() ?? string.Empty;
        return v.ToString() ?? string.Empty;
    }

    private static string? GetConfigString(CandidateConfig candidate, string key)
    {
        if (!candidate.Config.TryGetValue(key, out var v) || v == null) return null;
        if (v is string s) return s;
        if (v is JsonElement je && je.ValueKind == JsonValueKind.String)
            return je.GetString();
        return null;
    }

    private static string FindRepoRoot(string runsRoot)
    {
        var dir = Path.GetDirectoryName(runsRoot) ?? runsRoot;
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir, "suites")) &&
                Directory.Exists(Path.Combine(dir, "src")))
                return dir;
            var parent = Path.GetDirectoryName(dir);
            if (parent == dir) break;
            dir = parent;
        }
        return Path.GetDirectoryName(runsRoot) ?? runsRoot;
    }

    // ── Internal value types ──────────────────────────────────────────────

    private sealed record ResolvedAgentPaths(
        string BwrapPath,
        string NodePath,
        string AgentEntryScript,
        string AgentEntrySha256,
        string SandboxRoot);

    private sealed record SandboxConfig(
        string AgentResolved,
        string NodeResolved,
        string SandboxRoot,
        string? DotnetRoot,
        string? ApiKeyEnv,
        string Task,
        IReadOnlyList<string> CliArgs,
        string? AgentDir = null)
    {
        public static SandboxConfig From(CandidateConfig c) => new(
            AgentResolved: GetConfigString(c, "agent_resolved")
                ?? throw new InvalidOperationException(
                    "candidate.config.agent_resolved is required for coding-agent kind."),
            NodeResolved: GetConfigString(c, "node_resolved") ?? "",
            SandboxRoot: GetConfigString(c, "sandbox_root")
                ?? throw new InvalidOperationException(
                    "candidate.config.sandbox_root is required (path to .sandbox-runtime/)."),
            DotnetRoot: GetConfigString(c, "dotnet_root"),
            ApiKeyEnv: GetConfigString(c, "api_key_env"),
            Task: GetConfigString(c, "task") ?? string.Empty,
            CliArgs: c.CliArgs,
            AgentDir: GetConfigString(c, "agent_dir"));
    }
}
