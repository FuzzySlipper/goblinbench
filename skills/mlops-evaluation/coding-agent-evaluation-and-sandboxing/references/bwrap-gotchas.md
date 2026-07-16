# bwrap Gotchas — Reproduction Recipes

Distilled from the GoblinBench CodingAgentRunner implementation (2026-06).
Each section: symptom, root cause, reproduction command (host must be Linux
with bwrap ≥ 0.10), and the fix.

## Gotcha 1: `--ro-bind /usr /usr` breaks execvp

**Symptom:**
```
$ bwrap --ro-bind /usr /usr -- /usr/bin/bash -c 'echo hi'
bwrap: execvp /usr/bin/bash: No such file or directory
```

**Root cause:** bwrap's `execvp` happens before/separately from full namespace
binding, and on modern distros the dynamic linker is reached via symlinked
paths that don't always resolve across the namespace boundary. Even though
`/usr/bin/bash` is a real ELF file, the loader path lookup fails.

**Reproduction (Arch Linux, kernel 7.x, bwrap 0.11.2):**
```bash
file /usr/bin/bash
# ELF 64-bit LSB pie executable, ... interpreter /lib64/ld-linux-x86-64.so.2, ...
ls -la /lib64  # symlink to usr/lib on Arch
bwrap --ro-bind /usr /usr -- /usr/bin/bash -c 'echo hi'  # fails
```

**Fix:** bind the whole host read-only instead. This works on every distro
because the kernel handles the full path resolution through the new namespace.

```bash
bwrap --ro-bind / / -- /usr/bin/bash -c 'echo hi'  # works
```

This is also *strictly stronger* protection — the agent can no longer write
to any existing file on the host, not just `/usr`.

---

## Gotcha 2: workspace parent must be writable

**Symptom:**
```
$ bwrap --ro-bind / / --bind /tmp/workspace /work -- /usr/bin/bash -c 'touch /work/x'
bwrap: Can't mkdir /work: Read-only file system
```

**Root cause:** bwrap creates the bind mount point if it doesn't already
exist in the destination namespace. With `/` read-only, it can't create
`/work` there.

**Reproduction:**
```bash
mkdir -p /tmp/workspace && touch /tmp/workspace/seed
bwrap --ro-bind / / --bind /tmp/workspace /work -- /usr/bin/bash -c 'touch /work/x'
# fails
```

**Fix:** mount the workspace under a tmpfs parent. The standard pattern is
`--tmpfs /tmp` followed by `--bind <host_dir> /tmp/agent-workspace`:

```bash
bwrap --ro-bind / / --tmpfs /tmp --bind /tmp/workspace /tmp/agent-workspace \
  -- /usr/bin/bash -c 'touch /tmp/agent-workspace/x; echo ok'  # works
```

**Validation rule:** in your `BwrapProfile.Validate()`, reject any
`WorkDir` that is not under one of the tmpfs scratch dirs (`/tmp`, `/var/tmp`,
`/run`). Otherwise the user will hit this at run time.

---

## Gotcha 3: inner-command symlinks fail to resolve

**Symptom:**
```
$ bwrap --ro-bind / / --tmpfs /tmp --bind /tmp/workspace /tmp/work -- /usr/bin/sh -c 'echo hi'
bwrap: execvp /usr/bin/sh: No such file or directory
```

Even though `/usr/bin/sh` exists on the host as a symlink to `/usr/bin/bash`,
and the target exists, bwrap's execvp can't resolve the symlink chain through
the bind mount.

**Reproduction:**
```bash
ls -la /usr/bin/sh  # lrwxrwxrwx ... /usr/bin/sh -> bash
bwrap --ro-bind / / --tmpfs /tmp -- /usr/bin/sh -c 'echo hi'  # fails
```

**Fix:** realpath the inner command before passing it to bwrap.

```bash
resolved=$(readlink -f /usr/bin/sh)  # /usr/bin/bash
bwrap --ro-bind / / --tmpfs /tmp -- "$resolved" -c 'echo hi'  # works
```

In .NET: `File.ResolveLinkTarget(path, returnFinalTarget: false)` chained up
to the kernel's symlink depth limit (32). Pass the final realpath to the
bwrap argv.

