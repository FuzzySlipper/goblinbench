---
name: hermes-agent
description: "Configure, extend, or contribute to Hermes Agent."
version: 2.0.0
author: Hermes Agent + Teknium
license: MIT
metadata:
  hermes:
    tags: [hermes, setup, configuration, multi-agent, spawning, cli, gateway, development]
    homepage: https://github.com/NousResearch/hermes-agent
    related_skills: [claude-code, codex, opencode]
---

# Hermes Agent

Hermes Agent is an open-source AI agent framework by Nous Research that runs in your terminal, messaging platforms, and IDEs. It belongs to the same category as Claude Code (Anthropic), Codex (OpenAI), and OpenClaw — autonomous coding and task-execution agents that use tool calling to interact with your system. Hermes works with any LLM provider (OpenRouter, Anthropic, OpenAI, DeepSeek, local models, and 15+ others) and runs on Linux, macOS, and WSL.

What makes Hermes different:

- **Self-improving through skills** — Hermes learns from experience by saving reusable procedures as skills. When it solves a complex problem, discovers a workflow, or gets corrected, it can persist that knowledge as a skill document that loads into future sessions. Skills accumulate over time, making the agent better at your specific tasks and environment.
- **Persistent memory across sessions** — remembers who you are, your preferences, environment details, and lessons learned. Pluggable memory backends (built-in, Honcho, Mem0, and more) let you choose how memory works.
- **Multi-platform gateway** — the same agent runs on Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Email, and 10+ other platforms with full tool access, not just chat.
- **Provider-agnostic** — swap models and providers mid-workflow without changing anything else. Credential pools rotate across multiple API keys automatically.
- **Profiles** — run multiple independent Hermes instances with isolated configs, sessions, skills, and memory.
- **Extensible** — plugins, MCP servers, custom tools, webhook triggers, cron scheduling, and the full Python ecosystem.

People use Hermes for software development, research, system administration, data analysis, content creation, home automation, and anything else that benefits from an AI agent with persistent context and full system access.

**This skill helps you work with Hermes Agent effectively** — setting it up, configuring features, spawning additional agent instances, troubleshooting issues, finding the right commands and settings, and understanding how the system works when you need to extend or contribute to it.

**den-k8 local deployment note:** do not use older examples that point at `/home/agents/hermes-agent` or assume `/usr/local/bin/hermes` launches Hermes on den-k8. After the 2026-05 migration, app installs are per Unix user (not one shared mutable checkout), `/usr/local/bin/hermes` is a disabled safe stub, fleet profiles remain under `/home/agents/profiles/<profile>`, shared runtime under `/home/agents/runtime`, and maintenance scripts under `/home/agents/local/hermes-fleet/bin`. The authoritative Den reference is `den-network/den-k8-hermes-local-setup-for-agents`.

**Docs:** https://hermes-agent.nousresearch.com/docs/

## Quick Start

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

# Interactive chat (default)
hermes

# Single query
hermes chat -q "What is the capital of France?"

# Setup wizard
hermes setup

# Change model/provider
hermes model

# Check health
hermes doctor
```

---

## CLI Reference

### Global Flags

```
hermes [flags] [command]

  --version, -V             Show version
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --pass-session-id         Include session ID in system prompt
```

No subcommand defaults to `chat`.

### Chat

```
hermes chat [flags]
  -q, --query TEXT          Single query, non-interactive
  -m, --model MODEL         Model (e.g. anthropic/claude-sonnet-4)
  -t, --toolsets LIST       Comma-separated toolsets
  --provider PROVIDER       Force provider (openrouter, anthropic, nous, etc.)
  -v, --verbose             Verbose output
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --source TAG              Session source tag (default: cli)
```

### Configuration

```
hermes setup [section]      Interactive wizard (model|terminal|gateway|tools|agent)
hermes model                Interactive model/provider picker
hermes config               View current config
hermes config edit          Open config.yaml in $EDITOR
hermes config set KEY VAL   Set a config value
hermes config path          Print config.yaml path
hermes config env-path      Print .env path
hermes config check         Check for missing/outdated config
hermes config migrate       Update config with new options
hermes login [--provider P] OAuth login (nous, openai-codex)
hermes logout               Clear stored auth
hermes doctor [--fix]       Check dependencies and config
hermes status [--all]       Show component status
```

### Tools & Skills

```
hermes tools                Interactive tool enable/disable (curses UI)
hermes tools list           Show all tools and status
hermes tools enable NAME    Enable a toolset
hermes tools disable NAME   Disable a toolset

