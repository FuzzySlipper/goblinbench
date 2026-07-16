# vLLM on Strix Halo (gfx1151) — Setup Notes

## Hardware

- **Chip**: AMD Strix Halo (Ryzen AI 395)
- **GPU**: Radeon 8050S/8060S Graphics (gfx1151, 20 CUs)
- **RAM**: 128GB LPDDR5X-8000 unified memory
- **OS**: EndeavourOS (Arch-based)

## Installation (den-nimo — global install)

```bash
# System dependencies (requires sudo with password)
sudo pacman -S openmpi
# Arch's openmpi alone may not satisfy ROCm — may need compat shim from ROCm repos
# Check vLLM ROCm install docs if libmpi_cxx errors persist after openmpi install

# Global install (installs to /usr/local/bin/)
# Binary: /usr/local/bin/vllm + /usr/local/bin/vllm-python
# Venv: /opt/vllm/.venv (Python 3.12, own copy at /opt/vllm/python/)
```

### Verify installation

```bash
/usr/local/bin/vllm --version
# Should show: 0.20.1+rocm721 (or newer)
```

### Import test

```bash
/opt/vllm/.venv/bin/python -c "import vllm; print(vllm.__version__)"
```

## Running

```bash
# Basic serve (uses CUDA graphs — may crash on inference, see Known Issues)
HSA_OVERRIDE_GFX_VERSION=11.0.0 /usr/local/bin/vllm serve Qwen/Qwen3-8B \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.9 \
  --host 0.0.0.0 \
  --port 8000

# Safe mode (enforce-eager — skip CUDA graphs, works on gfx1151)
HSA_OVERRIDE_GFX_VERSION=11.0.0 /usr/local/bin/vllm serve Qwen/Qwen2.5-0.5B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype half \
  --enforce-eager
```

**Note**: `HSA_OVERRIDE_GFX_VERSION=11.0.0` may be needed depending on ROCm version. Test without it first.

## Benchmarks (from vLLM PR #40784, April 2026)

End-to-end on Strix Halo (128GB LPDDR5X-8000), input-len=128, output-len=128, num-prompts=5:

| Model                        | TPOT (ms) |
|------------------------------|-----------|
| Qwen/Qwen2.5-0.5B-Instruct  | 5.18      |
| Qwen/Qwen3-4B               | 36.85     |
| Qwen/Qwen3-8B               | 70.09     |
| google/gemma-3-4b-it         | 36.63     |

Kernel improvements on gfx1151 (bf16 wvSplitK):
- N=1: +18.7% bandwidth
- N=2: +19.8%
- N=3: +15.2%
- N=4: +13.0%

## Known Issues

### CUDA graphs crash during inference (gfx1151)
- **Symptom**: vLLM starts fine, model loads, CUDA graph capture succeeds, but first inference request returns 500 "EngineCore encountered an issue" and the server may crash
- **Workaround**: Use `--enforce-eager` flag. This disables torch.compile and CUDA graphs. Slower but functional.
- **Root cause**: Likely a GFX version compatibility issue with the iGPU. CUDA graph kernels may target a different GPU generation.
- **Status**: Active as of May 2026. Monitor vLLM ROCm releases for a fix.

### Triton fallback for paged attention
- **Symptom**: Warning "Cannot use ROCm custom paged attention kernel, falling back to Triton implementation"
- **Impact**: Non-critical — Triton fallback works but may be slower than native ROCm kernels
- **Status**: Normal on gfx1151 as of vLLM 0.20.1

### `libmpi_cxx.so.40` not found
- Install `openmpi` via pacman
- If still missing after openmpi install, Arch's stock openmpi may need a ROCm compat shim — check ROCm package repos

### openmpi compat shim
- Arch's packaged openmpi may not fully satisfy ROCm dependency checks
- User reported needing a compatibility shim in addition to `pacman -S openmpi`
- Check vLLM ROCm install docs or AUR for the specific package

### `LD_LIBRARY_PATH` for openmpi shim
- The shim lives at `/opt/vllm/lib/libmpi_cxx.so.40`
- When running vllm binary directly (not via venv activate), it's not on the search path
- Fix: `LD_LIBRARY_PATH=/opt/vllm/lib:$LD_LIBRARY_PATH /usr/local/bin/vllm serve ...`

## GPU Memory Limitation

