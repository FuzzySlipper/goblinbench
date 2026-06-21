# Tool-call behavior suite: optional-parameter stuffing and guided-error recovery

This suite targets two tool-use claims that are easy to miss in aggregate pass/fail benchmarks:

1. **Optional-parameter stuffing** — some models include every optional field in a tool call, often as `null`, `[]`, or `""`, even when the user did not supply those values.
2. **Helpful error guidance** — tool handlers that return a plain-language, use-specific suggestion for common validation errors should improve recovery compared with bare errors.

Suite id: `tool-call-behavior`

## Scenarios

- `tool-call-behavior.optional-parameter-minimalism`
  - Requires `calendar_find_slots(attendee, window)`.
  - Optional fields (`timezone`, `tags`, `include_declined`, `max_results`) should be omitted unless supplied.
  - Failure mode: `optional_parameter_stuffing` if optional values appear as `null`, empty arrays, or empty strings.

- `tool-call-behavior.null-optional-write-trap`
  - Requires `issue_create(title, priority)`.
  - Optional write-ish metadata (`labels`, `assignee`, `milestone`, `due_date`) should be omitted.
  - Designed to catch the RLHF-ish habit of serializing a whole object shape with null defaults.

- `tool-call-behavior.guided-error-recovery`
  - First fake `issue_create` result returns a validation error with `use_suggestion`.
  - The guidance explicitly says the priority enum and tells the model to omit unneeded optional fields.
  - Scorer records `guided_error_seen`, `recovered_after_error`, `repeated_invalid_call`, and `tool_error_count`.

- `tool-call-behavior.bare-error-recovery-control`
  - Same prompt/tool shape as guided recovery, but the first error is just `validation failed`.
  - Use this as the control pair to measure whether suggestions actually improve recovery.

## Scorer metrics

`McpToolUseScorer` now emits these additional detail fields when configured:

- `optional_parameter_count`
- `null_optional_parameter_count`
- `empty_optional_array_count`
- `empty_optional_string_count`
- `optional_parameter_violated`
- `optional_parameter_names`
- `tool_error_count`
- `guided_error_seen`
- `recovered_after_error`
- `repeated_invalid_call`
- `failure_categories`

Current failure categories include:

- `optional_parameter_stuffing`
- `error_recovery_failed`
- `missing_guided_error`
- `repeated_invalid_tool_call`

## Running deterministic smoke

```bash
python3 scripts/gb-run.py \
  --suite tool-call-behavior \
  --candidate fake-mcp-scripted
```

## Running local model smoke

```bash
python3 scripts/gb-run.py \
  --suite tool-call-behavior \
  --candidate qwen3-35b-local-mcp-tools
```

## Running cloud models through den-router

The den-pi extension is at:

```text
/home/dev/den-pi/extensions/den-router.ts
```

It discovers models from `DEN_ROUTER_URL` (default `http://127.0.0.1:18082`) via `/v1/models` and registers a Pi provider:

```text
provider: den-router
baseUrl: http://127.0.0.1:18082/v1
api: openai-completions
apiKey: den-router
```

GoblinBench's `OpenAiMcpToolUseRunner` can also hit the same OpenAI-compatible router directly, without spreading cloud API keys across machines. A candidate is included:

```text
--candidate den-router-deepseek-tool-behavior
```

Example:

```bash
python3 scripts/gb-run.py \
  --suite tool-call-behavior \
  --candidate den-router-deepseek-tool-behavior
```

On machines where `den-router` is not local, set up an SSH tunnel or run from the host where the router is listening. The current local probe during implementation found models from `http://127.0.0.1:18082/v1/models`, including `deepseek`, `local-coder`, and Codex/OAuth routes.

For Pi-based runs rather than direct OpenAI-compatible runs, use the den-pi extension directly:

```bash
pi --no-extensions \
  --extension /home/dev/den-pi/extensions/den-router.ts \
  --provider den-router \
  --model deepseek \
  --mode json
```

For this suite, prefer the direct GoblinBench OpenAI-compatible runner first because it preserves structured `tool_calls.json`, `chat_transcript.json`, and scorer details consistently across local and cloud models.