hermes skills list          List installed skills
hermes skills search QUERY  Search the skills hub
hermes skills install ID    Install a skill (ID can be a hub identifier OR a direct https://…/SKILL.md URL; pass --name to override when frontmatter has no name)
hermes skills inspect ID    Preview without installing
hermes skills config        Enable/disable skills per platform
hermes skills check         Check for updates
hermes skills update        Update outdated skills
hermes skills uninstall N   Remove a hub skill
hermes skills publish PATH  Publish to registry
hermes skills browse        Browse all available skills
hermes skills tap add REPO  Add a GitHub repo as skill source
```

### MCP Servers

```
hermes mcp serve            Run Hermes as an MCP server
hermes mcp add NAME         Add an MCP server (--url or --command)
hermes mcp remove NAME      Remove an MCP server
hermes mcp list             List configured servers
hermes mcp test NAME        Test connection
hermes mcp configure NAME   Toggle tool selection
```

### Web Dashboard

Browser-based UI for managing your Hermes installation — config editor, API key manager, session browser, log viewer, analytics, cron jobs, skills toggle, and an in-browser chat tab.

```
hermes dashboard              Start on http://127.0.0.1:9119 (opens browser)
hermes dashboard --port 8080  Custom port
hermes dashboard --host 0.0.0.0  Bind all interfaces (DANGEROUS — exposes keys)
hermes dashboard --no-open    Don't auto-open browser
hermes dashboard --tui        Enable the in-browser Chat tab (PTY/WebSocket)
```

**Prerequisites** (not installed by default):
```bash
pip install 'hermes-agent[web,pty]'    # web = FastAPI+Uvicorn, pty = ptyprocess
# OR
pip install hermes-agent[all]          # includes everything
```

For source installs (git clone), run from the repo dir:
```bash
venv/bin/pip install -e '.[web,pty]'
```

If the frontend hasn't been built and npm is available, it builds automatically on first launch. The `hermes update` command also rebuilds it.

Pages: Status (live overview), Chat (embedded TUI), Config (form editor), API Keys, Sessions (browse/search), Logs (live tail), Analytics (token usage/cost), Cron (manage jobs), Skills (toggle).

**LAN/remote access:** `--host` and `--port` are NOT configurable via `config.yaml` — they're CLI-only flags (defaults: 127.0.0.1:9119). For recurring LAN access, add a shell alias:
```bash
alias hermes-dashboard='hermes dashboard --host 0.0.0.0 --no-open'
```

**Always-on dashboard for config editing:** On a trusted LAN, running the dashboard persistently is convenient for config editing, session browsing, and log viewing. Add as a systemd service or run alongside the gateway. Security concern is minimal on a home network behind a firewall with no public access — the paranoia is for VPS/shared hosting. API keys in the config editor are only exposed to LAN.

Full details: [references/web-dashboard.md](references/web-dashboard.md)

### Gateway (Messaging Platforms)

```
hermes gateway run          Start gateway foreground
hermes gateway install      Install as background service
hermes gateway start/stop   Control the service
hermes gateway restart      Restart the service
hermes gateway status       Check status
hermes gateway setup        Configure platforms
```

**Multi-profile gateway deployment (systemd template):** Each profile that connects to Discord needs its own gateway process. Use a systemd template service to manage them cleanly. Call the venv python directly — NOT a wrapper script (which may point to a stale install):

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

```bash
# Manage per-profile (as agent user)
systemctl --user start hermes-gateway@kate
systemctl --user enable hermes-gateway@kate
systemctl --user status hermes-gateway@kate
systemctl --user restart hermes-gateway@kate  # after config change
```

**Critical: enable linger** or services die when the `agent` user has no active session:
```bash
sudo loginctl enable-linger agent
```
Without linger, a reboot with no SSH session means all gateways are dead.

**Managing from another user:** `systemctl --user` runs under the calling user's systemd. To manage agent user's services from a different user, pass the D-Bus environment:
```bash
sudo -u agent env \
  XDG_RUNTIME_DIR=/run/user/$(id -u agent) \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u agent)/bus \
  systemctl --user start hermes-gateway-kate.service
```

Each profile gets its own Discord bot token, config, memory, and session history. Idle gateway footprint: ~80-120MB RAM per instance. See [references/multi-machine-deployment.md](references/multi-machine-deployment.md) for full migration pitfalls.

Supported platforms: Telegram, Discord, Slack, WhatsApp, Signal, Email, SMS, Matrix, Mattermost, Home Assistant, DingTalk, Feishu, WeCom, BlueBubbles (iMessage), Weixin (WeChat), API Server, Webhooks. Open WebUI connects via the API Server adapter.

Platform docs: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

### Sessions

```
hermes sessions list        List recent sessions
hermes sessions browse      Interactive picker
hermes sessions export OUT  Export to JSONL
hermes sessions rename ID T Rename a session
hermes sessions delete ID   Delete a session
hermes sessions prune       Clean up old sessions (--older-than N days)
hermes sessions stats       Session store statistics
```

### Cron Jobs

```
hermes cron list            List jobs (--all for disabled)
hermes cron create SCHED    Create: '30m', 'every 2h', '0 9 * * *'
hermes cron edit ID         Edit schedule, prompt, delivery
hermes cron pause/resume ID Control job state
hermes cron run ID          Trigger on next tick
hermes cron remove ID       Delete a job
hermes cron status          Scheduler status
```

### Webhooks

```
hermes webhook subscribe N  Create route at /webhooks/<name>
hermes webhook list         List subscriptions
hermes webhook remove NAME  Remove a subscription
hermes webhook test NAME    Send a test POST
```

### Profiles

```
hermes profile list         List all profiles
hermes profile create NAME  Create (--clone, --clone-all, --clone-from)
hermes profile use NAME     Set sticky default
```

**Cloning for multi-profile deployments:** `--clone` copies config, `.env`, SOUL.md, and skills from an existing profile. Essential for fleet setups where profiles share the same API keys:

```bash
hermes profile create scout --clone --clone-from kate
```

This gives `scout` the same API keys and base config as `kate` — then customize (different Discord bot token, persona, toolsets). All profiles inherit the same bounded-billing keys, so damage from a rogue agent is limited to the shared pool.
hermes profile show NAME    Show details
hermes profile alias NAME   Manage wrapper scripts
hermes profile rename A B   Rename a profile
hermes profile export NAME  Export to tar.gz
hermes profile import FILE  Import from archive
```

**App vs data separation for service deployments:** The Hermes install (binary) and data directory (`HERMES_HOME`) are independent. For permanent service deployments, keep them separate so the app can be reinstalled/upgraded without touching data:

```bash
# Global app install (ephemeral, replaceable)
pip install hermes-agent
# Binary at /usr/local/bin/hermes

# Data lives elsewhere (persistent, backed up)
export HERMES_HOME=/home/agent/hermes
# All profiles, sessions, skills, configs live here
```

The main `~/.hermes/` directory IS the default profile. Named profiles live at `$HERMES_HOME/profiles/<name>/` with the same directory structure. See `references/discord-multi-agent.md` for multi-agent Discord config.