ROCm reports only ~62.2 GiB GPU memory on the Strix Halo despite 128GB unified RAM. This is the default **TTM** (Translation Table Manager) allocation — **not a hardware limit**.

### Memory Architecture

The Strix Halo has two memory pools:
- **GART** — Fixed reserved aperture set by BIOS (set to minimum like 512MB)
- **TTM** — Dynamically allocable memory, configurable via kernel parameters (formerly called "GTT" — AMD deprecated that term)

The default TTM allocation is ~62 GiB. On Windows, it auto-allocates up to 96 GiB. On Linux, it must be configured manually.

**Note**: Use `amd-ttm` utility to check/set TTM values. AMD deprecated the "GTT" name — config options now use `ttm.*` (e.g. `ttm.pages_limit` instead of `amdgpu.gttsize`).

### Configuring TTM (from Strix Halo Wiki)

Create `/etc/modprobe.d/amdgpu_llm_optimized.conf`:

```
# GTT pages limit: 31457280 pages × 4KB = 120 GiB
# Leave 8 GiB buffer for OS stability
options ttm pages_limit=31457280

# Pre-allocate to minimize fragmentation (set to match pages_limit for max performance)
options ttm page_pool_size=31457280

# Deprecated but referenced by some software

```

After changes, regenerate initramfs and reboot. den-nimo runs **headless** (no desktop environment) with auto-deleting/auto-cleanup removed — OS overhead is minimal (~4-8 GiB), leaving ~120-124 GiB usable for models.
```bash
# Arch:
sudo mkinitcpio -P
sudo reboot
```

**Impact**: With 120 GiB GTT, you could load the full fp16 Qwen3.6-35B-A3B (~70GB) without CPU offloading, though KV cache and OS overhead would be tight. More practically, it allows running larger models or more concurrent instances.

**Note**: vLLM expects to "own" GPU memory. On unified memory systems, it may compete with CPU for memory. Setting `page_pool_size` high pre-allocates for the GPU, reducing fragmentation but making that memory unavailable to the OS.

## AWQ Quantization (Recommended for Large Models)

## CPU Offloading

### When to use
- Model weights exceed GPU memory (e.g. 35B params at fp16 = ~70GB)
- You have plenty of system RAM (128GB on Strix Halo)

### How it works
- `--cpu-offload-gb N` keeps N GB of weights on CPU RAM via UVA offloading
- Remaining weights stay on GPU
- CPU-resident weights are fetched per-token during inference (slower path)
- Uses UVAOffloader (Unified Virtual Addressing) — not a separate process

### MoE model memory trap
MoE models have a **deceptive memory footprint**:
- Qwen3.6-35B-A3B: only 3B active params per token (fast!) but 35B total (~70GB fp16)
- ALL params must be loaded into addressable memory, not just active ones
- 3B active count affects throughput, not memory
- The same applies to any MoE model (Mixtral, DeepSeek, etc.)

### Benchmark: Qwen3.6-35B-A3B with 30GB CPU offload

```
Config: --cpu-offload-gb 30 --max-model-len 4096 --enforce-eager --dtype half
GPU memory: 36.8 GiB model + 17.99 GiB KV cache = ~55 GiB total
CPU offloaded: 30.83B parameters
KV cache capacity: 522,532 tokens
Generation throughput: ~15 tok/s (peak 15.7 tok/s in server logs)
Model load time: ~3.5 min (including 67GB HF download on first run)
```

Compare: Qwen2.5-0.5B fully on GPU = ~100+ tok/s

### Memory arithmetic

```
GPU total: 62.2 GiB
Model weights (fp16): params × 2 bytes
KV cache: max_seq_len × num_layers × 2 × head_dim × 2 bytes
CPU offload = gpu_total - model_on_gpu - kv_cache_reserve
Safe offload range: 20-30GB (leaves 30-40GB for model + KV)
```

### `--max-model-len` for memory savings

Reducing context window from default 32768 to 4096 frees significant KV cache memory, allowing more model weights on GPU. Trade-off: shorter max context per request.

### Benchmark: Qwen3.6-35B-A3B AWQ-4bit (no offload)

