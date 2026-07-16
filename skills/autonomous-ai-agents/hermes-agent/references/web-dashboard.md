# Web Dashboard — Full Reference

Browser-based UI for managing Hermes Agent. Runs entirely on localhost — no data leaves your machine.

## Prerequisites

The default install does not ship the HTTP stack or PTY helper. You need:

- **FastAPI + Uvicorn** (the `web` extra) — web server backend
- **ptyprocess** (the `pty` extra) — for the in-browser Chat tab
- **Node.js** — for building the frontend (auto-builds on first launch if npm is available)

```bash
pip install 'hermes-agent[web,pty]'    # minimal
pip install hermes-agent[all]          # everything including messaging/voice
```

For source installs (git clone):
```bash
cd ~/.hermes/hermes-agent
venv/bin/pip install -e '.[web,pty]'
```

The venv is typically at `~/.hermes/hermes-agent/venv/` (not `.venv`).

## Quick Start

```bash
hermes dashboard                    # starts on http://127.0.0.1:9119, opens browser
hermes dashboard --no-open          # don't auto-open
hermes dashboard --tui              # enable Chat tab (PTY/WebSocket)
hermes dashboard --port 8080        # custom port
hermes dashboard --host 0.0.0.0     # bind all interfaces (DANGEROUS)
```

## Pages

### Status
Landing page with live overview:
- Agent version and release date
- Gateway status (running/stopped, PID, connected platforms)
- Active sessions (count from last 5 minutes)
- Recent sessions (20 most recent with model, message count, tokens, preview)
- Auto-refreshes every 5 seconds

### Chat
Embedded Hermes TUI in the browser (same as `hermes --tui`).
- Works via PTY/WebSocket: keystrokes → PTY, ANSI output → xterm.js WebGL renderer
- Supports slash commands, model picker, tool-call cards, markdown streaming
- Resume sessions: click play icon (▶) from Sessions tab → `/chat?resume=<id>`
- Requires: Node.js, ptyprocess, POSIX kernel (Linux/macOS/WSL; not native Windows)

### Config
Form-based editor for `config.yaml`. Auto-discovers all 150+ fields from DEFAULT_CONFIG.
- Tabbed categories: model, terminal, display, agent, delegation, memory, approvals, etc.
- Dropdowns for known values, toggles for booleans, text inputs for everything else
- Actions: Save, Reset to defaults, Export (JSON), Import (JSON)
- Changes take effect on next session or gateway restart

### API Keys
Manage `.env` file. Keys grouped by:
- LLM Providers (OpenRouter, Anthropic, OpenAI, DeepSeek, etc.)
- Tool API Keys (Browserbase, Firecrawl, Tavily, ElevenLabs, etc.)
- Messaging Platforms (Telegram, Discord, Slack bot tokens, etc.)
- Agent Settings (non-secret env vars)

Each key shows: set/unset status, redacted preview, description, provider link, input field, delete button.

### Sessions
Browse and inspect all sessions. Features:
- Full-text search (FTS5) across message content with highlighted snippets
- Expand to load full message history (color-coded by role, markdown rendered)
- Tool calls shown as collapsible blocks with function name + JSON args
- Delete sessions with trash icon

### Logs
View agent, gateway, and error log files.
- Filter by: file (agent/errors/gateway), level (ALL/DEBUG/INFO/WARNING/ERROR), component
- Live tailing (polls every 5 seconds)
- Color-coded by severity

### Analytics
Usage and cost analytics from session history.
- Period selection: 7, 30, or 90 days
- Summary cards: total tokens, cache hit %, cost, session count
- Daily token chart (stacked bar)
- Daily breakdown table
- Per-model breakdown

### Cron
Create and manage scheduled jobs.
- Fields: name, prompt, cron expression, delivery target (local/Telegram/Discord/Slack/email)
- Actions: pause/resume, trigger now, delete

### Skills
Browse, search, and toggle skills and toolsets.
- Search by name/description/category
- Category filter pills
- Enable/disable switches (takes effect next session)
- Separate toolsets section with status and included tools list

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 9119 | Port to run the web server on |
| `--host` | 127.0.0.1 | Bind address |
| `--no-open` | — | Don't auto-open the browser |
| `--insecure` | off | Allow binding to non-localhost hosts (DANGEROUS) |
| `--tui` | off | Enable Chat tab (PTY/WebSocket). Also: `HERMES_DASHBOARD_TUI=1` |

## REST API

The dashboard exposes these endpoints (used by frontend, also callable directly):

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Agent version, gateway status, platform states |
| `/api/sessions` | GET | 20 most recent sessions |
| `/api/sessions/{id}` | GET | Single session metadata |
| `/api/sessions/{id}/messages` | GET | Full message history |
| `/api/sessions/search?q=` | GET | Full-text search |
| `/api/sessions/{id}` | DELETE | Delete session |
| `/api/config` | GET/PUT | Read/write config.yaml |
| `/api/config/defaults` | GET | Default config values |
| `/api/config/schema` | GET | Field schema (types, descriptions, options) |
| `/api/env` | GET/PUT/DELETE | Manage .env variables |
| `/api/logs` | GET | Log lines (params: file, lines, level, component) |
| `/api/analytics/usage?days=` | GET | Token usage, cost, session analytics |
| `/api/cron/jobs` | GET/POST | List/create cron jobs |
| `/api/cron/jobs/{id}/pause` | POST | Pause job |
| `/api/cron/jobs/{id}/resume` | POST | Resume job |
| `/api/cron/jobs/{id}/trigger` | POST | Trigger job now |
| `/api/cron/jobs/{id}` | DELETE | Delete job |
| `/api/skills` | GET | List skills with status |
| `/api/skills/toggle` | PUT | Enable/disable skill |
| `/api/tools/toolsets` | GET | List toolsets with status |

CORS restricted to localhost origins (9119, 3000, 5173 + custom port).

## Themes

Six built-in themes, switchable from header bar palette icon. Persists to `dashboard.theme` in config.yaml.

| Theme | Character |
|-------|-----------|
| Hermes Teal (default) | Dark teal + cream, system fonts |
| Midnight | Deep blue-violet, Inter + JetBrains Mono |
| Ember | Warm crimson + bronze, Spectral serif + IBM Plex Mono |
| Mono | Grayscale, IBM Plex, compact |
| Cyberpunk | Neon green on black, Share Tech Mono |
| Rosé | Pink + ivory, Fraunces serif |

Custom themes and plugins: see [Extending the Dashboard](https://hermes-agent.nousresearch.com/docs/user-guide/features/extending-dashboard)

## Security Notes

- Binds to 127.0.0.1 by default — localhost only
- No built-in authentication
- Reads/writes `.env` file (contains API keys)
- `--insecure` + `--host 0.0.0.0` exposes keys on network — pair with firewall + auth
- `/reload` slash command re-reads `.env` without restart

## Development

```bash
# Terminal 1: backend API
hermes dashboard --no-open

# Terminal 2: Vite dev server with HMR
cd web/ && npm install && npm run dev
# Vite at :5173 proxies /api to FastAPI at :9119
```

Frontend stack: React 19, TypeScript, Tailwind CSS v4, shadcn/ui-style components.
Production builds output to `hermes_cli/web_dist/`.
