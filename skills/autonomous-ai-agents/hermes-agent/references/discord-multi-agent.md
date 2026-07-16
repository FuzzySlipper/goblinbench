# Discord Multi-Agent Configuration

## Config Keys

All settable via `hermes config set discord.KEY value` or `DISCORD_*` env vars.
Restart gateway after changes (`/restart` or `hermes gateway restart`).

| Key | Default | Purpose |
|-----|---------|---------|
| `auto_thread` | `true` | Create a thread on every @mention in channels. Set `false` for in-channel responses. |
| `require_mention` | `true` | Only respond when @mentioned (server channels). |
| `allow_bots` | `"none"` | Process messages from other bots. `"none"` = ignore all, `"mentions"` = only when @mentioned by bot, `"all"` = accept all. **Must be `"mentions"` or `"all"` for agent-to-agent @mentioning.** |
| `free_response_channels` | `""` | Comma-separated channel IDs where bot responds without @mention. |
| `no_thread_channels` | `""` (env: `DISCORD_NO_THREAD_CHANNELS`) | Channel IDs where bot responds directly without creating a thread, even if `auto_thread` is true. |
| `allowed_channels` | `""` | Whitelist — bot ONLY responds in these channels. `"*"` = all. |
| `ignored_channels` | `""` (env: `DISCORD_IGNORED_CHANNELS`) | Blacklist — bot never responds here, even when mentioned. `"*"` = ignore all. |
| `reactions` | `true` | Add emoji reactions to messages. |

### Quick Setup for Multi-Agent Discord

```bash
# Agents can @mention each other
hermes config set discord.allow_bots mentions

# Respond in-channel instead of spinning up threads
hermes config set discord.auto_thread false

# Optional: dedicated channel where bot responds without @mention
hermes config set discord.free_response_channels "CHANNEL_ID_HERE"
```

## Home Channel vs Session Channel

- **Home channel** (`/sethome`): Default delivery target for autonomous outputs — cron job results, background task completions, `send_message` with no explicit target. Think of it as a notification feed.
- **Session channel**: Where an active conversation is happening. Messages go back and forth here.

They can be different. Use home for status/reports, keep session channels clean for conversation.

## What Agents See When @Mentioned

**Agents cannot see their own Discord bot name.** There's no API endpoint for this. If users refer to the bot by its Discord display name, the agent won't know what they're talking about. Set the name explicitly in the agent's personality/system prompt, or tell it once and let it save to memory.

**Critical limitation:** The Discord adapter does NOT fetch channel history from the Discord API when an agent wakes up. An agent only receives:

1. **The current message** (the one with the @mention)
2. **The replied-to message** (if the user used Discord's reply feature — `reply_to_text`)
3. **Channel topic** (from `TextChannel.topic`)
4. **Session history from SQLite** (previous conversations with *that specific agent* in that session)

Agents do **not** see:
- Other messages in the channel before the @mention
- What other agents were discussing
- Messages from people the user didn't reply to

### Workarounds for Context Gaps

1. **Reply to the relevant message** when @mentioning an agent — it gets that one message as context
2. **Copy/paste context** into the @mention message
3. **Agents @each other** — Agent A can @ Agent B with a summary, pulling them into the conversation
4. **Use Den blackboard** — write context to Den, tell the agent to read it
5. **Future: `fetch_channel_messages` tool** — would let agents pull last N messages on demand (not yet implemented)

## Multi-Agent Filtering Logic

When a message mentions multiple bots (from `on_message` in `gateway/platforms/discord.py`):

- If **other bots** are mentioned but **not this bot** → stays silent (not for us)
- If **humans** are mentioned but **not this bot** → stays silent (respects `DISCORD_IGNORE_NO_MENTION=true`)
- If **this bot** is mentioned (with or without other bots) → processes the message

This means directed @mentions work correctly: `@AgentA @AgentB` wakes both, `@AgentA` only wakes AgentA.

### Diagnostics: bot-to-bot mentions silently ignored

If profile YAML contains `discord.allow_bots: mentions` but agents still do not wake from bot-authored mentions, verify the runtime bridge from config to env before blaming Discord:

```bash
# Check the live gateway process env for each profile.
ps -eo pid,user,etime,cmd | grep -E 'hermes.*gateway|gateway run' | grep -v grep
tr '\0' '\n' < /proc/<PID>/environ | grep -E '^(HERMES_HOME|DISCORD_ALLOW_BOTS|DISCORD_REQUIRE_MENTION|DISCORD_AUTO_THREAD|DISCORD_ALLOWED_CHANNELS|DISCORD_FREE_RESPONSE_CHANNELS)='

# Check what config loading would resolve for a profile.
HERMES_HOME=/home/agents/profiles/<profile> python - <<'PY'
import os
from gateway.config import load_gateway_config
for k in ['DISCORD_ALLOW_BOTS','DISCORD_REQUIRE_MENTION','DISCORD_AUTO_THREAD','DISCORD_ALLOWED_CHANNELS','DISCORD_FREE_RESPONSE_CHANNELS']:
    os.environ.pop(k, None)
load_gateway_config()
print({k: os.environ.get(k) for k in ['DISCORD_ALLOW_BOTS','DISCORD_REQUIRE_MENTION','DISCORD_AUTO_THREAD','DISCORD_ALLOWED_CHANNELS','DISCORD_FREE_RESPONSE_CHANNELS']})
PY
```

Known pitfall found 2026-05: Hermes had `discord.allow_bots` in `config.yaml` but `gateway/config.py` did not bridge it to `DISCORD_ALLOW_BOTS`, while `gateway/platforms/discord.py` read only the env var and defaulted to `none`. Symptom: human reply/mention wakes the target, but bot-authored direct mention does not. Fix was to bridge `discord.allow_bots` → `DISCORD_ALLOW_BOTS`, add debug logs for bot-message drops, then restart the affected gateways.

## Channel Topic as Context

The channel topic is passed to the agent as `chat_topic` in the session source. Use it to give agents persistent context about a channel's purpose:

```
/sethome  # in the channel, then edit the topic to:
This channel is for infrastructure monitoring. Agents: report status, flag anomalies.
```

## Thread Behavior Details

- `auto_thread: true` → @mention in a text channel creates a new thread; conversation continues there
- `auto_thread: false` → @mention gets an in-channel reply
- Threads the bot has already participated in are treated as free-response (no @mention needed for follow-ups)
- `no_thread_channels` overrides `auto_thread` per-channel
- `free_response_channels` also skips thread creation
- Reply-type messages (`MessageType.reply`) skip auto-threading even when `auto_thread` is true