```
Config: --dtype half --enforce-eager --max-model-len 8192
Model: cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit (306K downloads, most popular AWQ)
Model weights: ~18 GiB at 4-bit (fits entirely in 62 GiB GPU memory)
KV cache: plenty of room with 8192 max context
Generation throughput: ~24 tok/s (56% faster than CPU offloading)
Coding test: Clean output with type hints, docstrings, efficient 6k±1 prime algorithm
```

### Other popular quants for Qwen3.6-35B-A3B

| Model | Type | Downloads | Notes |
|-------|------|-----------|-------|
| `cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit` | AWQ | 306K | Most popular, tested ✓ |
| `QuantTrio/Qwen3.6-35B-A3B-AWQ` | AWQ | 263K | Alternative AWQ |
| `palmfuture/Qwen3.6-35B-A3B-GPTQ-Int4` | GPTQ | 76K | Most popular GPTQ |

## Quant Quality Testing

When testing quantized models for coding/reasoning tasks, look for:

**Good signs (AWQ-4bit passed these):**
- Correct type hints and function signatures
- Efficient algorithms (e.g., 6k±1 for primality, not trial division)
- Proper edge case handling (empty lists, negative numbers, boundary values)
- Clean docstrings with Args/Returns sections

**Degradation signals to monitor:**
- Incorrect algorithm choices (e.g., O(n²) where O(n log n) exists)
- Missing edge cases or wrong boundary conditions
- Syntax errors or invalid Python constructs
- Hallucinated APIs or modules that don't exist
- Weaker reasoning on multi-step problems (e.g., dynamic programming, graph algorithms)

**Testing methodology:**
- Run same prompts on fp16 baseline and AWQ-4bit, compare outputs
- Focus on coding tasks: function implementation, bug fixing, code review
- Test with increasing complexity: simple functions → algorithms → system design
- Log token counts and generation time for throughput comparison

## Benchmarks (from vLLM PR #40784, April 2026)
- vLLM expects to "own" GPU memory. On unified memory systems, it works but may compete with CPU for memory
- With 128GB, plenty of headroom for 20-25GB models plus KV cache

### HSA_OVERRIDE_GFX_VERSION
- May need `HSA_OVERRIDE_GFX_VERSION=11.0.0` for ROCm to recognize the GPU
- Test without it first — some ROCm versions auto-detect gfx1151

## GoblinBench JSON-concurrency probe findings (2026-06-29)

Initial GoblinBench probe script: `/home/dev/goblinbench/scripts/local_json_concurrency_probe.py`; Den note: `goblinbench/local-vllm-json-concurrency-probe-2026-06-29`.

Observed den-nimo state:
- Lemonade endpoint: `http://192.168.1.23:13305/v1`.
- Global standalone vLLM: `/usr/local/bin/vllm`, observed `0.21.0+rocm722`.
- Direct vLLM import/run needs the openmpi shim in library path:
  `LD_LIBRARY_PATH=/opt/vllm/lib:$LD_LIBRARY_PATH`.
- `agent` SSH works and now has broad passwordless sudo (`sudo -n true` verified 2026-06-29). Earlier constrained-only sudo notes are stale for den-nimo.
- Standalone GoblinBench test service installed/enabled: `vllm-json-probe.service` on port `8000`, default model `Qwen/Qwen2.5-0.5B-Instruct` served as `qwen25-05b-standalone`. Config: `/etc/vllm-json-probe.env`; wrapper: `/usr/local/bin/vllm-json-probe-serve`; model switch helper: `/usr/local/sbin/vllm-json-probe-set-model HF_MODEL_ID [SERVED_NAME]`.
- Service runtime/cache paths are pinned under `/home`: `HF_HOME=/home/llm`, `XDG_CACHE_HOME=/home/llm/vllm-runtime/cache`, `TRITON_CACHE_DIR=/home/llm/vllm-runtime/triton`, `TMPDIR=/home/llm/vllm-runtime/tmp`, avoiding the small `/` partition.

Lemonade-managed vLLM behavior:
- Lemonade exposes downloaded vLLM recipes through the normal `:13305/v1` OpenAI-compatible endpoint and handles auto-load.
- It has one LLM slot; run one model at a time for matrix tests.
- Cold-load dominates the first concurrent wave: observed ~55s for `Qwen3.5-0.8B-FP16-vLLM`, ~220s for `Qwen3.5-2B-vLLM` before restart; warmed calls were ~1–3s for the small JSON probe.
- Small vLLM models returned parseable JSON reliably in the probe (`json_invalid=0`) but weaker models missed fields or got fuzzy constraints wrong, so reports should separate `contract_ok` from `decision_ok`.

