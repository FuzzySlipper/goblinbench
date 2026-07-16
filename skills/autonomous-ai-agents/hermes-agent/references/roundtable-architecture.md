# Multi-Agent Roundtable Architecture

## Overview

A deliberation system where Hermes profiles with distinct personalities discuss a
topic turn-by-turn, with Den as the coordination/state layer and Discord as a
real-time display mirror.

## Architecture

```
Discord #roundtable          Den (state layer)           Hermes agents
─────────────────────        ─────────────────           ──────────────
User @coordinator ──────►   Coordinator reads    ◄────  Coordinator skill
                             roundtable doc               loaded by any agent
                             │
Thread created ◄────────    Doc created
                             │
Each response ◄──────────   Response stored      ◄────  Participant responds
  posted in real-time        │                           (via Den dispatch)
                             │
Sanity check @user ──────►  Response count check
```

### Components

1. **Coordinator Skill** — Protocol definition: turn management, randomization,
   sanity checks, Den document structure. Loaded by any Hermes agent on demand.
2. **Den Roundtable Document** — Source of truth: conversation, participants,
   round number, responses, state. Survives coordinator crashes.
3. **Discord Thread** — Real-time mirror. Each response posted as it happens,
   not batched at end. User interacts via @mentions in thread.
4. **Participant Profiles** — Persistent Hermes profiles with distinct memory,
   personality, and expertise. Evolve across roundtables.

### Deliberation Protocol

1. User @coordinator in #roundtable with a question
2. Coordinator creates Discord thread + Den roundtable document
3. **Opening Round:** Coordinator dispatches to each participant → opening statement
4. **Deliberation Loop:**
   - Randomize participant order (excluding last respondent)
   - For each: dispatch with full context, ask "do you want to respond?"
   - If yes → response added to Den doc + mirrored to Discord thread
   - If no → skip
   - Re-randomize minus last respondent, repeat
5. **Sanity Check:** At configurable X responses, coordinator @mentions user:
   "Should this continue?"
6. **Conclusion:** User picks a winner or ends roundtable. Winning profile
   may be assigned implementation.

### Key Design Decisions

- **State in Den, not agent head** — Coordinator can crash and resume from
  Den document. Another agent can load the skill and pick up where it left off.
- **Discord is display-only** — All deliberation happens via Den dispatch.
  Discord thread is a real-time mirror for human visibility.
- **Profiles are persistent** — Each participant brings memory and evolved
  perspective across roundtables. Not fresh personas each time.
- **Turn-by-turn updates** — Responses posted to Discord as they happen.
  No big chunk update at the end.
- **Coordinator is neutral** — Can be a dedicated always-on agent or any
  agent that loads the skill on demand.

## Profile System

Each participant is a Hermes profile with:

| Layer | What it carries |
|-------|----------------|
| System prompt/personality | How they think and communicate |
| Memory | What they've learned from past roundtables |
| Skills | What they're good at (coding, architecture, security) |
| Model choice | Architect → larger reasoning model, coder → fast model |
| Tool access | Adversary → read-only, coder → full access |

### Profile Roles (examples)

- **No-nonsense coder** — Practical, implementation-focused, flags scope creep
- **System architect** — Bigger picture, willing to indulge ambitious designs
- **Adversarial reviewer** — Looks for flaws, edge cases, oversights
- **Domain specialist** — Deep knowledge in specific area

After a roundtable, the winning profile can be assigned implementation.
They carry the deliberation context into the work.

## Implementation Components

### Den MCP
- Roundtable document schema (participants, rounds, responses, state)
- Dispatch protocol for waking participants with context
- State tracking (round number, last respondent, response count)

### Hermes Skills
- **Coordinator skill** — Protocol, turn management, Den interaction,
  Discord mirroring
- **Participant skill** — Receive context, decide whether to respond,
  format response
- **Role contract templates** — Per-profile personality definitions

### Discord Integration
- Thread creation from coordinator
- Real-time response mirroring via `send_message`
- @mention protocol for sanity checks
- Thread archival on completion

## Resource Considerations

Idle Hermes processes: ~80-120MB RAM each (Python runtime + loaded tools).
No token costs while idle. CPU negligible (event loop waiting for input).

Capacity on a 32GB machine: 20-30 instances comfortably, 50+ if mostly idle.
Bottleneck is RAM, not CPU. LLM inference is remote (API calls).

## Open Questions

- Participant timeboxes (what if an agent is slow)?
- Roundtable size limits (practical max participants)?
- Participant dropouts mid-roundtable?
- Should coordinator also participate or stay neutral?
- Thread archival strategy?
- Context engine integration (protect opening statements from compression)?
