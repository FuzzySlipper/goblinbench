# Lemonade direct-API local model comparison

Companion to `pi-lemonade-json-mode.md` (which covers pi-wrapped Lemonade
coding-agent runs). This covers using Lemonade Server's native OpenAI-compatible
API directly as GoblinBench candidates — no pi, no coding-agent wrapper, just
the `OpenAiMcpToolUseRunner` hitting Lemonade at `http://192.168.1.23:13305/v1`.

## Why direct API instead of pi

The pi coding-agent runner wraps Lemonade as a subprocess with a pi extension.
For tool-behavior suites (`den-mcp-ambiguity`, `mcp-tools`, etc.), the
`OpenAiMcpToolUseRunner` talks directly to the OpenAI-compatible endpoint.
This is simpler, faster, and supports quant-level comparisons that pi's
model.json config obscures.

## Candidate config layout for Lemonade models

```json
{
  "id": "lemonade-step37-q4-tool-behavior",
  "name": "Step 3.7 Flash Q4_K_S (local) — tool behavior",
  "kind": "OpenAiModel",
  "model": "Step-3.7-Flash-GGUF-Q4_K_S",
  "provider": "lemonade",
  "base_url": "http://192.168.1.23:13305/v1",
  "cli_command": "mcp-openai-tool-use",
  "config": {
    "runner": "mcp-openai-tool-use",
    "temperature": 0.2,
    "max_tokens": 4096,
    "max_tool_rounds": 6
  }
}
```

Notes:
- `api_key` is not required for Lemonade; omit or use a placeholder.
- The `model` field must match the exact model ID from `/v1/models`.
- `base_url` points to den-nimo (192.168.1.23:13305).
- `provider` is informational; the runner only uses `base_url`.

## Model ID and quant mapping

Lemonade exposes full checkpoint paths in `/v1/models` responses. The
`checkpoints.main` field contains the HF repo + quant tag. Key comparison
pairs available on den-nimo as of 2026-06-10:

| Model ID | Quant | Size | Base model family |
|---|---|---|---|
| `Step-3.7-Flash-GGUF-Q4_K_S` | Q4_K_S | 47.4 GB | Step 3.7 Flash |
| `NVIDIA-Nemotron-3-Super-120B-A12B-GGUF-UD-Q4_K_XL` | Q4_K_XL | — | Nemotron 3 Super 120B (MoE) |
| `Nemotron-3-Nano-30B-A3B-GGUF` | Q4_K_XL | 21.3 GB | Nemotron 3 Nano 30B (MoE) |
| `Qwen3.6-27B-GGUF` | Q8_K_XL | — | Qwen 3.6 27B |
| `builtin.Qwen3.6-27B-GGUF` | Q4_K_XL | 18.5 GB | Qwen 3.6 27B |
| `Qwen3.6-35B-A3B-GGUF` | Q8_K_XL | — | Qwen 3.6 35B MoE |
| `Qwen3.6-35B-A3B-MTP-GGUF` | Q4_K_XL | 23.8 GB | Qwen 3.6 35B MoE (MTP) |
| `GLM-4.7-Flash-GGUF` | Q8_K_XL | — | GLM 4.7 Flash |
| `builtin.GLM-4.7-Flash-GGUF` | Q4_K_XL | 16.3 GB | GLM 4.7 Flash |
| `Gemma-4-26B-A4B-it-GGUF` | Q4_K_M | 18.1 GB | Gemma 4 26B MoE |
| `gemma-4-26B-A4B-it-GGUF` | Q6_K_XL | 21.7 GB | Gemma 4 26B MoE |
| `gemma-4-31B-it-GGUF` | Q6_K_XL | — | Gemma 4 31B |
| `Qwen3.5-4B-GGUF` | Q4_K_XL | 3.3 GB | Qwen 3.5 4B |

The `builtin.*` prefix models are lower-quant versions of the same base model
that also has a higher-quant entry loaded. This gives same-model quant
comparison pairs without needing to load additional models:
- Qwen3.6-27B: Q8 (`Qwen3.6-27B-GGUF`) vs Q4 (`builtin.Qwen3.6-27B-GGUF`)
- Qwen3.6-35B: Q8 vs Q4-MTP
- GLM-4.7: Q8 vs Q4 (builtin)
- Gemma-4-26B: Q4 vs Q6

## Cold-start timing

Lemonade loads models on first request and caches them. Cold-start times
observed (2026-06-10, den-nimo Strix Halo):