### Credential Pools

```
hermes auth add             Interactive credential wizard
hermes auth list [PROVIDER] List pooled credentials
hermes auth remove P INDEX  Remove by provider + index
hermes auth reset PROVIDER  Clear exhaustion status
```

### Other

```
hermes dashboard             Start web dashboard (http://127.0.0.1:9119)
hermes insights [--days N]  Usage analytics
hermes update               Update to latest version
hermes pairing list/approve/revoke  DM authorization
hermes plugins list/install/remove  Plugin management
hermes honcho setup/status  Honcho memory integration (requires honcho plugin)
hermes memory setup/status/off  Memory provider config
hermes completion bash|zsh  Shell completions
hermes acp                  ACP server (IDE integration)
hermes claw migrate         Migrate from OpenClaw
hermes uninstall            Uninstall Hermes
```

---

## Slash Commands (In-Session)

Type these during an interactive chat session.

### Session Control
```
/new (/reset)        Fresh session
/clear               Clear screen + new session (CLI)
/retry               Resend last message
/undo                Remove last exchange
/title [name]        Name the session
/compress            Manually compress context
/stop                Kill background processes
/rollback [N]        Restore filesystem checkpoint
/background <prompt> Run prompt in background
/queue <prompt>      Queue for next turn
/resume [name]       Resume a named session
```

### Configuration
```
/config              Show config (CLI)
/model [name]        Show or change model
/personality [name]  Set personality
/reasoning [level]   Set reasoning (none|minimal|low|medium|high|xhigh|show|hide)
/verbose             Cycle: off → new → all → verbose
/voice [on|off|tts]  Voice mode
/yolo                Toggle approval bypass
/skin [name]         Change theme (CLI)
/statusbar           Toggle status bar (CLI)
```

### Tools & Skills
```
/tools               Manage tools (CLI)
/toolsets            List toolsets (CLI)
/skills              Search/install skills (CLI)
/skill <name>        Load a skill into session
/cron                Manage cron jobs (CLI)
/reload-mcp          Reload MCP servers
/plugins             List plugins (CLI)
```

### Gateway
```
/approve             Approve a pending command (gateway)
/deny                Deny a pending command (gateway)
/restart             Restart gateway (gateway)
/sethome             Set current chat as home channel (gateway)
/update              Update Hermes to latest (gateway)
/platforms (/gateway) Show platform connection status (gateway)
```

### Utility
```
/branch (/fork)      Branch the current session
/fast                Toggle priority/fast processing
/browser             Open CDP browser connection
/history             Show conversation history (CLI)
/save                Save conversation to file (CLI)
/paste               Attach clipboard image (CLI)
/image               Attach local image file (CLI)
```

### Info
```
/help                Show commands
/commands [page]     Browse all commands (gateway)
/usage               Token usage
/insights [days]     Usage analytics
/status              Session info (gateway)
/profile             Active profile info
```

### Exit
```
/quit (/exit, /q)    Exit CLI
```

---

## Key Paths & Config

```
~/.hermes/config.yaml       Main configuration
~/.hermes/.env              API keys and secrets
$HERMES_HOME/skills/        Installed skills
~/.hermes/sessions/         Session transcripts
~/.hermes/logs/             Gateway and error logs
~/.hermes/auth.json         OAuth tokens and credential pools
~/.hermes/hermes-agent/     Source code (if git-installed)
```

Profiles use `~/.hermes/profiles/<name>/` with the same layout.

### Config Sections

Edit with `hermes config edit` or `hermes config set section.key value`.

| Section | Key options |
|---------|-------------|
| `model` | `default`, `provider`, `base_url`, `api_key`, `context_length` |
| `agent` | `max_turns` (90), `tool_use_enforcement` |
| `terminal` | `backend` (local/docker/ssh/modal), `cwd`, `timeout` (180) |
| `compression` | `enabled`, `threshold` (0.50), `target_ratio` (0.20), `protect_last_n` (20) |
| `context` | `engine` (default: "compressor") — pluggable context engine |
| `display` | `skin`, `tool_progress`, `show_reasoning`, `show_cost` |
| `stt` | `enabled`, `provider` (local/groq/openai/mistral) |
| `tts` | `provider` (edge/elevenlabs/openai/minimax/mistral/neutts) |
| `memory` | `memory_enabled`, `user_profile_enabled`, `provider` |
| `security` | `tirith_enabled`, `website_blocklist` |
| `delegation` | `model`, `provider`, `base_url`, `api_key`, `max_iterations` (50), `reasoning_effort` |
| `checkpoints` | `enabled`, `max_snapshots` (50) |

Full config reference: https://hermes-agent.nousresearch.com/docs/user-guide/configuration

### Provider Fallback Chain

Hermes supports automatic provider failover when the primary model is unavailable. Configure with `fallback_model` — either a single dict or a **list of dicts** for a priority chain:

```yaml
model:
  default: mimo-v2.5
  provider: xiaomi
  base_url: https://your-endpoint.com/v1

# Single fallback
fallback_model:
  provider: openrouter
  model: anthropic/claite-sonnet-4

# OR chain (tries each in order on failure)
fallback_model:
  - provider: kimi
    model: moonshot-v1-auto
    base_url: https://api.moonshot.cn/v1
  - provider: openrouter
    model: anthropic/claude-sonnet-4
```

Each entry can have its own `base_url` and `api_key` (or inherits from env vars / credential pools). Triggers on rate limits (429), billing errors, service errors (503/529), and connection failures. Rate-limited providers get a 60-second cooldown before retry.

### Providers

20+ providers supported. Set via `hermes model` or `hermes setup`.

