# Project code comparisons

These are working-code discussions for the owner's projects: native Codex for
OpenAI candidates, native DSH for other candidates, then prose review with
representative code excerpts. There are no numeric scores or leaderboard.
Start with the repository's existing guidance and ordinary C# judgment; record
additional preferences only after discussing the actual implementations.

## DSH setup

The installed runtime is `/home/system/dsh-runtime`. `/home/system/dsh` is a
different development checkout. The helper imports the Python SDK and launches
the CLI from the runtime directory, avoiding a separately installed SDK wheel.
It needs the already-installed Python `pydantic` and `PyYAML` packages.

```sh
python3 /home/dev/goblinbench/scripts/dsh-compare.py setup
python3 /home/dev/goblinbench/scripts/dsh-compare.py catalog
```

`setup` creates/refreshes `~/.dsh/profiles/comparison-sdk`. It copies the web
profile's configured provider routes, exact effort mappings, permission settings,
and relevant model/search settings, and installs the same thinking-effort plugin
version as web. Credentials stay in the existing DSH home. Run setup again after
changing web model configuration: this is an explicit snapshot, not a live link.
It leaves the web profile and runtime source unchanged.

The profile uses the full SDK plus the shipped standard preset's tooling, not
`sdk-minimal`. The current SDK does not select named web presets. The helper
therefore composes those tool rows in the SDK host scope, preserving their groups
and isolation; it translates the scope-only persona into `system-prompt` config
and omits the web-only standing child-model selector. Explicit child-model
selection/inheritance and the thinking-effort plugin remain available. It does
not copy web UI plugins or custom presets.

`catalog` boots that profile without a model call, then asks DSH to resolve each
model's effective reasoning metadata. It does not invent a universal effort
scale. The thinking-effort plugin can fill missing effort metadata in the
comparison profile during boot, just as it does in its normal host.

## Candidate runs

Give each candidate a separate worktree/branch from the chosen starting commit.
Keep the task prompt the same, but use the model's normal practical effort level.
Do not ask candidates to optimize for a scoring rubric or suggest an architecture.
The helper does not create branches or change the target checkout for you.

```sh
python3 /home/dev/goblinbench/scripts/dsh-compare.py run \
  --workspace /absolute/path/to/candidate-worktree \
  --provider zai --model glm-5.3-flash --effort max \
  --prompt-file /absolute/path/to/task.txt \
  --out /absolute/path/to/new-artifact-directory
```

Effort is mandatory: use an exact ID from `catalog`, or `default` to leave it to
the model. SDK initialization rejects unsupported efforts before sending the
task. The recorded `request/header` events show the resolved selection, including
child requests. Catalog availability does not by itself prove that a provider's
remote endpoint accepts a request; provider failures remain harness findings.

DSH's instruction plugin supplies root `AGENTS.md`/`CLAUDE.md` automatically and
discovers deeper instructions on filesystem-tool access. The helper adds only a
short reminder to follow applicable repository instructions. Use that same
reminder in Codex candidate briefs. No extra style guidelines are injected.

Outputs are `prompt.txt`, `session.json`, `events.jsonl` (including child events),
and `response.md`. Session logs also persist in the DSH home. `session.json`
records failure or completion, while the process exits nonzero for incomplete
turns. A new output directory is required to preserve earlier evidence. Supply
`--session-id` only for intentional continuation of the same candidate. The
default turn timeout is 30 minutes; `--timeout` overrides it.

For asynchronous completion, run the command in a detached worker and add
`--notify-thread <actual-Codex-task-UUID>`. The worker makes one terminal
`codex queue` call; `queue.log` records delivery output. Keep the worker on the
host and Codex configuration that own that task. Built-in Codex subagent
completion can use its native notification instead.

These prose-comparison artifacts are **not in `runs/goblinbench.sqlite`**. They
are retained directly for discussion and do not pass through GoblinBench scorers
or claim canonical benchmark ingestion.

## First task proposal

The first three-candidate run is complete. See
[the prose comparison](craftsurvive-room-variety-comparison-20260922.md), including
the ambiguity between the live terrain path and the offline catalog generator.

Use `/home/dev/rusty-craftsurvive`. At inspection, both it and `/home/dev/rusty-doom`
were clean on `main`; recheck before creating candidate worktrees. CraftSurvive's
pure C# procgen library keeps this task bounded without requiring new Engine
features or assets. Its default room catalog has one shape. Candidate-facing prompt:

> This task targets the catalog-based CraftSurvive.Procgen.Generation pipeline
> used by the offline generation tool.
>
> Give generated CraftSurvive dungeons more room-shape variety. Add a small set
> of distinct default room shapes and have generation choose among compatible
> shapes using the generation seed. Identical inputs must produce identical
> layouts; different seeds should be able to produce different room choices.
> Preserve required exits, content placement, and valid traversable generated
> layouts. Keep this within the existing procgen feature and add focused checks
> using the existing tests. Follow the repository's AGENTS.md and applicable
> nested instructions. Finish with a brief explanation of the changes and what
> you verified.

This leaves design and implementation choices to the candidate. The initial
review should discuss those choices using excerpts from the actual patches:
state and data flow, naming, readability, reuse, abstraction choices, and whether
the behavior is complete. Distinguish defects from taste; ask which tradeoffs the
owner prefers. Do not rewrite the candidate implementations before comparison.

## Setup verification (2026-09-22)

