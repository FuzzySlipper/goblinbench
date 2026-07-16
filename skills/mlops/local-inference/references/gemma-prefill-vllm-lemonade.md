# Gemma long-prompt prefill comparison on den-nimo

Use this when comparing standalone vLLM vs Lemonade/llama.cpp on non-tiny models and long prompts. It captures durable methodology and gotchas from a Gemma 4 26B/31B prefill session.

## Benchmark shape

Goal: isolate prompt prefill behavior from model loading, startup, and prefix-cache artifacts.

Recommended sequence per backend/model:

1. Free the other backend before loading a large model.
   - Lemonade unload: `POST http://HOST:13305/api/v0/unload` with `{}`.
   - For strongest isolation, also stop the unused service (`systemctl stop lemond.service` before standalone vLLM runs; `systemctl stop vllm-json-probe.service` before Lemonade runs).
2. Load the model and wait for `/v1/models` or `/api/v0/health` readiness.
3. Send a tiny ACK warmup (`SEND ACK IF RECEIVED`) to separate model-load latency from the measured prompt ladder.
4. Run the actual prompt ladder with unique prompt seeds per size/repeat so larger prompts do not share identical prefixes with smaller prompts.
5. Record both endpoint-reported `usage.prompt_tokens` and the nominal target size. Plot against reported prompt tokens, not target tokens.
6. After the model run, unload/stop before switching model/backend.

## Scripts used in GoblinBench

In `/home/dev/goblinbench`:

- `scripts/local_prefill_latency_probe.py` — sends deterministic long prompts with tiny outputs; records first streamed event, TTFT when OpenAI-style content deltas exist, total latency, reported prompt tokens, cached token details, and errors.
- `scripts/local_prefill_gemma_matrix.py` — orchestrates Gemma 4 26B/31B across standalone vLLM and Lemonade, with ACK warmup and unload/stop isolation.

## Lemonade control surface

Observed on Lemonade 10.8.1:

```bash
curl -X POST -H 'Content-Type: application/json' --data '{}' \
  http://127.0.0.1:13305/api/v0/unload
```

Response:

```json
{"message":"All models unloaded successfully","status":"success"}
```

Equivalent POSTs also worked at `/api/v1/unload` and `/v1/unload`, but prefer `/api/v0/unload` because it matches the health/models namespace observed on den-nimo.

Lemonade health endpoints that expose loaded-model state:

- `/api/v0/health`
- `/v1/health`

## Prefix-cache gotchas

- vLLM and llama.cpp/Lemonade can make repeated long-prompt tests look much faster through prefix caching.
- Do not run a size ladder where 512, 2048, and 4096 all share the exact same prefix unless cache behavior is the thing being tested.
- Include size and repeat in the prompt seed. The GoblinBench prefill probe does this by deriving prompt seed from `seed + repeat*1009 + size*1000003`.
- Lemonade llama.cpp may return `usage.prompt_tokens_details.cached_tokens`; report it beside latency.
- Lemonade streaming may not expose OpenAI-style `choices[].delta.content`; in that case use first SSE event, total latency, and cached-token details rather than claiming TTFT.

## vLLM Strix Halo config notes

For Gemma 4 text-only vLLM runs on den-nimo:

- force text-only multimodal limits: `--limit-mm-per-prompt '{"image":0,"video":0,"audio":0}'`
- use `--enforce-eager` on gfx1151
- set explicit `--max-model-len`, `--max-num-seqs`, `--max-num-batched-tokens`, and `--kv-cache-memory-bytes`
- for dense 31B fp16, add CPU offload (`--cpu-offload-gb 24` was enough to start loading on den-nimo)

The standalone service wrapper was extended to honor `VLLM_CPU_OFFLOAD_GB` and append `--cpu-offload-gb` when set.

## Partial observed results

Standalone vLLM Gemma 4 26B-A4B, `max_model_len=8192`, `max_num_seqs=2`, `max_num_batched_tokens=8192`, `kv_cache_memory_bytes=8G`:

| target prompt toks | reported prompt toks median | first event / TTFT p50 | total p50 | note |
|---:|---:|---:|---:|---|
| 512 | 1238.5 | 0.797s | 2.111s | transport OK |
| 2048 | 4739.5 | 2.466s | 3.859s | transport OK |
| 4096 | — | — | — | HTTP 400; actual prompt + output exceeded 8192 context |

Takeaway: nominal prompt targets can drastically undershoot real tokenizer/chat-template usage. A `4096` synthetic target can exceed an `8192` serving context for Gemma 4 with verbose filler and 64 output tokens.

Standalone vLLM Gemma 4 31B-it began loading with `--cpu-offload-gb 24`; logs showed `Offloader set to UVAOffloader` and `Total CPU offloaded parameters: 24.36`. Treat 31B dense fp16 as CPU-offload territory on den-nimo unless TTM/GPU memory is expanded or a quantized build is used.

## Reporting discipline

Separate these in reports:

- model-load/ready latency
- ACK warmup latency
- real prompt prefill latency
- cached vs uncached prompt behavior
- context-window failures
- service/backend failures

Do not collapse them into a single “model is slow/fast” statement.