| Provider | Auth | Key env var |
|----------|------|-------------|
| OpenRouter | API key | `OPENROUTER_API_KEY` |
| Anthropic | API key | `ANTHROPIC_API_KEY` |
| Nous Portal | OAuth | `hermes auth` |
| OpenAI Codex | OAuth | `hermes auth` |
| GitHub Copilot | Token | `COPILOT_GITHUB_TOKEN` |
| Google Gemini | API key | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| DeepSeek | API key | `DEEPSEEK_API_KEY` |
| xAI / Grok | API key | `XAI_API_KEY` |
| Hugging Face | Token | `HF_TOKEN` |
| Z.AI / GLM | API key | `GLM_API_KEY` |
| MiniMax | API key | `MINIMAX_API_KEY` |
| MiniMax CN | API key | `MINIMAX_CN_API_KEY` |
| Kimi / Moonshot | API key | `KIMI_API_KEY` |
| Alibaba / DashScope | API key | `DASHSCOPE_API_KEY` |
| Xiaomi MiMo | API key | `XIAOMI_API_KEY` |
| Kilo Code | API key | `KILOCODE_API_KEY` |
| AI Gateway (Vercel) | API key | `AI_GATEWAY_API_KEY` |
| OpenCode Zen | API key | `OPENCODE_ZEN_API_KEY` |
| OpenCode Go | API key | `OPENCODE_GO_API_KEY` |
| Qwen OAuth | OAuth | `hermes login --provider qwen-oauth` |
| Custom endpoint | Config | `model.base_url` + `model.api_key` in config.yaml |
| GitHub Copilot ACP | External | `COPILOT_CLI_PATH` or Copilot CLI |

Full provider docs: https://hermes-agent.nousresearch.com/docs/integrations/providers

### Toolsets

Enable/disable via `hermes tools` (interactive) or `hermes tools enable/disable NAME`.

| Toolset | What it provides |
|---------|-----------------|
| `web` | Web search and content extraction |
| `browser` | Browser automation (Browserbase, Camofox, or local Chromium) |
| `terminal` | Shell commands and process management |
| `file` | File read/write/search/patch |
| `code_execution` | Sandboxed Python execution |
| `vision` | Image analysis |
| `image_gen` | AI image generation |
| `tts` | Text-to-speech |
| `skills` | Skill browsing and management |
| `memory` | Persistent cross-session memory |
| `session_search` | Search past conversations |
| `delegation` | Subagent task delegation |
| `cronjob` | Scheduled task management |
| `clarify` | Ask user clarifying questions |
| `messaging` | Cross-platform message sending |
| `search` | Web search only (subset of `web`) |
| `todo` | In-session task planning and tracking |
| `rl` | Reinforcement learning tools (off by default) |
| `moa` | Mixture of Agents (off by default) |
| `homeassistant` | Smart home control (off by default) |

Tool changes take effect on `/reset` (new session). They do NOT apply mid-conversation to preserve prompt caching.

### Context Management & Compression

Hermes manages context window usage automatically via a pluggable context engine.

**Automatic compression** triggers when context hits the threshold (default 50% of context window) and compresses to the target ratio (default 20%). The engine summarizes older exchanges while protecting recent messages (`protect_last_n`, default 20).

**Manual compression:** `/compress` — triggers immediately. Can take a focus topic to preserve specific content:
```
/compress keep the architecture discussion, drop the setup banter
```

**Usage visibility:** `/usage` shows token usage for the current session.

**Agent limitations:** The agent cannot query its own context usage or trigger compression programmatically. Compression is framework-managed (`run_agent.py` checks after each turn). The agent has no tool to see `context_length` or `last_prompt_tokens`.

**Pluggable engines:** Replace the default compressor via `context.engine` config. Custom engines implement the `ContextEngine` ABC in `agent/context_engine.py`. Useful for domain-specific compression (e.g., roundtable-aware engines that protect certain message ranges).

```yaml
compression:
  enabled: true
  threshold: 0.50      # trigger at 50% full
  target_ratio: 0.20   # compress to 20%
  protect_last_n: 20   # protect recent messages from summarization
context:
  engine: compressor   # or custom engine name
```

---

## Security & Privacy Toggles

Common "why is Hermes doing X to my output / tool calls / commands?" toggles — and the exact commands to change them. Most of these need a fresh session (`/reset` in chat, or start a new `hermes` invocation) because they're read once at startup.

### Secret redaction in tool output

Secret redaction is **off by default** — tool output (terminal stdout, `read_file`, web content, subagent summaries, etc.) passes through unmodified. If the user wants Hermes to auto-mask strings that look like API keys, tokens, and secrets before they enter the conversation context and logs:

```bash
hermes config set security.redact_secrets true       # enable globally
```

**Restart required.** `security.redact_secrets` is snapshotted at import time — toggling it mid-session (e.g. via `export HERMES_REDACT_SECRETS=true` from a tool call) will NOT take effect for the running process. Tell the user to run `hermes config set security.redact_secrets true` in a terminal, then start a new session. This is deliberate — it prevents an LLM from flipping the toggle on itself mid-task.

Disable again with:
```bash
hermes config set security.redact_secrets false
```

### PII redaction in gateway messages

Separate from secret redaction. When enabled, the gateway hashes user IDs and strips phone numbers from the session context before it reaches the model:

```bash
hermes config set privacy.redact_pii true    # enable
hermes config set privacy.redact_pii false   # disable (default)
```

### Command approval prompts

By default (`approvals.mode: manual`), Hermes prompts the user before running shell commands flagged as destructive (`rm -rf`, `git reset --hard`, etc.). The modes are:

- `manual` — always prompt (default)
- `smart` — use an auxiliary LLM to auto-approve low-risk commands, prompt on high-risk
- `off` — skip all approval prompts (equivalent to `--yolo`)

