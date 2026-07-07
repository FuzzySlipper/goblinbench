# Local vLLM / Lemonade JSON Concurrency Probe — 2026-06-29

## Goal

Design the first small test environment for using den-nimo local hardware as a high-concurrency agent/model backend. The initial probe focuses on programmatic framework fit rather than benchmark difficulty:

- Can the model return parseable JSON under concurrent calls?
- Does it satisfy a strict response contract?
- Does concurrency cause transport failures, truncation, or random malformed output?
- Separately: does it solve small fuzzy constraint scenarios correctly?

## Host / service state

- Host: `den-nimo` / `192.168.1.23`
- SSH as `agent` works.
- `agent` is in `video`, `render`, and `wheel` groups.
- `sudo -n true` now works for `agent` after sudoers was broadened.
- Lemonade service: `lemond.service`
- Lemonade API: `http://192.168.1.23:13305/v1`
- Lemonade after restart reports `10.8.1`.
- Global standalone vLLM exists: `/usr/local/bin/vllm`, version `0.21.0+rocm722`.
- Direct vLLM import requires `LD_LIBRARY_PATH=/opt/vllm/lib:$LD_LIBRARY_PATH` for `libmpi_cxx.so.40`.

## Probe script

Added:

```text
scripts/local_json_concurrency_probe.py
```

It sends concurrent OpenAI-compatible chat requests and records:

- HTTP/transport success
- JSON parse success
- strict contract success (`contract_ok`)
- fuzzy decision correctness (`decision_ok`)
- latency and finish reason
- raw content and parsed packet per request

Artifacts are written to:

```text
runs/local-json-concurrency/<timestamp>/
```

The prompt asks for a compact JSON packet:

```json
{
  "scenario_id": "...",
  "decision": "...",
  "action": "...",
  "confidence": 0.0,
  "constraint_summary": ["..."],
  "ignored_noise": ["..."],
  "valid_json_self_check": true
}
```

## Initial runs

| run | model | requests | concurrency | all ok | contract ok | decision ok | HTTP err | JSON invalid | format invalid | decision invalid | p50 s | max s | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `20260630T000720Z` | `Qwen3.5-0.8B-vLLM` | 4 | 2 | 2 | n/a* | n/a* | 0 | 0 | n/a* | n/a* | 82.626 | 164.048 | first cold-load pilot before metric split |
| `20260630T001148Z` | `Qwen3.5-0.8B-vLLM` | 16 | 8 | 4 | 6 | 5 | 0 | 0 | 10 | 11 | 1.756 | 2.736 | warmed concurrency pass; stable transport, weak contract/logic |
| `20260630T001218Z` | `Qwen3.5-2B-vLLM` | 8 | 4 | 4 | 7 | 4 | 0 | 0 | 1 | 4 | 111.393 | 220.488 | cold-load dominated first wave; warmed calls ~3s |
| `20260630T003655Z` | `Qwen3.5-0.8B-FP16-vLLM` | 4 | 2 | 2 | 3 | 2 | 0 | 0 | 1 | 2 | 28.299 | 55.691 | post-lemond-restart ID shape |

\*The first pilot used an older summary shape where schema and decision failures were not separated.

Key observation: even small vLLM models emitted parseable JSON reliably in these probes (`json_invalid = 0`), but weaker models often missed one required field or solved the fuzzy constraint incorrectly. That is exactly why the probe separates `contract_ok` from `decision_ok`.

## vLLM / Lemonade behavior observed

### Lemonade-managed vLLM

- Lemonade auto-loads vLLM recipe models and exposes them through the same `:13305/v1` endpoint.
- Cold-load/startup dominates early concurrent requests:
  - 0.8B first pilot: ~163s first wave before restart.
  - 2B first wave: ~220s.
  - 0.8B after Lemonade restart/version bump: ~55s.
- Warmed requests were fast enough for iterative probe work:
  - 0.8B warmed: ~1–3s in this prompt shape.
  - 2B warmed: ~2.7–3.2s.

### 4B Lemonade-managed vLLM caveat

Attempting `Qwen3.5-4B-vLLM` before the Lemonade restart exceeded the 10-minute foreground cap and left Lemonade-spawned vLLM children that were not registered as loaded. Lemonade health intermittently timed out and reported no loaded model. A constrained `sudo -n systemctl restart lemond` cleaned it up.

