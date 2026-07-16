# Multi-Machine Agent Deployment

## Machine Role Pattern

A practical multi-machine layout for running Hermes agents:

| Machine | Role | Hardware | Purpose |
|---------|------|----------|---------|
| den-srv | Coordination | Main server | Den MCP, backup destination, borgmatic → B2 |
| den-nimo | LLM inference | Strix Halo 128GB | Lemonade/vLLM, local model serving |
| den-k8 | Agent fleet | GMKtec K8 Plus | Independent Hermes profiles, Discord bots |

Each machine has a clear responsibility. Agents on den-k8 call den-nimo for LLM inference and den-srv for coordination/state.

## Agent User Convention

All machines use a dedicated `agent` user for agent access:
- Separates agent actions from personal user accounts (audit trail)
- SSH aliases follow `agent-<machine>` pattern (e.g. `agent-nimo`)
- Sudoers: NOPASSWD for diagnostics/systemctl/journalctl; package installs gated behind personal user
- Each agent profile runs under the agent user, not the personal account

## Systemd Template Pattern

Use systemd templates for managing multiple Hermes gateway profiles. Call the venv python directly — NOT the wrapper script (which may point to a stale install):

```ini
# /home/agent/.config/systemd/user/hermes-gateway@.service
[Unit]
Description=Hermes Agent Gateway - Profile %i
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
Environment=HERMES_HOME=/home/agents/profiles/%i
Environment=HERMES_HOME_MODE=0750
Environment=VIRTUAL_ENV=/home/agents/hermes-agent/venv
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=/home/agents/hermes-agent
ExecStart=/home/agents/hermes-agent/venv/bin/python -m hermes_cli.main --profile %i gateway run --replace
Restart=on-failure
RestartSec=10
RestartMaxDelaySec=300
RestartSteps=5
RestartForceExitStatus=75
KillMode=mixed
KillSignal=SIGTERM
ExecReload=/bin/kill -USR1 $MAINPID
TimeoutStopSec=210
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

Note: `HERMES_HOME=/home/agents/profiles/%i` is the per-profile path under the shared flat location. Using `python -m hermes_cli.main` directly bypasses the wrapper script and avoids stale-path issues.

**Critical: `HERMES_HOME_MODE` for group access.** Hermes calls `_secure_dir()` on startup, which forces `0o700` on the profile directory. This locks out any admin user not matching the file owner — even if they're in the correct group. Add `HERMES_HOME_MODE=0750` to the `[Service]` section:

```ini
[Service]
Type=simple
Environment=HERMES_HOME=/home/agents/profiles/%i
Environment=HERMES_HOME_MODE=0750
```

Without this, every gateway restart flips profile dirs back to `700` and the admin user loses `ls`/read access. The value is an octal mode — `0750` gives owner full, group read+execute, others nothing. Code path: `hermes_cli/config.py` → `_secure_dir()` → reads `HERMES_HOME_MODE` env var.

### Managing Services Across Users

`systemctl --user` runs under the CURRENT user's systemd daemon. To manage the `agent` user's services from another user (e.g. `patch`), you have two options:

**Option A: machinectl (cleaner)**
```bash
sudo machinectl shell agent@ systemctl --user restart hermes-gateway@kate.service
sudo machinectl shell agent@ systemctl --user daemon-reload
```

**Option B: D-Bus environment (more explicit)**
```bash
sudo -u agent env \
  XDG_RUNTIME_DIR=/run/user/$(id -u agent) \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u agent)/bus \
  systemctl --user start hermes-gateway-kate.service
```

**Pitfall:** `sudo -u agent systemctl --user ...` alone does NOT work — it inherits the calling user's D-Bus session, so systemd ignores the command or runs it under the wrong daemon. You MUST set both `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` (or use machinectl).

**Pitfall:** `timestamp_timeout=0` in sudoers means each sudo command needs a password prompt. Bundle multiple commands in one `sudo -u agent bash -c '...'` to avoid repeated prompts.

**Pitfall:** After editing a systemd unit file, always `daemon-reload` before restart — env var changes in unit files are not picked up without it.

Management (as agent user):
```bash
systemctl --user start hermes-gateway@kate
systemctl --user enable hermes-gateway@kate
systemctl --user status hermes-gateway@kate
systemctl --user restart hermes-gateway@kate
```

### Venv Python Symlink After Migration

When moving or copying a venv, the `python` symlink often points to the OLD user's home directory (e.g. `#!/home/patch/.local/share/uv/python/...`). This breaks ALL scripts in `bin/` — pip3, hermes, everything gets "bad interpreter: Permission denied."