| Model | Cold start | Warm response |
|---|---|---|
| Qwen3.5-4B Q4 | ~5s | <1s |
| Nemotron 3 Nano Q4 | ~15s | ~2s |
| GLM 4.7 Q4 | ~14s | ~3s |
| GLM 4.7 Q8 | ~22s | ~3s |
| Gemma 26B Q4 | ~14s | ~2s |
| Qwen3.6-27B Q4 | ~22s | ~3s |
| Qwen3.6-35B MTP Q4 | ~17s | ~2s |
| Qwen3.6-27B Q8 | ~52s | ~5s |
| Qwen3.6-35B Q8 | ~37s | ~4s |
| Nemotron 3 Super 120B Q4 | ~53s | ~5s |
| Gemma 26B Q6 | ~219s | ~5s |
| Step 3.7 Flash Q4 | ~88s | ~5s |
| Gemma 31B Q6 | ~300s+ | ~5s |

**Practical implications for matrix runs:**
- Smoke-test all models first to warm the cache before starting the actual
  matrix run. The smoke test pays the cold-start cost once.
- For a 13-model × 2-variant matrix (26 runs × 6 scenarios), expect
  2-5 hours total depending on model sizes.
- The per-scenario timeout (240s in `den-mcp-ambiguity`) is tight for
  cold starts on Gemma Q6 (219s just to load). Warm inference is well
  within the timeout.
- Order candidates smallest-first in the matrix script so early runs
  complete quickly and provide early signal.

## Smoke testing pattern

```bash
MODELS=(
  "Step-3.7-Flash-GGUF-Q4_K_S"
  "NVIDIA-Nemotron-3-Super-120B-A12B-GGUF-UD-Q4_K_XL"
  # ... etc
)

for m in "${MODELS[@]}"; do
  echo "=== $m ==="
  start=$(date +%s%N)
  curl -sS -X POST http://192.168.1.23:13305/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK\"}],\"max_tokens\":16}" \
    --max-time 300 | python3 -c "
import sys,json
raw = sys.stdin.read()
start = raw.find('{')
if start >= 0:
    d = json.loads(raw[start:])
    if 'error' in d:
        print(f'  ERROR: {d[\"error\"]}')
    else:
        c = d.get('choices',[{}])[0]
        msg = c.get('message',{})
        print(f'  OK: {repr(msg.get(\"content\",\"\")[:30])}')
" 2>&1
  end=$(date +%s%N)
  echo "  $(( (end - start) / 1000000 ))ms"
done
```

The `--max-time 300` is critical — large models can take 3-5 minutes to
load from cold. A 30s timeout will false-fail.

## Extracting quant info from /v1/models

Lemonade's model listing includes checkpoint paths that encode quant level:

```bash
curl -sS http://192.168.1.23:13305/v1/models | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
for m in d['data']:
    mid = m.get('id', '')
    ckpt = m.get('checkpoints', {}).get('main', '')
    quant = ckpt.split(':')[-1] if ':' in ckpt else ckpt
    size = m.get('size', '?')
    print(f'{mid:<45s} {quant:<30s} {size}GB')
"
```

## Known Lemonade-specific behaviors

- **Empty content on simple prompts:** Many local models return `content: ""`
  on trivial "Say OK" probes. This is normal — the model may emit only a
  tool call or reasoning, and the `max_tokens: 16` budget may be consumed by
  internal reasoning. For smoke tests, a successful HTTP 200 response is
  sufficient; content emptiness is not a failure signal.
- **Reasoning models need `max_tokens >= 4096`:** Models with reasoning
  capability (Qwen 3.5 vLLM variants, larger models) burn tokens on internal
  reasoning before producing visible output. Budget generously.
- **Tool calling works out of the box:** Lemonade's llama.cpp backend
  supports OpenAI-style `tools` and `tool_choice` parameters natively.
  Models tagged with `tool-calling` in Lemonade's labels field have been
  verified to produce valid `tool_calls` responses.
- **No rate limiting:** Single-user local inference server; concurrent
  requests queue at the model level. Running two candidates simultaneously
  against the same model will serialize, not parallelize.

## Candidate naming convention

Use a suffix pattern that encodes the quant level for easy identification:
- `lemonade-{base-model}-{quant}-tool-behavior`
- Examples: `lemonade-step37-q4-tool-behavior`, `lemonade-qwen36-27b-q8-tool-behavior`

This makes quant-comparison pairs obvious in the candidates list and report
output: `lemonade-glm47-q4-*` vs `lemonade-glm47-q8-*`.
