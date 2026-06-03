# Electron GUI Harness Suite — Design

GoblinBench's Electron GUI harness evaluates agent-facing desktop testing tooling by exercising
real or near-real Electron app flows. It combines four complementary layers:

| Layer | Scope | Platform |
|---|---|---|
| **Playwright Electron** | Renderer, WebContents, IPC, deterministic UI flows | Linux + Windows |
| **FlaUI / UIA** | Native dialogs, menus, tray, title bars, accessibility tree | Windows VM only |
| **Windows-MCP** | OS-level fallback, screenshot-and-click, broad desktop actions | Windows VM only |
| **Den Vision Analyzer** | Screenshot interpretation, recovery, state verification | Cross-platform |

The suite is designed to be layered: start with Playwright on Linux for fast iteration,
add FlaUI/Windows-MCP in a Windows VM for native coverage, and use Vision for anything
that can't be expressed deterministically.

---

## Electron Agent-Testability Contract

For Electron apps under our control (Den Desktop and future GoblinBench-tested apps),
the following contract must be honoured before the app can participate in harness evaluation.

### 1. `--test-mode` flag

When launched with `--test-mode`, the app:
- Starts in a known, clean state (no user data, no network connections, no telemetry).
- Disables animations and transitions (`prefers-reduced-motion: reduce`).
- Enables the accessibility API (`app.accessibilitySupportEnabled = true`).
- Exposes a local control socket or IPC channel for harness commands.

### 2. Deterministic profile directory

The app must accept `--user-data-dir=<path>` to use an isolated profile.
GoblinBench creates a fresh temp directory per scenario run and passes it here,
ensuring no cross-run state leaks.

### 3. Reset/seed command

The app must expose a reset mechanism reachable before or during a test:
- A CLI flag: `--seed-state=<path>` pointing to a JSON/directory of initial state.
- Or an IPC message: `{ type: "harness:reset", seed: { ... } }` that clears all
  in-memory and disk state and reapplies the seed.

### 4. Stable ARIA labels, roles, and test IDs

All interactive elements must have:
- `role` (semantic HTML or ARIA override)
- `aria-label` or `aria-labelledby` (human-readable, stable across versions)
- `data-testid` (machine-stable identifier, not used for display)

FlaUI/UIA relies on `AutomationId` or `Name`; these should map to the same stable identifiers.

### 5. Artifact output directory

The app must accept `--artifact-dir=<path>`. On teardown (or on harness request),
it writes:
- `screenshots/` — timestamped PNGs of key state transitions.
- `app-log.jsonl` — structured event log.
- `state-dump.json` — final serialised app state.

### 6. Playwright launch config

A `goblinbench-launcher.json` file in the app's root describes how to launch it:

```json
{
  "electron_path": "node_modules/.bin/electron",
  "app_entry": "dist/main.js",
  "test_mode_args": ["--test-mode", "--no-sandbox"],
  "window_size": { "width": 1280, "height": 800 },
  "ready_signal": { "type": "ipc", "channel": "harness:ready" },
  "playwright_config": "playwright.config.ts"
}
```

---

## Scenario Schema for GUI Flows

Electron GUI scenarios extend the standard GoblinBench scenario JSON with
a `gui_flow` input block describing the sequence of test steps.

```json
{
  "id": "electron.den-desktop.compose-and-send",
  "version": "1.0.0",
  "suite": "electron",
  "name": "Compose and send a channel message",
  "description": "...",
  "input": {
    "fixture": "den-desktop",
    "layers": ["playwright", "vision"],
    "seed_state": { "channels": [{ "id": "ch1", "name": "general" }] },
    "flow": [
      { "step": "launch", "profile": "clean", "window": { "width": 1280, "height": 800 } },
      { "step": "wait_ready", "selector": "[data-testid='composer-input']", "timeout_ms": 5000 },
      { "step": "screenshot", "label": "initial_state" },
      { "step": "click", "selector": "[data-testid='composer-input']" },
      { "step": "type", "selector": "[data-testid='composer-input']", "text": "hello from harness" },
      { "step": "click", "selector": "[data-testid='send-button']" },
      { "step": "wait_selector", "selector": "[data-testid='message-list'] .message:last-child", "timeout_ms": 3000 },
      { "step": "screenshot", "label": "after_send" },
      { "step": "vision_assert",
        "screenshot": "after_send",
        "prompt": "Is the message 'hello from harness' visible in the message list?",
        "expected_answer_contains": "yes" }
    ],
    "scripted_response": {
      "steps_completed": 9,
      "screenshots": ["initial_state.png", "after_send.png"],
      "vision_assertions": [{ "step": "vision_assert", "passed": true, "answer": "Yes, the message is visible." }],
      "final_state": "message_sent"
    }
  },
  "scoring": {
    "scorers": ["electron-flow", "vision-correctness", "latency"],
    "parameters": {
      "electron-flow": {
        "expected_final_state": "message_sent",
        "required_steps": ["launch", "send", "screenshot"]
      },
      "vision-correctness": {
        "expected_answer_contains": "yes"
      }
    },
    "thresholds": {
      "electron-flow": 0.8,
      "vision-correctness": 0.8
    }
  },
  "timeout_seconds": 120
}
```

