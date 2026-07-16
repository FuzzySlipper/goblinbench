---
name: subprocess-sandbox
description: Run untrusted or low-trust subprocesses (coding agents, model CLIs, user-supplied tools) inside a Linux capability-restricted sandbox. Covers the "friction not fortress" design pattern, bubblewrap (bwrap) profile construction, common gotchas, and the test-with-fake-agent verification path. Use when the task is to launch a tool you don't fully trust and want it to fail safe without doing a hard security boundary.
version: 0.2.0
author: GoblinOverseer
license: MIT
metadata:
  hermes:
    tags: [sandbox, bwrap, bubblewrap, subprocess, isolation, coding-agents, agent-evaluation]
    related_skills: [spike, systematic-debugging, test-driven-development]
---

# Subprocess Sandbox — "Friction, Not Fortress"

This skill is for the recurring pattern of **running an untrusted or low-trust subprocess against artifacts you care about** and wanting it to fail safe when it misbehaves. The canonical example: a coding agent CLI (pi, codex, claude, opencode) given a fixture to edit, where a confused model under context pressure might do something dumb like `rm -rf` the wrong directory.

It is **not** for hostile-actor containment. If you actually need to defend against a malicious agent, use a real container (docker/podman) or firejail with strict seccomp. This skill is the "defaults that catch accidents" tier.

## When to use

Trigger on any of:

- "Run this coding agent / model CLI against a fixture and capture its diff."
- "I need to call out to an untrusted binary repeatedly with different inputs."
- "I want to make sure this tool can't damage the rest of the system if it goes wrong."
- "Run a model CLI non-interactively inside a bwrap / sandbox."
- "Capture the file edits a coding agent made to a workspace."

**Do not** trigger on hostile-actor isolation, network policy enforcement, or syscall filtering — those need a different tool.

## Design philosophy — "friction not fortress"

The user is rarely asking for actual containment. They are asking for **defaults that make destructive accidents hard to commit and easy to recover from**. The shift in framing matters: it changes the design space from "what access does the agent need to be denied" to "what state is expensive to put back if it gets damaged."

Practical consequences:

- **Network isolation is usually a non-goal.** If your agent needs to call a model API, and `dotnet restore` needs NuGet, you'll spend all your time fighting the sandbox. Don't.
- **Reads are fine.** The agent can `ls /etc` and `cat ~/.bashrc` — these are observations, not damage. Worry about writes.
- **Writes are what matter.** The only thing we restrict is the set of paths the agent can write to.
- **Make the workspace ephemeral.** If the agent mangles its own workspace, that's fine — the run gets re-run with a fresh copy. The expensive-to-rebuild state (nuget cache, dotnet SDK, your home directory) is read-only.
- **Don't enumerate needed paths by distro.** `bwrap --ro-bind / /` is simpler and stronger than `--tmpfs /` + every read-only path enumerated, and works the same on Arch, Debian, and NixOS. (See gotchas below.)

## Architecture

The standard shape:

1. **Resolve the agent's binary and dependencies to absolute paths** (chase symlinks so bwrap binds the real file). Compute a SHA-256 of the entry script and log it in the trace.
2. **Snapshot the workspace before the run** (file list + mtime + sha256).
3. **Build a `BwrapProfile` value type** describing the argv: `unshare-all`, `die-with-parent`, `share-net` (for NuGet/model API), `ro-bind` the host root, `tmpfs` overlay for scratch dirs, `bind` the workspace writable at `/tmp/agent-workspace` (or similar), `clearenv`, set only the env keys you need, `chdir` to the workspace, then the inner command.
4. **Launch the agent as a subprocess** with the bwrap argv. Capture stdout, stderr, exit code, and wall-clock duration.
5. **Snapshot the workspace after the run** and compute a unified diff (or a `git diff` if the workspace is a git repo).
6. **Run your existing scorer/evaluator** against the modified workspace. The diff is also written as a separate artifact (e.g. `agent.patch`) for later `git apply` use.

The runner should record every step in a `trace.jsonl` stream so failures are diagnosable from artifacts alone.

## Validation strategy — fake agent

Do not wait for a real model API to validate the harness. Write a **fake agent** that is a 5-line shell script which performs the operations you expect a real model to perform. Run the harness against it. This is your integration test.

Concretely: have the fake agent create a known file in the workspace, write its argv to a sentinel file, and exit 0. The runner should detect the file changes and emit a diff. If the runner instead sees no file changes or fails to launch, you have a sandbox-construction bug — and you'll find it without burning an API key.