4B/standalone caveats:
- Attempting Lemonade-managed `Qwen3.5-4B-vLLM` before restart exceeded a 10-minute foreground cap and left vLLM children not registered as loaded; `sudo -n systemctl restart lemond` cleaned it up.
- Likely cause: Lemonade vLLM recipes use huge `ctx_size` / `--max-model-len 200000` by default, which is bad for fast stress tests.
- `Qwen/Qwen3.5-*` standalone vLLM attempts on den-nimo were treated as Qwen3-VL / multimodal models by vLLM 0.21.0 and failed during MM encoder profiling with `torch.OutOfMemoryError: Tried to allocate 192.00 GiB`. Adding `--kv-cache-memory-bytes 4G` did not fix this; use known text-only models first (`Qwen/Qwen2.5-0.5B-Instruct` worked) and treat Qwen3.5 catalog entries as suspicious until model architecture is verified.
- A text-only standalone service with `Qwen/Qwen2.5-0.5B-Instruct`, `--max-model-len 4096`, `--kv-cache-memory-bytes 4G`, `--max-num-seqs 32`, and caches under `/home/llm/vllm-runtime` passed direct chat completion and GoblinBench JSON probes.
- For Gemma 4 text-only JSON probes, set `VLLM_DOWNLOAD_DIR=/home/llm` and `VLLM_LIMIT_MM_PER_PROMPT={"image":0,"video":0,"audio":0}` so vLLM passes `--download-dir /home/llm --limit-mm-per-prompt ...` and logs text-only mode. Official HF Gemma repos may require `HF_TOKEN` in `/etc/vllm-json-probe.env` (kept `0600 root:root`). Verified 2026-06-30: `google/gemma-4-E2B-it`, `google/gemma-4-E4B-it`, and `google/gemma-4-26B-A4B-it` all served on den-nimo vLLM 0.21.0. 26B-A4B downloaded ~48.07 GiB in ~386.6s, used TRITON unquantized MoE backend, became ready in ~8.3m, and passed GoblinBench JSON probe transport/contract (16/16 contract-valid at concurrency 4), but consumed ~50 GiB process memory. `google/gemma-4-12B-it` and checked 12B variants use `gemma4_unified`, which the current bundled Transformers does not recognize; likely needs vLLM/Transformers upgrade before serving.
- Additional candidate sweep (2026-06-30, 16 requests/concurrency 4): `ibm-granite/granite-4.1-8b` served and looked strong (16/16 contract, 12/16 decision, p50 7.58s); `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16` served on AMD despite NVIDIA branding (16/16 contract, 12/16 decision, p50 3.51s, one slow tail 39.9s); `LiquidAI/LFM2.5-8B-A1B` served via TRITON unquantized MoE backend (14/16 contract, 8/16 decision, p50 5.29s). `Qwen/Qwen3.5-4B` needed `/home/llm` ownership cleanup after Lemonade-owned cache files, then loaded weights but never opened API after >10m; logs still initialized Qwen VL/MM + GDN/Mamba-ish Triton kernels. Restored standalone service to Granite after the failed Qwen retry.

Recommended high-concurrency path:
1. Use Lemonade for quick model discovery and small one-model-at-a-time JSON probes.
2. For actual many-agent stress, create a supervised standalone vLLM service with a fixed model, sane max context (4k/8k/16k), warmed kernels/cache, explicit `LD_LIBRARY_PATH`, and restart/cleanup policy.
3. Add warmup and concurrency-sweep modes to GoblinBench before doing large runs.