```bash
hermes config set approvals.mode smart       # recommended middle ground
hermes config set approvals.mode off         # bypass everything (not recommended)
```

Per-invocation bypass without changing config:
- `hermes --yolo …`
- `export HERMES_YOLO_MODE=1`

Note: YOLO / `approvals.mode: off` does NOT turn off secret redaction. They are independent.

### Shell hooks allowlist

Some shell-hook integrations require explicit allowlisting before they fire. Managed via `~/.hermes/shell-hooks-allowlist.json` — prompted interactively the first time a hook wants to run.

### Disabling the web/browser/image-gen tools

To keep the model away from network or media tools entirely, open `hermes tools` and toggle per-platform. Takes effect on next session (`/reset`). See the Tools & Skills section above.

---

## Voice & Transcription

### STT (Voice → Text)

Voice messages from messaging platforms are auto-transcribed.

Provider priority (auto-detected):
1. **Local faster-whisper** — free, no API key: `pip install faster-whisper`
2. **Groq Whisper** — free tier: set `GROQ_API_KEY`
3. **OpenAI Whisper** — paid: set `VOICE_TOOLS_OPENAI_KEY`
4. **Mistral Voxtral** — set `MISTRAL_API_KEY`

Config:
```yaml
stt:
  enabled: true
  provider: local        # local, groq, openai, mistral
  local:
    model: base          # tiny, base, small, medium, large-v3
```

### TTS (Text → Voice)

| Provider | Env var | Free? |
|----------|---------|-------|
| Edge TTS | None | Yes (default) |
| ElevenLabs | `ELEVENLABS_API_KEY` | Free tier |
| OpenAI | `VOICE_TOOLS_OPENAI_KEY` | Paid |
| MiniMax | `MINIMAX_API_KEY` | Paid |
| Mistral (Voxtral) | `MISTRAL_API_KEY` | Paid |
| NeuTTS (local) | None (`pip install neutts[all]` + `espeak-ng`) | Free |

Voice commands: `/voice on` (voice-to-voice), `/voice tts` (always voice), `/voice off`.

---

## Spawning Additional Hermes Instances

Run additional Hermes processes as fully independent subprocesses — separate sessions, tools, and environments.

### When to Use This vs delegate_task

| | `delegate_task` | Spawning `hermes` process |
|-|-----------------|--------------------------|
| Isolation | Separate conversation, shared process | Fully independent process |
| Duration | Minutes (bounded by parent loop) | Hours/days |
| Tool access | Subset of parent's tools | Full tool access |
| Interactive | No | Yes (PTY mode) |
| Use case | Quick parallel subtasks | Long autonomous missions |

### One-Shot Mode

```
terminal(command="hermes chat -q 'Research GRPO papers and write summary to ~/research/grpo.md'", timeout=300)

# Background for long tasks:
terminal(command="hermes chat -q 'Set up CI/CD for ~/myapp'", background=true)
```

### Interactive PTY Mode (via tmux)

Hermes uses prompt_toolkit, which requires a real terminal. Use tmux for interactive spawning:

```
# Start
terminal(command="tmux new-session -d -s agent1 -x 120 -y 40 'hermes'", timeout=10)

# Wait for startup, then send a message
terminal(command="sleep 8 && tmux send-keys -t agent1 'Build a FastAPI auth service' Enter", timeout=15)

# Read output
terminal(command="sleep 20 && tmux capture-pane -t agent1 -p", timeout=5)

# Send follow-up
terminal(command="tmux send-keys -t agent1 'Add rate limiting middleware' Enter", timeout=5)

# Exit
terminal(command="tmux send-keys -t agent1 '/exit' Enter && sleep 2 && tmux kill-session -t agent1", timeout=10)
```

### Multi-Agent Coordination

```
# Agent A: backend
terminal(command="tmux new-session -d -s backend -x 120 -y 40 'hermes -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t backend 'Build REST API for user management' Enter", timeout=15)

# Agent B: frontend
terminal(command="tmux new-session -d -s frontend -x 120 -y 40 'hermes -w'", timeout=10)
terminal(command="sleep 8 && tmux send-keys -t frontend 'Build React dashboard for user management' Enter", timeout=15)

# Check progress, relay context between them
terminal(command="tmux capture-pane -t backend -p | tail -30", timeout=5)
terminal(command="tmux send-keys -t frontend 'Here is the API schema from the backend agent: ...' Enter", timeout=5)
```

### Session Resume

```
# Resume most recent session
terminal(command="tmux new-session -d -s resumed 'hermes --continue'", timeout=10)

# Resume specific session
terminal(command="tmux new-session -d -s resumed 'hermes --resume 20260225_143052_a1b2c3'", timeout=10)
```

### Architecture Principles

**Specialists outperform generalists.** Even with `delegate_task` sub-agent delegation, a single "do everything" agent with a bloated system prompt loses to discrete specialists prompted on their specifics. Each specialist gets a clean context window scoped to its domain — no noise from unrelated tasks.

**Context window management is critical.** Noise in the window limits reasoning space and causes sticky thinking. Coordination/manager agents are especially sensitive to context bloat because their scope is inherently broader. Protect their reasoning space aggressively.

**The librarian pattern (smart RAG).** Rather than having agents fill their context window searching for information, delegate search to a specialist that returns only the pruned, relevant subset. This keeps the working agent's context clean for reasoning. Works well with Den blackboard or session_search as the retrieval layer.

**Direct agent-call pattern for specialists.** For high-frequency internal questions (e.g. Hermes source/docs lookups), prefer a generic direct request/response mechanism over Discord or Den message passing. Discord adds human-interface friction and Den is better as durable blackboard/state, not hot-path RPC. A reusable local/LAN “agent call” shim should accept a structured request, route to a named specialist profile, wake/run it, and return either a synchronous result or a request ID for polling/callback. Keep the transport generic (`POST /call/{profile}`, `GET /call/{request_id}`), with token auth, timeouts, prompt-size limits, and redacted logs; make specialist profiles like `hermes-librarian` consumers of this primitive rather than baking librarian behavior into the transport. Use Den only for durable synthesized findings, service registry, and audit summaries.