- `pytest tests/test_dsh_compare.py -q`: two tests passed, covering exact effort
  mapping preservation (notably YAML's `off` key), Cordis expressions, and SDK
  adaptation of standard tooling without importing web-only customizations.
- Catalog boot completed with all entries active. Configured efforts included
  Gemini `medium/high`, Muse `high/xhigh`, GLM `off/high/max`, and local Qwen
  `off/medium/xhigh`. Xiaomi routes exposed no explicit effort tiers at this time.
- Live `zai/glm-5.3-flash` smoke at `max` completed with a normal file read and one
  child agent. Root and child request headers both recorded `max`; both received
  the automatic repository-instructions baseline before their first request.
  Root returned the instruction marker `copper lantern` and the expected file
  text. Artifacts: `artifacts/model-comparisons/dsh-sdk-smoke/`; durable DSH
  session: `comparison-1f4af86b-b4ad-407e-beb9-d8f1b546f86b`.
- GLM at unsupported `xhigh` failed in initialization, with no model events:
  `artifacts/model-comparisons/dsh-sdk-invalid-effort/`.
- Completion queue syntax was inspected earlier; this setup did not send a
  synthetic task wakeup. The first three project candidates subsequently completed; see the report above.

## Additional inexpensive candidates

A second run uses the same base commit and task, with the explicit offline catalog
pipeline sentence above. Candidates are `xiaomi/mimo-v2.6-flash` at provider default
and `local/qwen-flash-next-pwilkin-iq4` at `xhigh`, in separate fresh worktrees.
The comparison SDK profile was refreshed from web before launch; the effective
catalog confirms those routes and Qwen's effort. Timeouts are one hour for MiMo
and two hours for local Qwen. No additional style instructions were added.

Artifacts and completion handoff:
`artifacts/model-comparisons/craftsurvive-room-variety-extra-20260922/manifest.json`.
These results remain experimental and **not in the canonical DB**. The prompt
clarification must be acknowledged when comparing with the first three runs.

For the next prose review, the owner's discussion established a preference for
explicit allocation/computation costs (verbose methods over deceptively cheap
properties), readable decomposition, and feature-specific filenames. Existing
dense code is not itself an endorsed style. LINQ is not banned. Distinguish loud,
reviewer-visible failures from subtle behavior errors; this does not excuse either.
The current task provides little evidence about unnecessary validation or schema
versioning. Independent cheap-model runs also differ from their usual role as
bounded workers under stronger orchestration; that is a useful future comparison.

Both additional candidates completed and passed independent Release procgen checks
and the singleton quota probe. The [five-model prose comparison](craftsurvive-room-variety-comparison-20260922.md) now includes their code samples and the owner's style calibration. Candidate implementations remain untouched.

## Direct higher-tier comparison

Five further direct implementations use the same base and clarified prompt revision 2:
MiMo v2.6 Pro at default, Muse Spark 1.3 Contributor at xhigh, Gemini 3.8 Flash
at high (all DSH), GPT-6 Sol at high and GPT-6 Astra at low (native Codex
subagents). The owner explicitly confirmed low as the intended Astra setting.
The SDK profile was refreshed from web and the DSH catalog verified before launch.
Each candidate has a fresh worktree, no prior patches or review feedback, and
applicable repository/Den guidance. DSH runs have one-hour turn timeouts.

Launch and completion evidence lives in
`artifacts/model-comparisons/craftsurvive-room-variety-direct-20260922/manifest.json`.
Review is pending. These experimental artifacts are **not in the canonical DB**.
This batch is direct implementation; a comparison under stronger orchestration
remains a subsequent experiment.

All five direct higher-tier candidates completed. Independent procgen checks passed;
MiMo Pro reproduced the singleton quota regression. See the [direct comparison and ten-model synthesis](craftsurvive-room-variety-direct-comparison-20260922.md). No orchestrated runs have been started.

## Additional local dense Qwen run

`local-patch/Qwen3.8-27B-GGUF` at `xhigh` was launched directly in DSH on
2026-09-23 using the same base commit and clarified prompt revision 2. The SDK
profile was refreshed from web and the effective catalog verified. A fresh
worktree isolates the implementation; the timeout is two hours, matching the
earlier local Qwen run. Completion queues review back to this task, emphasizing
the comparison with `local/qwen-flash-next-pwilkin-iq4` at `xhigh`.

Artifacts: `artifacts/model-comparisons/craftsurvive-room-variety-qwen27-20260923/`.
Review is pending; these artifacts are **not in the canonical DB**.

The eleventh direct candidate, local Qwen 27B at xhigh, completed and passed independent procgen and singleton quota checks. See the [comparison with the earlier local Qwen](craftsurvive-room-variety-qwen27-comparison-20260923.md).

## First orchestrated run

GPT-6 Sol at medium now orchestrates fresh GPT-6 Luna max worker sessions through
nested native Codex subagents. The feature prompt remains revision 2 and the base
commit is unchanged. Sol chooses delegation and review/correction steps; Luna
implements, with any direct Sol integration edits recorded separately. The first
worker handoff is snapshotted before corrections, alongside a concise orchestration
log, to distinguish worker output from the final result. Neither receives prior
candidate code or review findings.

Artifacts: `artifacts/model-comparisons/craftsurvive-room-variety-sol-luna-20260923/`.
Review is pending. These are experimental artifacts, **not canonical DB results**.
Comparison limits: standalone Sol used high effort, this orchestrator uses medium;
standalone Luna received the earlier ambiguous feature prompt.

The first orchestrated run completed: Sol approved Luna's first patch unchanged.
Independent procgen checks passed, but the singleton quota probe reproduced a regression.
See the [orchestration comparison](craftsurvive-room-variety-sol-luna-comparison-20260923.md).
