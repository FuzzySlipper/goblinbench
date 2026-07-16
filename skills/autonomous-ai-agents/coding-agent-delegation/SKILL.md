---
name: coding-agent-delegation
description: Use when delegating implementation, review, or repo work to autonomous coding CLIs such as Claude Code, Codex, or OpenCode from Hermes.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [autonomous-agents, coding-agents, claude-code, codex, opencode, delegation]
    related_skills: [subagent-driven-development, github-pr-workflow]
---

# Coding Agent Delegation

## Overview

This umbrella covers running external autonomous coding agents from Hermes: Claude Code, OpenAI Codex CLI, and OpenCode. Use it when another coding agent should inspect a repository, edit files, run tests, review a PR, or work in parallel. The Hermes agent remains the orchestrator: choose the worker, give bounded context, monitor output, verify the resulting files/tests yourself, and report only verified results.

## When to Use

- The task is coding-heavy and benefits from an autonomous CLI worker.
- You want a second implementation or review perspective.
- You need parallel exploration in isolated worktrees or temporary clones.
- The user explicitly asks for Claude Code, Codex, or OpenCode.

Do not delegate if the task is a single mechanical command, requires user interaction the worker cannot obtain, or would be faster/safer to do directly.

## Choosing a Worker

| Worker | Best fit | Typical bounded command |
| --- | --- | --- |
| Claude Code | Deep repo reasoning, long context, structured JSON/stream output, Anthropic subscription/API auth. | `claude -p 'task' --max-turns 10` |
| Codex CLI | OpenAI Codex one-shots, full-auto/yolo tasks, quick PR/issue workers. | `codex exec 'task'` |
| OpenCode | Provider-agnostic open-source coding worker, TUI or non-interactive `run`, model/provider selection. | `opencode run 'task'` |

## Universal Orchestration Pattern

1. **Preflight:** verify binary and auth (`--version`, `auth status`, `auth list`, etc.).
2. **Scope:** run in an explicit `workdir`; prefer a git worktree or temp clone for risky edits.
3. **Prompt:** include objective, constraints, files, test command, and required final report.
4. **Bound:** set max turns/timeouts; use background process tracking for long jobs.
5. **Monitor:** capture logs/output; do not assume success from the worker's prose.
6. **Verify:** inspect `git diff`, run tests/build/lint, and read back changed files.
7. **Integrate:** apply or discard changes deliberately; commit/PR only after verification.

## Claude Code Quick Reference

- Install/auth: `npm install -g @anthropic-ai/claude-code`; run `claude auth login` or set `ANTHROPIC_API_KEY`; check `claude auth status`; run `claude doctor` for health.
- Preferred one-shot: `claude -p 'Add error handling to all API calls in src/' --allowedTools 'Read,Edit' --max-turns 10`.
- JSON output: `claude -p 'Analyze auth.py' --output-format json --max-turns 5`.
- Stream JSON: `claude -p 'task' --output-format stream-json --verbose --include-partial-messages`.
- Interactive/tmux mode is for multi-turn sessions only; handle trust and permission dialogs explicitly.
- Claude Code v2 supports sessions, worktrees, MCP, slash commands, settings, hooks, and specialized agents; use those only when they materially help.

## Codex Quick Reference

- One-shot: `codex exec 'Add dark mode toggle to settings'`.
- Full-auto task: `codex exec --full-auto 'Refactor the auth module'`.
- PR review pattern: clone/check out the PR, then run `codex review --base origin/main` or `codex exec 'Review this PR vs main...'`.
- Use `pty=true` for interactive Codex behavior; use Hermes background process tracking for long tasks.
- Treat `--yolo`/full-auto modes as high-risk: isolate in a worktree/temp clone and verify before merging.

## OpenCode Quick Reference

- Install/auth: `npm i -g opencode-ai@latest` or `brew install anomalyco/tap/opencode`; run `opencode auth login`; verify `opencode auth list`.
- Binary resolution can matter; check `which -a opencode` and `opencode --version`.
- Bounded task: `opencode run 'Add retry logic to API calls and update tests'`.
- File-scoped review: `opencode run 'Review this config for security issues' -f config.yaml -f .env.example`.
- Interactive session: start `opencode` with `background=true, pty=true`, then send follow-up input via `process`.
- Resume with `opencode -c` or `opencode -s <session>`.

## PR and Parallel Work Patterns

- Use temporary clones or git worktrees for parallel workers.
- Assign non-overlapping files/tasks to avoid merge conflicts.
- Ask each worker to produce a concise final packet: files changed, tests run, open risks.
- Never tell the user a worker succeeded until you have verified diff and tests yourself.

## Common Pitfalls

1. **Letting a worker run unbounded.** Always set a turn limit, timeout, or background process lifecycle.
2. **Trusting self-reports.** Workers hallucinate success; verify with git and test output.
3. **Running in the wrong directory.** Always pass `workdir` and confirm repo state.
4. **Interactive CLIs without PTY.** Use `pty=true` when a TUI/REPL is expected.
5. **Unsafe permission bypasses.** Only use yolo/full-auto/dangerous flags inside disposable or version-controlled workspaces.

## Verification Checklist

- [ ] Worker binary and auth verified.
- [ ] Workdir isolated or known-safe.
- [ ] Prompt includes objective, constraints, and test command.
- [ ] Diff inspected after the worker exits.
- [ ] Tests/build/lint run by Hermes, not merely claimed by the worker.
- [ ] Final user summary distinguishes verified facts from worker recommendations.