**Discord servers for fleet coordination.** When deploying multiple Hermes instances, a Discord server provides better ergonomics than Telegram groups for multi-agent coordination: channels per agent/topic, threads for scoped conversations, roles for access control, and visual organization via categories. Telegram's flat chat structure fights you when multiple agents report status or workstreams run in parallel.

Multi-agent Discord requires two config changes from defaults:
- `discord.allow_bots mentions` — lets agents @mention each other (default `"none"` ignores all bot messages)
- `discord.auto_thread false` — keeps conversations in-channel instead of spinning up threads on every @mention

**Context gap:** Agents do NOT see channel history when @mentioned — only the triggering message + reply context. Agents can @each other with summaries, or use Den blackboard for cross-agent context. Full config reference: [references/discord-multi-agent.md](references/discord-multi-agent.md).

**Example fleet layout:**
- `#ops` — monitoring, status reports, infrastructure watch
- `#coding` — orchestrator delegating to pi/codex/claude-code
- `#research` — paper discovery, web monitoring, knowledge gathering
- `#coordination` — cross-agent state, task routing

**Roundtable deliberation pattern:** For multi-agent discussions where participants with distinct perspectives deliberate on a question, see [references/roundtable-architecture.md](references/roundtable-architecture.md). Uses Den as state layer, Discord as display mirror, coordinator skill for orchestration, and Hermes profiles for persistent participant personalities.

**Multi-machine deployment:** For machine role patterns, agent user conventions, systemd templates, and backup strategies, see [references/multi-machine-deployment.md](references/multi-machine-deployment.md).

Each instance gets its own personality, skills loaded, and tool access. The coding agent doesn't need to know about your Hue lights; the ops agent doesn't need to see code diffs.

**Resource planning for fleet deployment:** Idle Hermes processes use ~80-120MB RAM (Python runtime + loaded tools/skills). No token costs while idle — LLM inference is remote. CPU negligible (event loop waiting for input). A 32GB machine can comfortably run 20-30 instances, 50+ if mostly idle. Bottleneck is RAM, not CPU. Gateway agents hold WebSocket connections (tiny overhead). See [references/roundtable-architecture.md](references/roundtable-architecture.md) for detailed capacity notes.

### Tips

- **Prefer `delegate_task` for quick subtasks** — less overhead than spawning a full process
- **Use `-w` (worktree mode)** when spawning agents that edit code — prevents git conflicts
- **Set timeouts** for one-shot mode — complex tasks can take 5-10 minutes
- **Use `hermes chat -q` for fire-and-forget** — no PTY needed
- **Use tmux for interactive sessions** — raw PTY mode has `\r` vs `\n` issues with prompt_toolkit
- **For scheduled tasks**, use the `cronjob` tool instead of spawning — handles delivery and retry

---

## Troubleshooting

### Voice not working
1. Check `stt.enabled: true` in config.yaml
2. Verify provider: `pip install faster-whisper` or set API key
3. In gateway: `/restart`. In CLI: exit and relaunch.

### Tool not available
1. `hermes tools` — check if toolset is enabled for your platform
2. Some tools need env vars (check `.env`)
3. `/reset` after enabling tools

### Model/provider issues
1. `hermes doctor` — check config and dependencies
2. `hermes login` — re-authenticate OAuth providers
3. Check `.env` has the right API key
4. **Copilot 403**: `gh auth login` tokens do NOT work for Copilot API. You must use the Copilot-specific OAuth device code flow via `hermes model` → GitHub Copilot.

### Changes not taking effect
- **Tools/skills:** `/reset` starts a new session with updated toolset
- **Config changes:** In gateway: `/restart`. In CLI: exit and relaunch.
- **Code changes:** Restart the CLI or gateway process

### TUI vs classic chat client confusion

Hermes can launch the modern Ink TUI even without an explicit `--tui` flag if the environment contains `HERMES_TUI=1`. To identify the actual client from inside a running agent, check process/env state:

```bash
env | grep -E '^(HERMES_TUI|HERMES_TUI_ACTIVE_SESSION_FILE|HERMES_GATEWAY_SESSION|TERM|SSH_TTY)='
ps -eo pid,ppid,tty,stat,etime,cmd | grep -E 'hermes|ui-tui|node|tui_gateway' | grep -v grep
```

Strong TUI indicators: `HERMES_TUI=1`, `HERMES_TUI_ACTIVE_SESSION_FILE=...`, and a process tree like `hermes -> node ui-tui/dist/entry.js -> python -m tui_gateway.entry`. `HERMES_GATEWAY_SESSION=1` may also appear in TUI sessions because the TUI uses gateway-style plumbing; it does not by itself mean Discord/web chat.

If the user expected the classic Rich/prompt-toolkit REPL but got the modern TUI, inspect shell startup files for `export HERMES_TUI=1` (on den-k8 this is currently in `/home/agent/.bashrc`). One-off classic launch:

```bash
env -u HERMES_TUI hermes -p <profile> chat
# or in the shell:
unset HERMES_TUI
hermes -p <profile> chat
```

`/skin` also differs by client: the classic REPL uses the Python skin engine directly, while the modern TUI maps resolved skin values through `ui-tui/src/theme.ts`. In the TUI, a skin change may be more constrained than in the classic client and can look like it “has no impact” if the mapped colors/branding do not affect the currently visible components.