### Step types

| Step | Description | Playwright | FlaUI | Windows-MCP |
|---|---|---|---|---|
| `launch` | Start the Electron app | ✓ | ✓ | ✓ |
| `wait_ready` | Wait for a selector or signal | ✓ | via AutomationId | ✓ |
| `click` | Click a UI element | ✓ | ✓ | ✓ |
| `type` | Type text into a focused element | ✓ | ✓ | ✓ |
| `screenshot` | Capture a labelled screenshot | ✓ | ✓ | ✓ |
| `wait_selector` | Wait for element to appear | ✓ | via polling | ✓ |
| `native_dialog` | Handle a save/open/alert dialog | — | ✓ | ✓ |
| `accessibility_check` | Assert ARIA tree properties | ✓ (axe) | ✓ | — |
| `vision_assert` | Vision analysis of a screenshot | via Vision | via Vision | via Vision |
| `ipc_send` | Send an IPC message to the renderer | ✓ | — | — |
| `teardown` | Close app, collect artifacts | ✓ | ✓ | ✓ |

### Artifacts

Each run produces artifacts under `runs/<run-id>/candidates/<candidate-id>/`:
- `screenshots/<label>.png` — one per `screenshot` step
- `flow-log.jsonl` — step-by-step execution log
- `accessibility-report.json` — if accessibility_check step ran
- `vision-analysis.json` — vision scorer output per `vision_assert` step
- `app-log.jsonl` — forwarded from the app's `--artifact-dir`

---

## Platform Matrix

| Feature | Linux (CI / dev) | Windows VM (gui-lab) |
|---|---|---|
| Playwright Electron renderer tests | ✓ | ✓ |
| WebContents IPC tests | ✓ | ✓ |
| Screenshot capture | ✓ | ✓ |
| Vision analysis of screenshots | ✓ | ✓ |
| Native open/save dialogs | ✗ | ✓ (FlaUI) |
| System tray / menubar | ✗ | ✓ (FlaUI) |
| Native window chrome / title bar | ✗ | ✓ (FlaUI) |
| Accessibility tree (UIA) | ✗ | ✓ (FlaUI/axe-core) |
| Broad OS desktop actions | ✗ | ✓ (Windows-MCP) |
| Screen reader compatibility | ✗ | ✓ (Windows Narrator) |

Scenarios declare which layers they require via `"layers": ["playwright", "flaui", "windows-mcp", "vision"]`.
The runner skips or stubs scenarios whose required layers are unavailable on the current host.

### Windows VM / gui-lab

The Windows VM running gui-lab needs:
- Windows 10/11 with UIAutomation enabled
- Node.js + npm (for Playwright and the fixture app)
- .NET 6+ (for FlaUI test runner)
- Windows-MCP server running locally
- GoblinBench runner with `--gui-lab` flag that enables FlaUI and Windows-MCP layers
- Den Host agent for receiving tasks and reporting results back to Den

Provisioning is deferred until the core Linux harness and the orchestrator/vision/coding
suites have validated the patterns. The gui-lab VM is not a blocking dependency.

---

## Hello Electron Fixture

A minimal Electron app in `fixtures/electron/hello-electron/` demonstrates the
testability contract on Linux using Playwright only. It is intentionally small:
a single window that accepts typed input and echoes it back.

The fixture satisfies:
- `--test-mode` (disables network, logs to `--artifact-dir`)
- `--user-data-dir=<path>` (Electron passthrough)
- `--artifact-dir=<path>` (writes screenshots and a state dump on quit)
- Stable `data-testid` and ARIA labels on all elements
- A `goblinbench-launcher.json` Playwright launch config

See `fixtures/electron/hello-electron/` for the implementation.

---

## ElectronCandidateRunner

The `ElectronCandidateRunner` (activated by `cli_command = "playwright-electron"`)
executes the `input.flow` step sequence using Playwright's Electron launch API.

Current state: **stub** — the runner is registered in the framework and runs on Linux,
executing all non-FlaUI steps. FlaUI and Windows-MCP steps are silently skipped and
recorded as `skipped` in the flow log with a platform note.

Deferred:
- `FlaUiRunner` — a .NET helper invoked as a subprocess for FlaUI/UIA steps
- `WindowsMcpRunner` — calls the Windows-MCP server for OS-level steps
- These are wired in when gui-lab VM provisioning is complete

---

## `ElectronFlowScorer`

Scores the outcome of a GUI flow run:
- Checks `final_state` matches `expected_final_state`
- Checks all `required_steps` were completed
- Scores each `vision_assert` step against the vision-correctness scorer
- Reports skipped steps (platform mismatch) as neutral (not failures)

Score weights: final_state 40%, required_steps completion 40%, skipped < 20% of steps 20%.

---

## Deferred Items

The following are explicitly out of scope until gui-lab VM is provisioned:

- FlaUI test runner (`FlaUiCandidateRunner`)
- Windows-MCP integration
- Native dialog handling
- Accessibility tree assertions via UIA
- Screen reader compatibility checks
- Multi-window and multi-process Electron test flows
- Heavy app fixtures (Den Desktop, full coding-agent harness UI)
