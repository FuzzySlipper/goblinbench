# GoblinBench Visual-Inspect Candidate Matrix Pattern

Session-derived note for task #3425 class work: visual-inspect / chaotic screenshot description benchmarks that compare local Lemonade vision models with den-router cloud baselines.

## Candidate routing preference

Use the simplest live OpenAI-compatible endpoint that matches the model source:

- **Local Lemonade on den-nimo:** direct `base_url: "http://192.168.1.23:13305/v1"`; no API key and no den-router indirection required.
- **Cloud baselines:** local den-router `base_url: "http://127.0.0.1:18082/v1"`; no candidate-level key when the router handles upstream auth.

This matches Patch's preference: do not add local Lemonade models to den-router unless the router adds a concrete benefit such as central accounting, common aliases, or cross-provider orchestration.

## Vision candidate shape

All direct model candidates should use the existing OpenAI-compatible vision runner:

```json
{
  "id": "lemonade-qwen35-4b-q4-vision",
  "name": "Lemonade Qwen3.5 4B Q4 Vision",
  "kind": "OpenAiModel",
  "model": "Qwen3.5-4B-GGUF",
  "provider": "lemonade",
  "base_url": "http://192.168.1.23:13305/v1",
  "cli_command": "vision-openai",
  "config": {"temperature": 0.0, "max_tokens": 4096}
}
```

Cloud baseline shape:

```json
{
  "id": "den-router-kimi-code-vision",
  "name": "Den Router Kimi Code Vision",
  "kind": "OpenAiModel",
  "model": "kimi-code",
  "provider": "den-router",
  "base_url": "http://127.0.0.1:18082/v1",
  "cli_command": "vision-openai",
  "config": {"temperature": 1.0, "max_tokens": 8192}
}
```

## Starter model set used for #3425

Local Lemonade:

- `Gemma-4-26B-A4B-it-GGUF` → `lemonade-gemma4-26b-q4-vision`
- `Qwen3.5-4B-GGUF` → `lemonade-qwen35-4b-q4-vision`
- `Qwen3.6-35B-A3B-MTP-GGUF` → `lemonade-qwen36-35b-q4mtp-vision`

Cloud via den-router:

- `mimo` → `den-router-mimo-vision`, `max_tokens=8192`
- `kimi-code` → `den-router-kimi-code-vision`, `temperature=1.0`, `max_tokens=8192`
- `minimax` → `den-router-minimax-vision`, `max_tokens=8192`
- `grok` → `den-router-grok-vision`
- `stepfun` → `den-router-stepfun-vision`
- `qwenplus` → `den-router-qwenplus-vision`

## Validation sequence before image matrix

1. Validate candidate JSON:

   ```bash
   python3 -m json.tool candidates.json >/tmp/candidates.validated.json
   ```

2. Check Lemonade model IDs are present without printing secrets:

   ```bash
   python3 - <<'PY'
   import json, urllib.request
   with urllib.request.urlopen('http://192.168.1.23:13305/v1/models', timeout=10) as r:
       data=json.loads(r.read().decode())
   ids={m.get('id') for m in data.get('data', [])}
   for mid in ['Gemma-4-26B-A4B-it-GGUF','Qwen3.5-4B-GGUF','Qwen3.6-35B-A3B-MTP-GGUF']:
       print(mid, 'present' if mid in ids else 'MISSING')
   PY
   ```

3. Cheap text-only den-router smoke the cloud aliases with their real candidate temperatures. Use a temp/file or Python request body rather than inline shell JSON so quoting cannot corrupt the payload. Expect some reasoning models (`mimo`, `minimax`) to return empty/partial visible content under a tiny `max_tokens` budget; HTTP 200 proves routability, but real vision runs need larger budgets.

4. Run deterministic harness checks before model spend:

   ```bash
   python3 scripts/gb-run.py --suite vision --candidate scripted-deterministic
   python3 -m pytest tests/ -q
   ```

5. Only then launch the image matrix. Order local Lemonade candidates smallest-first to pay cold starts on cheap/fast models first.

## Interpretation gotchas

- The `vision-openai` runner sends base64 `data:image/png;base64,...` image URLs to `/chat/completions`; the endpoint must support multimodal chat-completions.
- `api_key_env` is optional. The runner adds an `Authorization` header only if a key resolves.
- `/v1/models` presence is not enough for den-router cloud aliases; do a cheap `chat/completions` smoke with the actual temperature.
- Kimi-family router aliases often require `temperature: 1.0`.
- For reasoning-heavy models, budget visible output generously (`max_tokens >= 8192` for `mimo`, `kimi-code`, `minimax` in this matrix).