### Skills not showing
1. `hermes skills list` — verify installed
2. `hermes skills config` — check platform enablement
3. Load explicitly: `/skill name` or `hermes -s name`

### Dashboard not starting
1. Missing deps: run `pip install 'hermes-agent[web,pty]'` (or `[all]`)
2. Frontend not built: if npm is available, it builds on first launch; otherwise install npm
3. Port in use: try `hermes dashboard --port 8080`
4. Source install with missing pip: if `venv/bin/pip` doesn't exist, bootstrap it first:
   ```bash
   venv/bin/python -m ensurepip --upgrade
   venv/bin/pip install -e '.[web,pty]'
   ```
   Some venvs (especially Python 3.11+) ship without pip pre-installed.
5. Source install: use `venv/bin/pip install -e '.[web,pty]'` from the repo dir

### Gateway issues
Check logs first:
```bash
grep -i "failed to send\|error" ~/.hermes/logs/gateway.log | tail -20
```

Common gateway problems:
- **Gateway dies on SSH logout**: Enable linger: `sudo loginctl enable-linger $USER`
- **Gateway dies on WSL2 close**: WSL2 requires `systemd=true` in `/etc/wsl.conf` for systemd services to work. Without it, gateway falls back to `nohup` (dies when session closes).
- **Gateway crash loop**: Reset the failed state: `systemctl --user reset-failed hermes-gateway`

### Platform-specific issues
- **Discord bot silent**: Must enable **Message Content Intent** in Bot → Privileged Gateway Intents.
- **Discord auto-threads when you don't want them**: Set `discord.auto_thread false` (default is `true`).
- **Discord agents can't @mention each other**: Set `discord.allow_bots mentions` (default `"none"` ignores all bot messages) and restart the target gateway. Current local Hermes builds bridge this profile config to the runtime `DISCORD_ALLOW_BOTS` policy automatically; older builds may still require `DISCORD_ALLOW_BOTS=mentions` in the service environment. If the YAML is correct but bot-authored mentions still do not wake the target, inspect `gateway/config.py` bridging and whether a systemd/env override is masking config; see `references/discord-multi-agent.md` diagnostics.
- **Discord agent wakes but doesn't know channel context**: The adapter does NOT fetch channel history — agents only see the current message + reply context. Work around by replying to the relevant message, having agents @each other with summaries, or using Den for context passing. Full details: [references/discord-multi-agent.md](references/discord-multi-agent.md).
- **Slack bot only works in DMs**: Must subscribe to `message.channels` event. Without it, the bot ignores public channels.
- **Windows HTTP 400 "No models provided"**: Config file encoding issue (BOM). Ensure `config.yaml` is saved as UTF-8 without BOM.

### Auxiliary models not working

Two distinct failure modes:

**1. `auto` can't find a backend** — auxiliary tasks fail silently. Fix: set `OPENROUTER_API_KEY` or `GOOGLE_API_KEY`, or explicitly configure each auxiliary task's provider:
```bash
hermes config set auxiliary.vision.provider <your_provider>
hermes config set auxiliary.vision.model <model_name>
```

**2. `auto` resolves provider but uses wrong base_url** — e.g. custom endpoint like `token-plan-sgp.xiaomimimo.com` but auxiliary hits `api.xiaomimimo.com`. The auto-detect inherits the provider *name* but not the custom `base_url` from the main model config. Symptoms: HTTP 401 "Invalid API Key" on title generation, compression, or vision despite the main model working fine. Check `logs/agent.log` for the actual URL being hit.

Fix: change `provider: auto` to the **named provider** AND set `base_url` on each auxiliary service:
```yaml
auxiliary:
  vision:
    provider: xiaomi          # NOT "auto" — see pitfall below
    base_url: 'https://your-actual-endpoint.com/v1'
  compression:
    provider: xiaomi
    base_url: 'https://your-actual-endpoint.com/v1'
  title_generation:
    provider: xiaomi
    base_url: 'https://your-actual-endpoint.com/v1'
```

**Critical pitfall: `provider: auto` silently drops `base_url`.** In `_resolve_task_provider_model()` (auxiliary_client.py:3322-3335), when `cfg_provider` is `"auto"` and `cfg_api_key` is empty, the configured `base_url` is discarded — the code falls through to `return "auto", ..., None, None, ...`. Then `_resolve_auto()` only passes `runtime_base_url` through when the main provider is `"custom"`, ignoring it for named providers like `"xiaomi"`. Result: the auxiliary hits the provider's default endpoint (e.g. `api.xiaomimimo.com`) instead of your custom one, and the token-plan API key gets rejected with 401.

Setting `base_url` alone with `provider: auto` is NOT sufficient — you must also change `provider` to the named provider (e.g. `xiaomi`, `openrouter`, etc.). This makes the resolution hit the `cfg_base_url and cfg_provider and cfg_provider != "auto"` branch which correctly preserves the URL.

How to verify: check `logs/agent.log` for lines like `Auxiliary compression: using xiaomi (mimo-v2.5) at https://your-endpoint/v1/` — the URL shown should be your custom endpoint, not the provider default.

---

## Where to Find Things