Likely contributing factor: Lemonade’s vLLM recipe used `--max-model-len 200000` and `--kv-cache-memory-bytes 4G`, which is a poor default for fast stress testing.

### Standalone vLLM caveat

A reversible standalone test was attempted with:

```bash
HF_HOME=/home/llm \
LD_LIBRARY_PATH=/opt/vllm/lib:$LD_LIBRARY_PATH \
HSA_OVERRIDE_GFX_VERSION=11.0.0 \
/usr/local/bin/vllm serve Qwen/Qwen3.5-0.8B \
  --served-model-name qwen35-08b-standalone \
  --host 0.0.0.0 --port 8000 \
  --dtype half --enforce-eager \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.5 \
  --enable-prefix-caching
```

The model loaded but did not open the port after several minutes, spending time in ROCm/Triton compile/profiling. The agent-owned process ignored normal TERM and required `kill -9` cleanup. Do not promote this exact command to a service without further tuning.

## Current recommendation

Use three lanes:

1. **Lemonade quick lane** — model discovery, smoke tests, and small matrices. Accept cold-load cost. Run one model at a time because Lemonade has one LLM slot.
2. **Standalone vLLM service lane** — for real high-concurrency agent stress, create a supervised service with a fixed model, sane `--max-model-len` (4k/8k/16k), warmed kernel/cache, `LD_LIBRARY_PATH=/opt/vllm/lib`, and explicit cleanup/restart policy. Do not rely on Lemonade’s 200k-context vLLM recipe for this.
3. **GoblinBench probe lane** — keep expanding `scripts/local_json_concurrency_probe.py` into a repeatable matrix harness with warmup, concurrency sweep, and flat reports.

## Next concrete steps

1. Add warmup mode to the probe so cold-load is measured separately from steady-state concurrency.
2. Add concurrency sweep mode: e.g. 1, 2, 4, 8, 16, 32, 64 concurrent requests against a fixed warmed model.
3. Try larger known text-only standalone models next, using `/usr/local/sbin/vllm-json-probe-set-model`.
4. Treat `Qwen/Qwen3.5-*` standalone attempts as suspicious until the model architecture/MM behavior is verified; the current vLLM 0.21.0 path hit Qwen3-VL MM encoder OOM.
5. Retest larger Qwen/Gemma/MiniMax style models via standalone vLLM only after confirming text-only architecture and sane context/cache flags.


## Update — standalone vLLM service installed

After sudoers was broadened, installed and enabled a standalone vLLM lane on den-nimo:

- Unit: `vllm-json-probe.service`
- Endpoint: `http://192.168.1.23:8000/v1`
- Default model: `Qwen/Qwen2.5-0.5B-Instruct`
- Served name: `qwen25-05b-standalone`
- Env/config: `/etc/vllm-json-probe.env`
- Wrapper: `/usr/local/bin/vllm-json-probe-serve`
- Model switch helper: `/usr/local/sbin/vllm-json-probe-set-model HF_MODEL_ID [SERVED_MODEL_NAME]`
- Runtime/cache/temp roots are pinned under `/home/llm/vllm-runtime` / `/home/llm` to avoid filling `/`.

Current service flags:

```text
--dtype half
--enforce-eager
--max-model-len 4096
--gpu-memory-utilization 0.50
--max-num-seqs 32
--max-num-batched-tokens 4096
--kv-cache-memory-bytes 4G
```

Verification:

- `/v1/models` returns `qwen25-05b-standalone` with `max_model_len: 4096`.
- Direct chat completion returned valid JSON.
- GoblinBench probe artifact: `runs/local-json-concurrency/20260630T013944Z` — 16 requests / concurrency 8: 16/16 contract-valid, 0 JSON invalid, 0 transport errors.
- Larger smoke artifact: `runs/local-json-concurrency/20260630T014045Z` — 64 requests / concurrency 32: 64/64 contract-valid, 0 JSON invalid, 0 transport errors, p50 1.232s, max 1.462s. Decision quality was poor as expected for a 0.5B model: 16/64 decision-correct.

Important gotcha:

- Standalone `Qwen/Qwen3.5-*` attempts were treated by vLLM 0.21.0 as Qwen3-VL / multimodal models and failed during MM encoder profiling with a 192 GiB HIP allocation. Adding `--kv-cache-memory-bytes 4G` did not fix it. Use known text-only models first and verify model architecture before larger Qwen3.5 tests.


## Update — Gemma 4 standalone vLLM smoke (2026-06-30)

Added HF token to `/etc/vllm-json-probe.env` (file mode `0600 root:root`) and added explicit vLLM service knobs:

```text
VLLM_DOWNLOAD_DIR=/home/llm
VLLM_LIMIT_MM_PER_PROMPT={"image":0,"video":0,"audio":0}
```

The wrapper now passes:

```text
--download-dir /home/llm
--limit-mm-per-prompt '{"image":0,"video":0,"audio":0}'
```

This caused vLLM to log `All limits of multimodal modalities supported by the model are set to 0, running in text-only mode`, avoiding unnecessary multimodal work for JSON/text probes.

### Gemma 4 results

| model | served name | requests | concurrency | contract ok | decision ok | JSON invalid | transport errors | p50 s | max s | artifact |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `google/gemma-4-E2B-it` | `gemma4-e2b-it` | 32 | 16 | 24/32 | 24/32 | 0 | 0 | 9.474 | 16.133 | `runs/local-json-concurrency/20260630T100742Z` |
| `google/gemma-4-E4B-it` | `gemma4-e4b-it` | 32 | 16 | 24/32 | 16/32 | 0 | 0 | 10.939 | 14.842 | `runs/local-json-concurrency/20260630T101108Z` |
| `google/gemma-4-26B-A4B-it` | `gemma4-26b-a4b-it` | 16 | 4 | 16/16 | 12/16 | 0 | 0 | 10.948 | 16.391 | `runs/local-json-concurrency/20260630T102030Z` |

Load/startup notes:

- `google/gemma-4-E2B-it` loaded successfully in text-only mode; first startup including download/compile was roughly 110 seconds.
- `google/gemma-4-E4B-it` loaded successfully in text-only mode; first startup was roughly 140 seconds.
- `google/gemma-4-26B-A4B-it` loaded successfully in text-only mode. It downloaded ~48.07 GiB of weights in ~386.6 seconds and became API-ready around 8.3 minutes after service restart.
- 26B-A4B logged `Using TRITON Unquantized MoE backend`; it fit with current conservative flags but consumed ~50 GiB process memory during/after load.

Interpretation:

- All three Gemma 4 models were clean at the transport/JSON parse layer: no HTTP errors, no transport errors, no invalid JSON.
- E2B/E4B had a repeatable schema quirk on `deployment_gate`: they often chose the right decision concept but returned a non-exact `action` value, causing `wrong_action` format failures.
- 26B-A4B was the cleanest contract follower in this small sample (16/16 contract-valid) and best on the simple decision metric (12/16), but startup cost and memory footprint are high for many-agent stress.
- The current probe’s bridge-box scenario may be too brittle/ambiguous as a model-quality discriminator; all Gemma sizes missed it frequently enough that it should be reviewed before overinterpreting decision accuracy.


## Update — additional local vLLM candidate sweep (2026-06-30)

Added reusable sweep helper:

```text
scripts/local_vllm_candidate_sweep.py
```

Sweep artifact:

```text
runs/local-json-concurrency/candidate-sweep-20260630T124708Z/
```

Probe shape for successful candidates: 16 requests, concurrency 4, max output 512 tokens, standalone vLLM at `http://192.168.1.23:8000/v1` with the existing conservative flags (`max_model_len=4096`, text-only multimodal limits, `enforce_eager`).

| model | served name | status | contract ok | decision ok | JSON invalid | transport errors | p50 s | max s | artifact |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| `ibm-granite/granite-4.1-8b` | `granite-41-8b` | loaded + probed | 16/16 | 12/16 | 0 | 0 | 7.582 | 12.441 | `runs/local-json-concurrency/20260630T125017Z` |
| `LiquidAI/LFM2.5-8B-A1B` | `lfm25-8b-a1b` | loaded + probed | 14/16 | 8/16 | 0 | 0 | 5.293 | 9.255 | `runs/local-json-concurrency/20260630T125339Z` |
| `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` | `nemotron3-nano-4b-bf16` | loaded + probed | 16/16 | 12/16 | 0 | 0 | 3.507 | 39.947 | `runs/local-json-concurrency/20260630T125551Z` |
| `google/gemma-4-12B-it` | `gemma4-12b-it` | failed before load | — | — | — | — | — | — | — |
| `Qwen/Qwen3.5-4B` | `qwen35-4b` | failed/hung before API ready | — | — | — | — | — | — | — |