---

## Gotcha 4: missing source paths crash with a clear error

**Symptom:**
```
$ bwrap --ro-bind /usr /usr --ro-bind /etc/alternatives /etc/alternatives -- /bin/true
bwrap: Can't find source path /etc/alternatives: No such file or directory
```

**Root cause:** bwrap validates that every `--ro-bind` source exists at
startup, before launching the inner command. Some paths are distro-specific
(`/etc/alternatives` is Debian/Ubuntu; Arch doesn't have it).

**Fix:** at profile-construction time, only include `--ro-bind` for paths that
exist (`File.Exists || Directory.Exists`). Log a `bind_skipped` trace event
for the dropped ones. Don't put missing paths in the argv at all.

This is less of a concern if you're using `--ro-bind / /` (one bind, the
source is the root, which always exists), but you still need the guard for
explicit extra binds like the user's `.dotnet` directory or a custom sandbox
runtime tree.

---

## Gotcha 5: agent's HOME on tmpfs loses state every run

**Symptom:** every agent run takes 2+ minutes to warm up the npm cache, pi
auth tokens, dotnet restore cache, etc. Some agents fail outright without
their config.

**Root cause:** if `HOME=/tmp` and `/tmp` is a fresh tmpfs, the agent's
state files in `~/.cache`, `~/.config`, `~/.npm`, etc. are wiped when the
sandbox exits.

**Fix:** set `HOME`, `XDG_CACHE_HOME`, `TMPDIR`, `DOTNET_CLI_HOME` (for
dotnet), and any other XDG dirs all under the workspace:
```
HOME=/tmp/agent-workspace/.home
XDG_CACHE_HOME=/tmp/agent-workspace/.cache
TMPDIR=/tmp/agent-workspace/.tmp
DOTNET_CLI_HOME=/tmp/agent-workspace/.dotnet-home
```
The workspace itself is a writable bind; these sub-dirs live for the run
and are thrown away with the workspace.

---

## Gotcha 6: `--unshare-all` without `--share-net` cuts network

**Symptom:** model API calls time out, `dotnet restore` fails to reach
NuGet, agent exits with cryptic network errors.

**Root cause:** `--unshare-all` includes `--unshare-net`. With it, the
sandbox has no network interface, even loopback is not available.

**Fix:** add `--share-net` to keep the host's network namespace. The agent
and dotnet can reach the internet normally. If you need air-gapped
evaluation, override `ShareNetwork = false` on the profile.

---

## Combined happy-path argv

For reference, a working argv for a "coding agent editing a fixture"
sandbox on Arch:

```
bwrap
  --unshare-all
  --die-with-parent
  --hostname goblinbench-sandbox
  --share-net
  --ro-bind / /
  --ro-bind /home/dev/goblinbench/.sandbox-runtime /home/dev/goblinbench/.sandbox-runtime
  --ro-bind /home/agent/.dotnet /home/agent/.dotnet
  --tmpfs /tmp
  --tmpfs /var/tmp
  --tmpfs /run
  --bind /home/dev/goblinbench/runs/run-X/candidates/Y/fixture /tmp/agent-workspace
  --clearenv
  --setenv HOME /tmp/agent-workspace/.home
  --setenv PATH /usr/bin:/bin
  --setenv TMPDIR /tmp/agent-workspace/.tmp
  --setenv XDG_CACHE_HOME /tmp/agent-workspace/.cache
  --setenv DOTNET_CLI_HOME /tmp/agent-workspace/.dotnet-home
  --setenv DOTNET_CLI_TELEMETRY_OPTOUT 1
  --setenv DOTNET_NOLOGO 1
  --chdir /tmp/agent-workspace
  --
  /usr/bin/node
  /home/dev/goblinbench/.sandbox-runtime/node_modules/@earendil-works/pi-coding-agent/dist/cli.js
  --print
  --no-session
  --provider openai
  --model gpt-4o
  <task prompt>
```

The order matters: `--ro-bind` before `--tmpfs` and `--bind`, `--clearenv`
before any `--setenv`, `--chdir` after the env, `--` separates sandbox
options from the inner argv.