For the **negative** case (agent can't escape the sandbox), have the fake agent attempt writes to `/tmp/escape-attempt` and a sensitive host path like `/home/<user>/.dotnet/escape-attempt`. After the run, assert neither file exists on the host. With `--ro-bind / /` + tmpfs scratch overlays, both writes should be silently blocked (or land in the sandbox's tmpfs, not the host's).

## Pitfalls (read these before designing the profile)

### 1. bwrap execvp fails through `--ro-bind /usr /usr`

Symptom: `bwrap: execvp /usr/bin/bash: No such file or directory` even though `/usr/bin/bash` is a real ELF binary on the host.

Cause: On modern distros, the dynamic linker (`/lib64/ld-linux-x86-64.so.2`) is reached via a symlinked path. `--ro-bind /usr /usr` doesn't always make that path resolvable inside the sandbox's namespace.

Fix: Use `--ro-bind / /` (the whole host, read-only) and let the kernel find the linker. This is also strictly stronger protection against destructive accidents.

### 2. bwrap needs the parent of the bind destination to be writable

Symptom: `bwrap: Can't mkdir /work: Read-only file system` even though you passed `--bind <host_dir> /work`.

Cause: bwrap creates the mount point if it doesn't already exist. With `/` read-only, it can't create `/work` there.

Fix: Mount the workspace under a tmpfs parent. The standard pattern is `--tmpfs /tmp` then `--bind <host_dir> /tmp/agent-workspace`. The default tmpfs scratch dirs in `BwrapProfile.TmpfsScratchDirs` are `/tmp`, `/var/tmp`, `/run`; pick your workspace path from one of those. `Validate()` should reject `WorkDir` values outside a tmpfs scratch dir.

### 3. Inner-command symlinks must be resolved

Symptom: `bwrap: execvp /usr/bin/sh: No such file or directory` where `/usr/bin/sh` exists on the host and is a symlink to `/usr/bin/bash`.

Cause: bwrap's execvp runs before/separately from the bind mount resolution. Symlinks inside the sandbox namespace don't always resolve cleanly across the namespace boundary.

Fix: Realpath the inner command (chase symlinks all the way to the leaf) before binding. In .NET this is `File.ResolveLinkTarget(path, returnFinalTarget: false)` chained up to the kernel symlink depth limit (32). On the host, the same fix is `readlink -f`.

### 4. Missing source paths crash bwrap

Symptom: `bwrap: Can't find source path /etc/alternatives: No such file or directory`.

Cause: bwrap refuses to start if a `--ro-bind` source doesn't exist. Some paths are distro-specific (`/etc/alternatives` is Debian-only; `/lib`, `/lib64` symlinks are Arch-specific).

Fix: When building the bwrap argv, only include `--ro-bind` for paths that exist (`File.Exists || Directory.Exists`). Log a `bind_skipped` trace event for the dropped ones. With `--ro-bind / /` this is a non-issue for *most* paths but you still want the guard for the explicit extra binds (sandbox root, user .dotnet, etc.).

### 5. The agent's home dir matters for state

If you set `HOME=/tmp` (a fresh tmpfs), the agent's `~/.cache`, `~/.config`, npm cache, etc. are all lost when the sandbox exits. That's a 2-minute warmup every run, and some agents refuse to start without their config.

Fix: Point `HOME`, `XDG_CACHE_HOME`, `TMPDIR`, and the dotnet CLI home all under the workspace (`/tmp/agent-workspace/.home` etc.). The agent's scratch state lives for the duration of the run and gets thrown away with the workspace.

### 6. Network access is opt-in, not opt-out

If you write `--unshare-all` without `--share-net`, the agent has no network at all. For a model API + NuGet restore, this is the wrong default.

Fix: Default `ShareNetwork = true`. Override to `false` for air-gapped evaluation runs.

### 7. The agent's own config dir is invisible to the sandbox

Symptom: the runner sets an env var like `PI_CODING_AGENT_DIR` (or
`ANTHROPIC_HOME`, `OPENCODE_CONFIG_DIR`, etc.) to a host path. The agent
inside the sandbox silently doesn't see its `models.json` / `auth.json` /
provider definitions, registers no providers, and either errors out with
"Unknown provider" or runs against a hard-coded default.

Root cause: with `--ro-bind / /` everything under the host root is
visible, but the agent's config dir path **must actually live under
the host root** for that to work. If the runner hard-codes
`~/.config/<agent>` and that path is in `/home/agent/`, you're fine. If
someone overrides it to `/tmp/lemonade-test/agent` or some other
not-under-`/` path, the agent will not find it.

Fix: when designing the candidate config for an "agent config dir" override,
either (a) make the default live under a known-bounded subdir of `/` (e.g.
`<sandbox_root>/agent`) and document that the override must also live under
the host root, or (b) explicitly add a `--ro-bind <host_dir> <in_sandbox_path>`
to the bwrap argv whenever a non-default agent_dir is configured. Verify with
`pi --list-models` (or the agent's equivalent) inside the sandbox showing
the custom provider.

### 8. A read-only host `/dev` is not enough

Symptom: tools that spawn subprocesses inside bwrap fail strangely: shell
redirects report `/dev/null: Permission denied`, Node `spawn(..., {stdio:
"ignore"})` raises `EACCES`, or a coding agent's bash tool times out and
kills the sandbox with exit 137 after starting a build/test command.

Root cause: with `--unshare-all --ro-bind / /`, device nodes from the host
root are visible but not usable in the user namespace. Many runtimes open
`/dev/null` for ignored stdio, so a missing usable `/dev` can break ordinary
subprocess execution even though the main agent process starts fine.

Fix: after the read-only binds and scratch tmpfs overlays, add a fresh device
mount before binding the workspace:

```bash
--tmpfs /tmp --tmpfs /var/tmp --tmpfs /run \
--dev /dev \
--bind "$WORKSPACE" /tmp/agent-workspace
```

Verify with:

```bash
bwrap ... --dev /dev ... -- /usr/bin/bash -lc 'echo ok </dev/null'
node -e 'require("child_process").spawn("/usr/bin/true", [], {stdio:["ignore","pipe","pipe"]}).on("exit", c => console.log(c))'
```

### 9. Tool-call models that never `stop` will hang the harness

Symptom: a coding-agent run against a real or mock model hangs past the
`scenario.timeout_seconds` and is killed with exit 137 (SIGKILL from
`--die-with-parent` + runner timeout). The fixture file is correctly
edited, but the run reports FAIL.

Root cause: many coding agents in `--print` / single-shot mode do not
return to the caller until the model emits a `finish_reason: "stop"`. If
the model instead keeps emitting `tool_calls` (e.g. "I should call write
again to be sure"), the agent loop never resolves. The harness waits,
the timeout fires, the inner command is killed.

Fix: this is on the **model side** and there's no harness-side cure
without changing the agent. Practical mitigations:

- For mock servers used in harness tests: have the mock branch on the
  previous turn's last role. If the last message is a `role: "tool"`
  result, return a brief `finish_reason: "stop"` text completion. If
  it's a `role: "user"`, return a single tool call. See
  `scripts/mock-openai-compat-server.js` for the exact pattern.
- For real models: pick ones known to terminate cleanly (Qwen3.6-35B-A3B
  and Gemma-4-26B-A4B-it tested OK; GLM-4.7-Flash hallucinates and
  loops). Budget `scenario.timeout_seconds` generously and treat a
  timeout-killed run with a clean diff as a partial success (the patch
  landed, the harness timed out waiting for the model to wrap up).
- The runner's snapshot/diff pipeline does not care whether the inner
  command exits 0 or 137 — it diffs the workspace. So a timeout-killed
  run still produces a useful `agent.patch` artifact.

### 10. Mock LLM servers must return streaming SSE, not JSON

Symptom: a custom OpenAI-compat mock returns a single JSON object as the
response body. The agent makes the call successfully but the streaming
parser in `@earendil-works/pi-ai` (and most other OpenAI clients)
silently hangs because it never sees the `data: ...\n\n` SSE chunk
boundaries.

Root cause: OpenAI's wire format is HTTP chunked transfer with
`Content-Type: text/event-stream` and `data: <json>\n\n` per chunk,
terminated by `data: [DONE]\n\n`. Many clients will also accept a
non-streamed response, but agents that use `for await (const chunk of
stream)` patterns will not.

Fix: when writing a mock LLM server for harness testing, always use SSE:

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

data: {"id":"...","object":"chat.completion.chunk","choices":[{"delta":{"role":"assistant","content":""}}]}

data: {"id":"...","object":"chat.completion.chunk","choices":[{"delta":{"content":"hi"}}]}

data: {"id":"...","object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

Use `res.write('data: ' + JSON.stringify(chunk) + '\n\n')` and end with
`'data: [DONE]\n\n'`. A working reference is
`scripts/mock-openai-compat-server.js` in this skill.

### 11. "No `--base-url` flag" — use the agent's models.json instead

Symptom: `pi --provider openai --base-url http://mylocal:13305/v1 ...
Error: Unknown option: --base-url`. The agent CLI rejects the base URL
flag you assumed every OpenAI-compat client would accept.

Root cause: most modern coding-agent CLIs (pi, opencode, claude code,
codex) don't expose `--base-url` as a generic flag. They either have
hard-coded built-in providers (openai, anthropic, azure, groq) or they
read a custom-provider config from a JSON file in the user's config dir.

Fix: write a `models.json` (or `config.json`, depending on the agent)
in the agent's config directory, with a custom provider block:

```json
{
  "providers": {
    "my-local": {
      "name": "My Local LLM",
      "baseUrl": "http://192.168.1.23:13305/v1",
      "api": "openai-completions",
      "apiKey": "***",
      "models": [
        { "id": "Qwen3.6-35B-A3B-GGUF", "name": "Qwen 35B", "reasoning": false,
          "input": ["text"], "contextWindow": 8192, "maxTokens": 2048,
          "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 } }
      ]
    }
  }
}
```

Then invoke with `--provider my-local --model <id>`. For pi the schema
is validated by `@earendil-works/pi-ai`'s `ModelRegistrySchema`; required
keys per model are `id`, `name`, `reasoning`, `input`, `contextWindow`,
`maxTokens`, `cost`. A wrong key causes pi to silently drop the
provider — verify with `pi --list-models` showing it. See the
`templates/pi-coding-agent-candidate.json` and
`templates/pi-models.json` files in this skill for known-good examples.

## Verification steps

After writing a sandbox runner, in this order:

1. **Profile shape test (no bwrap needed).** Construct a `BwrapProfile`, call `ToArgv`, assert the order of `--ro-bind`, `--tmpfs`, `--bind`, `--clearenv`, `--setenv`, `--chdir`, `--`. Use a record `with` to vary one field at a time and re-assert.
2. **`Validate()` tests.** Assert that foot-guns are caught: WorkDir at `/`, WorkDir outside a tmpfs scratch dir, relative paths everywhere, writable read-only bind, etc.
3. **Real-bwrap escape test.** Set up a fake agent (5-line shell script) that writes to known locations: inside the workspace (should succeed and show in the diff) and outside the workspace (should fail silently and not appear on the host). Run through the real bwrap. Assert.
4. **Real-bwrap diff test.** Same fake agent, but have it write a known file with known content. Assert the diff matches.
5. **Path-resolution test.** Point the runner at a non-existent agent path. Assert a clean, descriptive error (not a stack trace, not a 137 kill).
6. **End-to-end with a real model** (last, not first). Once the fake-agent tests are green, the only remaining risks are model-API specific (auth, model IDs, base URLs) and unrelated to the sandbox.

## Files & cross-references

- `references/bwrap-gotchas.md` — the distilled debugging notes from the session this skill was extracted from, with reproduction recipes for each failure mode
- `scripts/verify-bwrap.sh` — a 30-second smoke test that confirms bwrap is installed, the kernel supports user namespaces, and the basic `--ro-bind / / --tmpfs /tmp --bind <src> /tmp/work` pattern works on the current host. Run this *first* before committing to the design on a new host.
- `scripts/mock-openai-compat-server.js` — a minimal Node.js OpenAI-compat mock LLM for harness testing. Returns streaming SSE, branches on the previous turn's last role (tool result → text stop, user → single tool call), so a coding agent terminates cleanly. Use this when the real model server is offline or you want deterministic e2e tests. See gotchas 8 and 9.
- `templates/pi-models.json` — known-good `models.json` for `@earendil-works/pi-coding-agent`, with a custom `lemonade-lan` provider. Copy and edit the `baseUrl` + `apiKey` for your local endpoint. See gotcha 10.
- `templates/pi-coding-agent-candidate.json` — known-good `candidates.json` entry for a pi + bwrap CodingAgent runner. Wires `agent_dir`, `sandbox_root`, `node_resolved`, and the `--print --no-session` CLI args. See gotchas 7 and 10.