Findings:

- **Granite 4.1 8B** looks like the strongest practical candidate in this mini-sweep: clean JSON/contract (16/16), good simple decision score (12/16), and moderate p50 latency (~7.6s at concurrency 4). The main repo `ibm-granite/granite-4.1-8b` appears to be the instruct/tool-calling line; `ibm-granite/granite-4.1-8b-base` exists separately.
- **Nemotron 3 Nano 4B BF16** loaded successfully on AMD/ROCm despite NVIDIA branding and had the best p50 latency (~3.5s) with clean contract (16/16) and 12/16 decision score. One request tail was slow (`max=39.947s`), likely first-wave/kernel/prefix effects; worth retesting warmed or at higher concurrency.
- **LFM2.5 8B-A1B** loaded successfully and was reasonably fast (p50 ~5.3s), but weaker on this JSON contract/decision probe: 14/16 contract, 8/16 decision. It logs as a MoE path (`TRITON Unquantized MoE backend`).
- **Gemma 4 12B** did not load with the current vLLM/Transformers stack. Error: `model type gemma4_unified` not recognized by Transformers. The inspected 12B variants (`google/gemma-4-12B-it`, `google/gemma-4-12B-it-qat-w4a16-ct`, `google/gemma-4-12B`) all use `gemma4_unified`, so this likely requires updating the bundled vLLM/Transformers stack rather than just switching variants.
- **Qwen3.5 4B** initially failed due to a stale Lemonade-owned cache path (`/home/llm/models--Qwen--Qwen3.5-4B` owned by `lemonade:lemonade`). Fixed with recursive `chown -R agent:agent /home/llm`. After retry, it loaded weights (`Checkpoint size: 8.68 GiB`, `Loading weights took 10.77 seconds`, `Model loading took 7.99 GiB`) and text-only mode was applied, but the OpenAI API never opened within >10 minutes. Logs show it still initializes Qwen VL/MM components and GDN/mamba-ish Triton kernels (`Qwen2VLImageProcessor`, `Using Torch SDPA backend for ViT model`, `Using Triton/FLA GDN prefill kernel`). Treat Qwen3.5 4B as not currently usable on this standalone lane without deeper vLLM/kernel tuning.

After the Qwen retry, restored the standalone endpoint to the known-good Granite model:

```text
model: ibm-granite/granite-4.1-8b
served: granite-41-8b
endpoint: http://192.168.1.23:8000/v1
```


## Update — long prompt prefill probe (2026-07-05)

Added standalone prefill-specific probe:

```text
scripts/local_prefill_latency_probe.py
```

Purpose: compare local OpenAI-compatible endpoints (standalone vLLM, Lemonade vLLM recipes, Lemonade llama.cpp/GGUF recipes) on long-prompt actual usage rather than short JSON/concurrency tasks.

Signals recorded per request:

- `ttft_s` for streaming endpoints that emit OpenAI-style `choices[].delta.content` chunks. This is the closest simple proxy for scheduler + prefill latency when output is tiny.
- `total_latency_s` for all requests.
- endpoint-reported `usage.prompt_tokens` when available.
- HTTP/transport errors, raw error bodies, and tiny JSON response success.

The prompt generator intentionally creates deterministic structured filler and asks for a tiny JSON object so decode time stays small and latency is dominated by prefill.

### Smoke results

Standalone vLLM current model:

```text
base_url: http://192.168.1.23:8000/v1
model: granite-41-8b
artifact: runs/local-prefill-latency/20260705T071322Z-standalone-vllm-granite-prefill-smoke
```