| Looking for... | Location |
|----------------|----------|
| Web dashboard | `hermes dashboard` or [Web Dashboard docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard) |
| Config options | `hermes config edit` or [Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) |
| Available tools | `hermes tools list` or [Tools reference](https://hermes-agent.nousresearch.com/docs/reference/tools-reference) |
| Slash commands | `/help` in session or [Slash commands reference](https://hermes-agent.nousresearch.com/docs/reference/slash-commands) |
| Skills catalog | `hermes skills browse` or [Skills catalog](https://hermes-agent.nousresearch.com/docs/reference/skills-catalog) |
| Provider setup | `hermes model` or [Providers guide](https://hermes-agent.nousresearch.com/docs/integrations/providers) |
| Platform setup | `hermes gateway setup` or [Messaging docs](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/) |
| MCP servers | `hermes mcp list` or [MCP guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp) |
| Profiles | `hermes profile list` or [Profiles docs](https://hermes-agent.nousresearch.com/docs/user-guide/profiles) |
| Cron jobs | `hermes cron list` or [Cron docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron) |
| Memory | `hermes memory status` or [Memory docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory) |
| Env variables | `hermes config env-path` or [Env vars reference](https://hermes-agent.nousresearch.com/docs/reference/environment-variables) |
| CLI commands | `hermes --help` or [CLI reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands) |
| Gateway logs | `~/.hermes/logs/gateway.log` |
| Session files | `~/.hermes/sessions/` or `hermes sessions browse` |
| Source code | `~/.hermes/hermes-agent/` |

---

## Contributor Quick Reference

For occasional contributors and PR authors. Full developer docs: https://hermes-agent.nousresearch.com/docs/developer-guide/

### Upstream vs downstream/local overlay changes

When working from a live Hermes runtime or a deployment fork, first preserve the runtime state, then split changes by ownership before preparing review or update work:

- **Generic Hermes fixes** should be PR-shaped, narrow, and free of downstream product code.
- **Deployment/product-specific behavior** (custom gateway adapters, delivery contracts, profile glue, local service integration, Den-specific status/context behavior, etc.) should live in a downstream repo, plugin, or shared overlay install path that survives `hermes update`.
- Validate from a clean or simulated-clean upstream Hermes checkout plus the downstream install path; the currently mutated runtime is not enough proof.
- Add an idempotent installer/symlink strategy for profile plugin paths instead of copying code into each profile by hand.

See [references/downstream-overlays.md](references/downstream-overlays.md) for the reusable extraction pattern and a Den Channels example.

For staged downstream memory-provider rollouts, especially Den-backed Hermes memory, use [references/den-memory-provider-rollout.md](references/den-memory-provider-rollout.md): keep provider code in a Den-owned plugin/overlay, enable only named guinea-pig profiles, set `deny_auto_behavior: true` for manual-only trials, audit worker profiles remain zero-memory, and schedule dry-run curation reports before widening access.

### Project Layout

```
hermes-agent/
├── run_agent.py          # AIAgent — core conversation loop
├── model_tools.py        # Tool discovery and dispatch
├── toolsets.py           # Toolset definitions
├── cli.py                # Interactive CLI (HermesCLI)
├── hermes_state.py       # SQLite session store
├── agent/                # Prompt builder, context compression, memory, model routing, credential pooling, skill dispatch
├── hermes_cli/           # CLI subcommands, config, setup, commands
│   ├── commands.py       # Slash command registry (CommandDef)
│   ├── config.py         # DEFAULT_CONFIG, env var definitions
│   └── main.py           # CLI entry point and argparse
├── tools/                # One file per tool
│   └── registry.py       # Central tool registry
├── gateway/              # Messaging gateway
│   └── platforms/        # Platform adapters (telegram, discord, etc.)
├── cron/                 # Job scheduler
├── tests/                # ~3000 pytest tests
└── website/              # Docusaurus docs site
```

Config: `~/.hermes/config.yaml` (settings), `~/.hermes/.env` (API keys).

### Adding a Tool (3 files)

**1. Create `tools/your_tool.py`:**
```python
import json, os
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(param: str, task_id: str = None) -> str:
    return json.dumps({"success": True, "data": "..."})

registry.register(
    name="example_tool",
    toolset="example",
    schema={"name": "example_tool", "description": "...", "parameters": {...}},
    handler=lambda args, **kw: example_tool(
        param=args.get("param", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

**2. Add to `toolsets.py`** → `_HERMES_CORE_TOOLS` list.

Auto-discovery: any `tools/*.py` file with a top-level `registry.register()` call is imported automatically — no manual list needed.

All handlers must return JSON strings. Use `get_hermes_home()` for paths, never hardcode `~/.hermes`.

### Adding a Slash Command

1. Add `CommandDef` to `COMMAND_REGISTRY` in `hermes_cli/commands.py`
2. Add handler in `cli.py` → `process_command()`
3. (Optional) Add gateway handler in `gateway/run.py`

All consumers (help text, autocomplete, Telegram menu, Slack mapping) derive from the central registry automatically.

### Agent Loop (High Level)

```
run_conversation():
  1. Build system prompt
  2. Loop while iterations < max:
     a. Call LLM (OpenAI-format messages + tool schemas)
     b. If tool_calls → dispatch each via handle_function_call() → append results → continue
     c. If text response → return
  3. Context compression triggers automatically near token limit
```

### Testing

```bash
python -m pytest tests/ -o 'addopts=' -q   # Full suite
python -m pytest tests/tools/ -q            # Specific area
```

- Tests auto-redirect `HERMES_HOME` to temp dirs — never touch real `~/.hermes/`
- Run full suite before pushing any change
- Use `-o 'addopts='` to clear any baked-in pytest flags

### Commit Conventions

```
type: concise subject line

Optional body.
```

Types: `fix:`, `feat:`, `refactor:`, `docs:`, `chore:`

### Key Rules

- **Never break prompt caching** — don't change context, tools, or system prompt mid-conversation
- **Message role alternation** — never two assistant or two user messages in a row
- Use `get_hermes_home()` from `hermes_constants` for all paths (profile-safe)
- Config values go in `config.yaml`, secrets go in `.env`
- New tools need a `check_fn` so they only appear when requirements are met
- Plugin hooks that observe gateway/tool-call activity must use task-local context (`contextvars`) or stable per-call IDs; process-global env/module state can misattribute concurrent gateway sessions. See [references/plugin-hook-concurrency.md](references/plugin-hook-concurrency.md).
