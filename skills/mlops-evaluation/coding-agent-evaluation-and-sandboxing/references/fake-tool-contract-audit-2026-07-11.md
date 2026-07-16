# Fake-tool contract audit pattern

## Trigger

Use this audit after a model looks implausibly weak, loops after a reasonable tool call, or receives a canned result only for one narrow argument representation.

## Deterministic audit

1. For each `scripted_tool_calls[]` entry, compare expected argument keys with the advertised tool JSON Schema.
2. Classify each expected-but-non-required key:
   - **safe default/presentation**: remove it from canned matching (examples: `verbose`, empty labels, default comment kind, optional tags);
   - **free-form safe effect**: define a narrow matcher such as `$any_nonempty_string`, rather than a fixed prose value;
   - **task-grounding identity**: retain deterministic matching and surface it in the scorer; do not silently accept nearby IDs/scopes.
3. Verify direct OpenAI and stdio/HTTP MCP executors share the same order: schema validation → canned-state matching → state consumption.
4. Assert an advertised but unscripted decoy returns a structured unavailable/unsupported result, never `{ok: true}`.
5. Run deterministic fixture tests, then one bounded live-model regression. Compare the model's trace and score with the previous result before calling it a model-quality delta.

## Interpretation

A model may be validly different in ordering, harmless optional fields, retry wording, or free-text internal drafts. It should not be rejected for those. Exact identity, operation, and destructive-target fields can remain strict when they are the thing being measured.

For API fields that are optional in reality but necessary for benchmark grounding (for example, project scope), keep the true schema and score/record the broader call separately rather than inventing a stricter fake API contract.