| target prompt toks | reported prompt toks | result | TTFT s | total s | note |
|---:|---:|---|---:|---:|---|
| 512 | 945 | OK | 0.099 | 2.315 | JSON valid |
| 2048 | 3574 | OK | 0.295 | 2.582 | JSON valid |
| 4096 | — | HTTP 400 | — | 0.090 | Prompt + 64 output tokens exceeded `max_model_len=4096` (`input_tokens >= 4033`, total >= 4097) |

Lemonade vLLM recipe attempt:

```text
base_url: http://192.168.1.23:13305/v1
model: Qwen3.5-2B-FP16-vLLM
artifact: runs/local-prefill-latency/20260705T071328Z-lemonade-vllm-qwen35-2b-prefill-smoke
```

Result: both 512 and 2048 target prompt probes failed with Lemonade model-load errors, independent of stream/response-format simplification:

```text
Failed to load model 'Qwen3.5-2B-FP16-vLLM': vllm-server failed to start within timeout
```

Lemonade llama.cpp/GGUF path:

```text
base_url: http://192.168.1.23:13305/v1
model: Gemma-4-26B-A4B-it-GGUF
artifact: runs/local-prefill-latency/20260705T071616Z-lemonade-llamacpp-gemma4-26b-prefill-smoke
stream artifact: runs/local-prefill-latency/20260705T071650Z-lemonade-llamacpp-gemma4-26b-prefill-stream
```

| target prompt toks | reported prompt toks | mode | total s | note |
|---:|---:|---|---:|---|
| 512 | 1233 | non-stream | 21.251 | likely cold-ish first call / load/cache cost |
| 2048 | 4726 | non-stream | 5.536 | warmed-ish |
| 2048 | 4726 | stream | 1.456 | response included `usage.prompt_tokens_details.cached_tokens=4725`; no OpenAI delta content chunks captured, so `ttft_s` was null |

Interpretation:

- We did **not** previously have a good prefill-specific harness; the JSON concurrency probe was short-prompt focused.
- The new prefill probe is the right shape for this question, but endpoint-specific quirks matter:
  - standalone vLLM gives useful streaming TTFT and strict context errors;
  - Lemonade llama.cpp reports prompt-token usage and cached-token details, but its streaming response path may not expose OpenAI-style delta content chunks, so total latency + usage/cached tokens are currently more reliable than TTFT there;
  - Lemonade vLLM recipe load health can dominate/obscure prompt prefill measurements.
- Prompt-size targets are approximate; always use `usage.prompt_tokens` as the real x-axis where available. The 4096 target generated enough prompt tokens that `max_model_len=4096` failed once output tokens and chat-template overhead were included.

Next useful measurement:

- Run warmed ladders with repeats after explicit warmup: e.g. target sizes `512,1024,2048,3072` for the current standalone Granite 4k service, and larger sizes only after switching standalone vLLM to an 8k/16k context model/config.
- For Lemonade llama.cpp, run each size twice and report cold vs warmed/cached separately because `cached_tokens` can make repeated long prompts look deceptively fast.
- For true vLLM-vs-Lemonade apples-to-apples, pick a model that works in both lanes or accept that current comparison is service-path + model-path, not same-weights.


## Update — Gemma 4 26B/31B prefill matrix, standalone vLLM vs Lemonade (2026-07-05)

Added matrix runner:

```text
scripts/local_prefill_gemma_matrix.py
```

Run artifact:

```text
runs/local-prefill-latency/gemma-vllm-vs-lemonade-20260705T092128Z/
```

Run shape:

- Models:
  - standalone vLLM: `google/gemma-4-26B-A4B-it`, `google/gemma-4-31B-it`
  - Lemonade llama.cpp/GGUF: `gemma-4-26B-A4B-it-GGUF`, `gemma-4-31B-it-GGUF`
- Sizes: target `512,2048,4096`
- Repeats: 2
- Concurrency: 1
- Max output tokens: 64
- Warmup: small non-measured `SEND ACK IF RECEIVED` request after model load and before the real prefill probes.
- Isolation/unload:
  - Lemonade unloaded via `POST /api/v0/unload`; vLLM stopped via `systemctl stop vllm-json-probe.service`.
  - Lemonade was stopped during standalone vLLM phase; standalone vLLM was stopped before Lemonade phase.
  - Final state verified: Lemonade active with no model loaded; standalone vLLM inactive.

Standalone vLLM configs:

```text
26B: max_model_len=8192, max_num_seqs=2, max_num_batched_tokens=8192, kv_cache=8G, gpu_memory_utilization=0.90, no CPU offload
31B: same, plus --cpu-offload-gb 24
```

The 31B vLLM load succeeded with UVA offload:

```text
Offloader set to UVAOffloader
Total CPU offloaded parameters: 24.36
```

### Results

| backend | model | warmup s | target | reported prompt toks | first event p50 s | TTFT p50 s | total p50 s | cached toks | status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| standalone vLLM | `google/gemma-4-26B-A4B-it` | 2.076 | 512 | 1238.5 | 0.797 | 0.797 | 2.111 | — | complete |
| standalone vLLM | `google/gemma-4-26B-A4B-it` | 2.076 | 2048 | 4739.5 | 2.466 | 2.466 | 3.859 | — | complete |
| standalone vLLM | `google/gemma-4-26B-A4B-it` | 2.076 | 4096 | — | — | — | — | — | HTTP 400 context overflow |
| standalone vLLM | `google/gemma-4-31B-it` + CPU offload 24G | 3.389 | 512 | 1238.5 | 3.269 | 3.269 | 12.299 | — | complete |
| standalone vLLM | `google/gemma-4-31B-it` + CPU offload 24G | 3.389 | 2048 | 4739.5 | 14.564 | 14.564 | 23.728 | — | complete |
| standalone vLLM | `google/gemma-4-31B-it` + CPU offload 24G | 3.389 | 4096 | — | — | — | — | — | HTTP 400 context overflow |
| Lemonade llama.cpp | `gemma-4-26B-A4B-it-GGUF` | 22.553 | 512 | 1235.5 | 1.440 | — | 2.846 | 0 | complete |
| Lemonade llama.cpp | `gemma-4-26B-A4B-it-GGUF` | 22.553 | 2048 | 4736.5 | 4.575 | — | 6.033 | 0 | complete |
| Lemonade llama.cpp | `gemma-4-26B-A4B-it-GGUF` | 22.553 | 4096 | 9331.0 | 9.122 | — | 10.610 | 0 | complete |
| Lemonade llama.cpp | `gemma-4-31B-it-GGUF` | 25.908 | 512 | 1235.5 | 6.905 | — | 15.361 | 0 | complete |
| Lemonade llama.cpp | `gemma-4-31B-it-GGUF` | 25.908 | 2048 | 4736.5 | 21.647 | — | 30.399 | 0 | complete |
| Lemonade llama.cpp | `gemma-4-31B-it-GGUF` | 25.908 | 4096 | 9331.0 | 42.531 | — | 51.438 | 0 | complete |

Notes:

- `first_event` for Lemonade is available, but TTFT remains null because Lemonade/llama.cpp did not emit OpenAI-style `choices[].delta.content` chunks in the stream shape parsed by the probe. Treat first-event and total latency as the comparable Lemonade fields for now.
- The target sizes are approximate. With this filler/chat template, target 2048 became ~4740 prompt tokens; target 4096 became ~9331 prompt tokens under Lemonade. Standalone vLLM rejected target 4096 because max_model_len was 8192 plus output budget and chat/template overhead.
- Lemonade cached-token median was 0 for this matrix because the probe now includes size/repeat in the seed to avoid shared-prefix cache artifacts.

Interpretation:

- **For 26B, standalone vLLM was faster at measured sizes:** ~2.47s TTFT for ~4.7k prompt tokens vs Lemonade 26B first-event ~4.58s and total ~6.03s.
- **For 31B, standalone vLLM with 24G CPU offload was much slower than 26B vLLM and broadly similar/slower than Lemonade 31B depending metric:** at ~4.7k prompt tokens, vLLM 31B first token was ~14.6s and total ~23.7s; Lemonade 31B first event ~21.6s and total ~30.4s. At ~1.2k, vLLM 31B first token ~3.27s and total ~12.3s; Lemonade 31B first event ~6.9s and total ~15.4s.
- **The largest observed prompt (~9.3k tokens) only ran on Lemonade** because standalone vLLM was configured at 8k; Lemonade 26B handled it in ~10.6s total, Lemonade 31B in ~51.4s total.
- **MoE vs dense / total-weight effects are visible:** Gemma 26B-A4B MoE is dramatically more responsive than Gemma 31B dense in both backends; CPU offload makes 31B standalone vLLM especially expensive.