Long-prompt prefill testing:
- Use `/home/dev/goblinbench/scripts/local_prefill_latency_probe.py` for prefill-specific measurements. It sends deterministic long prompts with tiny outputs and records streaming TTFT, total latency, `usage.prompt_tokens`, and transport errors.
- Treat target sizes as approximate; use endpoint-reported `prompt_tokens` as the real x-axis. Example: a target 2048 prompt produced 3574 prompt tokens on standalone Granite due filler/tokenizer/chat overhead.
- Standalone vLLM exposes useful OpenAI-style streaming TTFT. Smoke on `granite-41-8b` with `max_model_len=4096`: target 512→945 prompt tokens TTFT 0.099s/total 2.315s; target 2048→3574 prompt tokens TTFT 0.295s/total 2.582s; target 4096 failed because prompt + 64 output tokens exceeded 4096 context.
- Lemonade llama.cpp/GGUF can report `usage.prompt_tokens_details.cached_tokens`; repeated long prompts may look much faster due cache. Smoke on `Gemma-4-26B-A4B-it-GGUF`: target 2048→4726 prompt tokens, non-stream total 5.536s, later stream total 1.456s with 4725 cached tokens, but no OpenAI delta content chunks were captured so TTFT was null.
- Lemonade vLLM recipe health can dominate prefill measurements: `Qwen3.5-2B-FP16-vLLM` failed with `vllm-server failed to start within timeout` during prefill smoke, independent of stream/response_format simplification.
- Full Gemma 4 26B/31B prefill matrix artifact: `/home/dev/goblinbench/runs/local-prefill-latency/gemma-vllm-vs-lemonade-20260705T092128Z/`. Shape: target sizes 512/2048/4096, repeats 2, concurrency 1, ACK warmup, services isolated/unloaded. Standalone vLLM 26B-A4B at 8192 ctx: ~1238 prompt tokens TTFT 0.797s/total 2.111s; ~4739 prompt tokens TTFT 2.466s/total 3.859s; target 4096 overflowed ctx. Standalone vLLM 31B dense was run with `--cpu-offload-gb 24` due stale/conservative memory assumptions: ~1238 prompt tokens TTFT 3.269s/total 12.299s; ~4739 prompt tokens TTFT 14.564s/total 23.728s; target 4096 overflowed ctx. Correction: current den-nimo ROCm/TTM view reports GTT Total Memory 137438953472 bytes (~128 GiB), `ttm.pages_limit=33554432`, so use resident/no-offload first. Lemonade llama.cpp Q6 26B: ~1235 prompt tokens first_event 1.440s/total 2.846s; ~4736 first_event 4.575s/total 6.033s; ~9331 first_event 9.122s/total 10.610s. Lemonade llama.cpp Q6 31B: ~1235 first_event 6.905s/total 15.361s; ~4736 first_event 21.647s/total 30.399s; ~9331 first_event 42.531s/total 51.438s. Lemonade stream did not expose OpenAI delta content chunks, so compare first_event/total rather than TTFT; cached-token median was 0 after cache-busting prompt seeds.
- Resident/no-offload standalone vLLM 16k rerun artifact: `/home/dev/goblinbench/runs/local-prefill-latency/gemma-vllm-context-rerun-20260705T105753Z/`. Config: `max_model_len=16384`, `kv_cache_memory_bytes=16G`, `max_num_seqs=1`, no CPU offload. 26B-A4B loaded resident at 47.42 GiB model memory, KV cache 76,191 tokens; results: ~1238 prompt toks TTFT 0.839s/total 2.240s, ~4739 TTFT 4.069s/total 5.579s, ~9334 TTFT 11.421s/total 13.069s, ~13934 TTFT 22.389s/total 24.084s. 31B dense loaded resident at 57.82 GiB model memory, KV cache 19,046 tokens; results: ~1238 prompt toks TTFT 3.257s/total 12.297s, ~4739 TTFT 14.626s/total 23.796s, ~9334 TTFT 37.846s/total 47.199s, ~13934 TTFT 73.669s/total 83.133s. Removing offload did not materially improve 31B at the comparable low/mid prompt sizes, so the main penalty appears to be dense 31B compute/kernel path on Strix Halo rather than offload alone.

## SSH Access

From den-k8 (where Hermes runs):

```
# SSH config entries:
Host den-nimo
    Hostname 192.168.1.23
    user patch

Host agent-nimo
    Hostname 192.168.1.23
    user agent
```

**Agent user convention**: All machines use an `agent` user for agent access. This separates agent actions from personal user accounts for easier auditing and change tracking. SSH aliases follow the `agent-<machine>` pattern (e.g. `agent-nimo`).

**Sudoers policy**: The `agent` user has NOPASSWD sudo for diagnostic/systemctl/journalctl commands. Package installs remain gated behind the personal user's sudo (requires password). Finding the middle ground — agents need enough access to be useful (check services, read logs, restart daemons) but not so much that they can install arbitrary packages or modify system config without oversight.