**Full fix (reinstall Python + rebuild venv):**
```bash
# 1. Install Python system-wide (not in a user home dir)
sudo uv python install --system  # or pacman -S python

# 2. Recreate the venv with system Python
cd /home/agents/hermes-agent
python3 -m venv venv

# 3. Bootstrap pip (may not be included by default in Python 3.11+)
/home/agents/hermes-agent/venv/bin/python3 -m ensurepip --upgrade

# 4. Reinstall hermes with all extras
/home/agents/hermes-agent/venv/bin/pip3 install -e '.[web,pty]'
```

**Quick fix (if only pip is broken):**
```bash
/home/agents/hermes-agent/venv/bin/python3 -m ensurepip --upgrade
```

**Check current symlink target:**
```bash
ls -la /home/agents/hermes-agent/venv/bin/python
# Should point to system python, NOT /home/patch/.local/share/uv/...
```

## App/Data Separation

For permanent service deployments, keep the Hermes install and data directory independent:

- **App** (ephemeral): `pip install hermes-agent` → binary at `/usr/local/bin/hermes`
- **Data** (persistent): `HERMES_HOME=/home/agents` → profiles, sessions, skills, configs

This allows reinstalling/upgrading Hermes without touching data. Data gets backed up separately.

## Migration Pitfalls (User Install → Shared Location)

When moving Hermes from a personal home directory (e.g. `/home/patch/.hermes/`) to a shared location (e.g. `/home/agents/`), these gotchas bite hard:

### chown Order of Operations

Running processes (gateway, CLI sessions) immediately recreate files with the running user's ownership — especially SQLite journal files (`.db-shm`, `.db-wal`). Fix:

1. **Stop all hermes processes first** — `systemctl --user stop hermes-gateway-*`, kill any CLI sessions
2. **Then** `sudo chown -R agent:agents /home/agents/`
3. **Then** start services under the `agent` user

If you chown while processes are running, the files get recreated with wrong ownership within seconds.

### File Ownership Drift (Ongoing)

Even after initial chown, files created by a non-agent user (e.g. `patch` editing a skill) get `patch:patch` ownership. If the permissions are `600`, the `agent` user can't read them — the gateway silently fails to load skills, configs, etc.

Diagnosis:
```bash
# Find files the agent process can't read
find /home/agents/profiles/kate/skills -type f -user patch ! -perm -g=r
```

Fix:
```bash
sudo chown :agents <files> && sudo chmod 640 <files>
```

Prevention: setgid on parent dirs (`chmod 2775`) ensures new directories inherit the `agents` group, but most editors don't respect setgid for new *files*. Periodic sweep or editor configuration is the only real mitigation.

### Permission Diagnosis Workflow

When debugging "permission denied" errors on a shared profile setup, use this sequence:

```bash
# 1. Check the full permission chain from root to target file
namei -l /home/agents/profiles/kate/config.yaml

# 2. Check specific directory/file ownership
stat -c '%a %U:%G %n' /home/agents/profiles/kate

# 3. Find files the agent process can't read (owned by wrong user, no group read)
find /home/agents/profiles/kate -type f -user patch ! -perm -g=r

# 4. Check which user the gateway is running as
ps aux | grep hermes | grep -v grep

# 5. Check if the user is in the correct groups
id patch  # should show 'agents' in groups
```

Common root causes:
- File owned by `patch:patch` with `600` → `agent` can't read (needs `:agents` group + `640`)
- Directory at `700` → blocks traversal even for group members (needs `750`)
- `_secure_dir()` resetting perms → add `HERMES_HOME_MODE=0750` to systemd unit
- Stale process holding old permissions → stop all processes before chown

### Stale Systemd Services

The old user-level install leaves services at `~/.config/systemd/user/hermes-gateway-*.service` pointing to the old code path. These will crash-loop if left enabled because they reference stale venvs or wrong `HERMES_HOME`. Fix:

```bash
# Stop and disable old services
systemctl --user stop hermes-gateway-kate.service
systemctl --user disable hermes-gateway-kate.service

# Remove old service files
rm ~/.config/systemd/user/hermes-gateway-*.service
systemctl --user daemon-reload
```

### HERMES_HOME Path in New Services

The systemd template must point `HERMES_HOME` to the actual shared location, NOT to a subdirectory of the agent user's home:

```ini
# CORRECT — flat, memorable path
Environment=HERMES_HOME=/home/agents

# WRONG — buried in agent's home, hard to remember
Environment=HERMES_HOME=/home/agent/hermes
Environment=HERMES_HOME=/home/agent/.hermes
```

The user's preference: paths should be easily remembered months later. `/home/agents/` beats `/home/agent/.hermes/` for discoverability.

### HERMES_HOME and --profile Interaction

When both `HERMES_HOME` and `--profile` are set (as in the systemd template), `--profile` always wins — it overrides the env var and re-resolves the path. This means `HERMES_HOME` is NOT redundant in the systemd unit; it serves as a safety net for child processes that inherit the env var but don't get `--profile` explicitly.