Next measurement recommendation:

- Rerun standalone vLLM 26B at `max_model_len=16384` with sizes targeting real prompt tokens around 1k/4k/9k so it can be compared directly to Lemonade's 9.3k prompt case.
- Add a non-stream Lemonade mode row if total latency is the main comparison target, and keep `first_event` as a separate field.
- Consider a lower output cap or simpler forced one-token response if the goal is purer prefill, because total latency currently includes 64-token decode budget even though output is tiny-ish.


## Update — standalone vLLM Gemma 4 resident 16k rerun (2026-07-05)

Focused rerun after discovering the prior 31B standalone vLLM row used unnecessary `--cpu-offload-gb 24` from a stale memory assumption.

Script:

```text
scripts/local_prefill_vllm_gemma_context_rerun.py
```

Artifact:

```text
runs/local-prefill-latency/gemma-vllm-context-rerun-20260705T105753Z/
```

Run shape:

- Backend: standalone vLLM only
- Models: `google/gemma-4-26B-A4B-it`, `google/gemma-4-31B-it`
- Config: `max_model_len=16384`, `kv_cache_memory_bytes=16G`, `max_num_seqs=1`, `max_num_batched_tokens=16384`, no CPU offload
- Sizes: target `512,2048,4096,6144`; repeats 2; concurrency 1; max output tokens 64
- Cleanup verified after run: Lemonade active/no model loaded; standalone vLLM inactive.

Resident/no-offload load facts from vLLM logs:

```text
26B-A4B: Model loading took 47.42 GiB memory; GPU KV cache size 76,191 tokens; max concurrency for 16,384 tokens/request: 4.65x
31B dense: Model loading took 57.82 GiB memory; GPU KV cache size 19,046 tokens
```

### Results

| model | real prompt toks | TTFT p50 s | total p50 s | status |
|---|---:|---:|---:|---|
| `google/gemma-4-26B-A4B-it` | 1238.5 | 0.839 | 2.240 | complete |
| `google/gemma-4-26B-A4B-it` | 4739.5 | 4.069 | 5.579 | complete |
| `google/gemma-4-26B-A4B-it` | 9334.0 | 11.421 | 13.069 | complete |
| `google/gemma-4-26B-A4B-it` | 13934.0 | 22.389 | 24.084 | complete |
| `google/gemma-4-31B-it` | 1238.5 | 3.257 | 12.297 | complete |
| `google/gemma-4-31B-it` | 4739.5 | 14.626 | 23.796 | complete |
| `google/gemma-4-31B-it` | 9334.0 | 37.846 | 47.199 | complete |
| `google/gemma-4-31B-it` | 13934.0 | 73.669 | 83.133 | complete |

### Interpretation

- The earlier 8k wall was just configuration. `max_model_len=16384` allowed the formerly failing target 4096 row (~9.3k real prompt tokens) and an additional target 6144 row (~13.9k real prompt tokens).
- The prior 31B CPU offload was unnecessary on current den-nimo TTM/GTT settings. 31B loaded resident with no offload.
- Removing CPU offload did **not** make 31B fast at the comparable 1.2k/4.7k prompt-token points; timings are very close to the earlier offload run. This suggests the main penalty is dense 31B compute/kernel path on this hardware, not just offload overhead.
- 26B-A4B MoE remains the much better local large-context option for latency. At ~9.3k prompt tokens, resident vLLM 26B took ~13.1s total vs Lemonade 26B GGUF ~10.6s total in the previous matrix; at ~13.9k prompt tokens vLLM 26B took ~24.1s total.

### Quantization note

The official `google/gemma-4-*` standalone vLLM runs here are not quantized: vLLM logs show `quantization=None`, `dtype=torch.float16`, and the model load memory matches fp16-ish weights. vLLM itself is not limited to full-fat models: current docs list quantization support including FP8 on AMD GPU and GGUF on AMD GPU; AWQ/GPTQ are not listed as AMD GPU-supported in the latest quantization compatibility table. For Strix Halo specifically, quantized model choice/kernel support is likely a major factor for larger dense models.