The `get_default_hermes_root()` function in `hermes_constants.py` is smart about this: if `HERMES_HOME` points to a profile path (`<root>/profiles/<name>`), it detects the `profiles` parent directory name and uses the grandparent as the root. This means `hermes profile list` works correctly regardless of whether you're inside a profile or at the root.

Child processes spawned by the gateway (delegate_task, cron jobs, etc.) should inherit the profile's `HERMES_HOME`, NOT the root. Each profile is self-contained — children use the same config, skills, and sessions as their parent.

### Two Installs Coexisting

Migration often leaves both the old system-wide install (`/usr/local/lib/hermes-agent/`, root-owned) and the new shared install. The old install should be removed after migration:

```bash
# Check what's still referencing the old install
grep -r '/usr/local/lib/hermes-agent' ~/.config/systemd/user/
grep -r '/usr/local/lib/hermes-agent' /etc/systemd/

# Remove old install
sudo rm -rf /usr/local/lib/hermes-agent/
sudo rm /usr/local/bin/hermes  # if it points to old install
```

### Old State Cleanup

`~/.hermes/` in the personal home may still contain session files, logs, and memories from before the migration. Safe to remove after confirming the new location has what you need:

```bash
# Archive just in case
tar czf ~/hermes-old-state-backup.tar.gz ~/.hermes/

# Then remove
rm -rf ~/.hermes/
```

## Backup Strategy

- Hermes data (`$HERMES_HOME/`): borg backup to den-srv
- Den state: already on den-srv
- den-srv: borgmatic nightly to B2 (cloud storage)

The two backup sources complement each other:
- Hermes backup covers sessions, memory, skills, profile configs, auth tokens
- Den backup covers project tasks, documents, agent guidance, cross-project state

## Discord Bot Name Visibility

Agents **cannot** see their own Discord bot name — no API endpoint for this. When users refer to the bot by its display name, the agent won't know what they mean unless told. Set the name in the agent's personality/system prompt or tell it once and let it save to memory.

## TUI vs Systemd Gateway

The TUI (`hermes --tui`) always spawns its own gateway subprocess via pipe (stdin/stdout JSON-RPC). It does **not** attach to an already-running systemd gateway. The two are mutually exclusive for the same profile — running both simultaneously would cause conflicts (double Discord connections, session locks, etc.).

To use TUI with a profile managed by systemd:
1. Stop the systemd service: `systemctl --user stop hermes-gateway@<name>`
2. Run TUI: `hermes --tui --profile <name>`
3. When done, restart: `systemctl --user start hermes-gateway@<name>`

For always-on agents, the systemd gateway is the correct model. TUI is for interactive admin sessions when you want direct control.

## Web Dashboard on LAN

The dashboard refuses to bind to `0.0.0.0` without `--insecure`:

```
Refusing to bind to 0.0.0.0 — the dashboard exposes API keys and config without robust authentication.
Use --insecure to override (NOT recommended on untrusted networks).
```

For a home network behind a firewall with no public access, `--insecure` is fine. Add it to the systemd template:

```ini
ExecStart=... dashboard --host 0.0.0.0 --port 9119 --insecure --no-open --tui
```

Dashboard systemd template (`hermes-dashboard@.service`):

```ini
[Unit]
Description=Hermes Agent Dashboard - Profile %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=HERMES_HOME=/home/agents/profiles/%i
Environment=HERMES_HOME_MODE=0750
Environment=VIRTUAL_ENV=/home/agents/hermes-agent/venv
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=/home/agents/hermes-agent
ExecStart=/home/agents/hermes-agent/venv/bin/python -m hermes_cli.main --profile %i dashboard --host 0.0.0.0 --port 9119 --insecure --no-open --tui
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

## Browser Tool Bot Detection

The browser tool (Chromium-based) works for page navigation and scraping, but search engines aggressively block bot detection without residential proxies:

- **Google**: immediately redirects to CAPTCHA/sorry page
- **DuckDuckGo**: shows "Select all squares containing a duck" challenge
- **Bing**: Cloudflare "Verify you are human" checkbox (clickable, sometimes passes)

For reliable web search, use a search API key (Tavily, Brave, Exa) instead of browser-based search. The browser tool is better suited for navigating specific URLs and scraping content from pages that don't have bot detection.

The `web_extract` tool (fetching specific URLs) works without a search API key — it's only `web_search` that needs a backend.

## Resource Planning

Idle Hermes processes: ~80-120MB RAM each. No token costs while idle (LLM inference is remote). CPU negligible. A 32GB machine can run 20-30 instances comfortably. Bottleneck is RAM, not CPU.

## SSH Access

```ssh
Host agent-nimo
    Hostname 192.168.1.23
    user agent

Host agent-k8
    Hostname 192.168.1.x
    user agent
```

The agent user has NOPASSWD sudo for systemctl/journalctl. Package installs require the personal user's sudo (password required).
