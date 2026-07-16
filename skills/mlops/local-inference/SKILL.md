---
name: local-inference
description: "Run and manage local LLM inference servers — Lemonade, vLLM, llama.cpp server, Ollama — for sub-agent workloads, model testing, and routing tasks to on-prem hardware."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [inference, local-models, lemonade, llamacpp, vllm, ollama, sub-agents, amd]
    related_skills: [llama-cpp, huggingface-hub]
---

# Local Inference Servers

Managing local inference for Hermes sub-agents and model testing. This skill covers the *serving* layer — running models behind an OpenAI-compatible API — not training or fine-tuning (see `axolotl`, `unsloth`, `fine-tuning-with-trl` for those).

## When to Use

- Running local models for sub-agent workloads (review, drift detection, lightweight coding)
- Setting up inference servers on LAN hardware
- Testing different models by switching between them
- Routing Hermes delegation tasks to local hardware instead of cloud APIs

## Supported Servers

### Lemonade (AMD)

**Best for**: AMD hardware (Ryzen AI, Strix Halo, Radeon). Auto-optimizes for NPU/GPU/CPU. Multi-modal (LLM + image gen + TTS + transcription + embeddings). Primary LLM machine: **den-nimo** (192.168.1.23).

```yaml
# Hermes config for Lemonade as a custom provider
model:
  provider: lemonade
  base_url: http://HOST:13305/v1
  model: MODEL_NAME
```

**Key behaviors:**
- Auto-model-switching: send a request with `"model": "X"` and it loads/unloads automatically
- Only 1 LLM loaded at a time (also 1 image, 1 audio, 1 embedding)
- 86+ models in catalog, downloadable via web UI or `lemonade pull`
- OpenAI-compatible API at `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, etc.
- Web management UI at root URL
- Health endpoint at `/v1/health` shows loaded models, backend info, version
- Full API docs: see `references/lemonade-api.md`

**Hermes integration**: Use as a custom provider for sub-agents via delegation config. Route review/drift/coding tasks to Lemonade when local hardware is available. The auto-switching means different sub-agents can use different models without manual intervention — just set the model name in the request.

**Custom model storage**: Lemonade defaults to `~/.cache/huggingface/` for models. On systems with small root partitions, change `models_dir` in config.json:

```json
// Config location: /var/lib/lemonade/.cache/lemonade/config.json (Linux systemd)
// or ~/.cache/lemonade/config.json (standalone)
{
  "models_dir": "/home/llm"
}
```

This puts models in a shared location accessible to other services. The directory structure becomes HuggingFace cache format (`/home/llm/models--owner--repo/`). Other tools (vLLM, HuggingFace CLI) can share this cache by setting `HF_HOME=/home/llm`.

**Lemonade config.json location** (varies by install):
- Linux (systemd): `/var/lib/lemonade/.cache/lemonade/config.json`
- Windows: `%USERPROFILE%\.cache\lemonade\config.json`
- Standalone: `~/.cache/lemonade/config.json`

Key config fields:
- `models_dir` — where to store downloaded models
- `ctx_size` — default context window (default: 4096, can set to 200k+)
- `max_loaded_models` — max models per type slot (default: 1, use -1 for unlimited)
- `llamacpp.backend` — `vulkan`, `rocm`, `cpu`, or `auto`
- `llamacpp.args` — pass custom args to llama-server (e.g. `"--parallel 2"` for concurrent slots)
- `host` — bind address (default: `localhost`, set `0.0.0.0` for LAN access)

### vLLM

**Best for**: High-throughput serving, production workloads, concurrent multi-agent access. Built-in PagedAttention for efficient KV cache management.

```yaml
# Hermes config for vLLM as a custom provider
model:
  provider: vllm
  base_url: http://HOST:8000/v1
  model: MODEL_NAME
```

**Key behaviors:**
- Continuous batching — concurrent requests share compute efficiently (no queue)
- PagedAttention — KV cache allocated on-demand, no pre-reservation waste
- Automatic prefix caching — shared system prompts reuse cached KV
- Single model per instance (no auto-switching like Lemonade)
- OpenAI-compatible API at `/v1/chat/completions`
- Supports safetensors, GPTQ, AWQ, GGUF quantization

**Installation on Arch/EndeavourOS (ROCm for AMD GPU):**

vLLM with ROCm needs system-level ROCm packages. Two install patterns exist:

**Pattern A — User venv (quick test):**
```bash
uv venv --python 3.12 vllm-env --seed
source vllm-env/bin/activate
uv pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/
```

**Pattern B — Global install (production, what den-nimo uses):**
```bash
# Installs to /usr/local/bin/vllm and /usr/local/bin/vllm-python
# Venv lives at /opt/vllm/.venv with its own Python copy at /opt/vllm/python/
sudo /opt/vllm/.venv/bin/python -m pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/
```
The global install avoids user-permission issues and makes the binary available system-wide.

**Critical**: The ROCm wheels index (`https://wheels.vllm.ai/rocm/`) is required for AMD GPU support. Without it, vLLM installs CPU-only PyTorch.

**Missing `libmpi_cxx.so.40`**: If vLLM fails to import with this error, install `openmpi` system-wide:
```bash
sudo pacman -S openmpi
```
**Pitfall (Arch)**: Arch's stock `openmpi` may not fully satisfy ROCm's dependency checks. You may also need a ROCm openmpi compatibility shim/package. If `openmpi` alone doesn't resolve it, check ROCm package repos or the vLLM ROCm install docs for the specific compat package needed.

**Sharing model storage with Lemonade**: Point vLLM at the same model directory:
```bash
export HF_HOME=/home/llm  # Same as Lemonade's models_dir
vllm serve MODEL_NAME --model-dir /home/llm
```

**Running as a service**: vLLM can be started with:
```bash
vllm serve Qwen/Qwen3-8B --max-model-len 8192 --gpu-memory-utilization 0.9 --host 0.0.0.0 --port 8000
```

For systemd service, create `/etc/systemd/system/vllm.service` with the venv Python path.

**LD_LIBRARY_PATH for ROCm shim**: When running vLLM binary directly (not via venv activation), the openmpi compatibility shim at `/opt/vllm/lib/` may not be on the system library path:
```bash
LD_LIBRARY_PATH=/opt/vllm/lib:$LD_LIBRARY_PATH HSA_OVERRIDE_GFX_VERSION=11.0.0 \
  /usr/local/bin/vllm serve MODEL_NAME --host 0.0.0.0 --port 8000
```

**CPU offloading for large models**: The Strix Halo iGPU reports ~62 GiB GPU memory despite 128GB unified RAM. Models exceeding this at fp16 need `--cpu-offload-gb`:
```bash
# MoE models: ALL params loaded even though only a fraction are active per token
# Qwen3.6-35B-A3B = ~70GB fp16, only fits with 30GB CPU offload
vllm serve unsloth/Qwen3.6-35B-A3B \
  --host 0.0.0.0 --port 8000 \
  --dtype half --enforce-eager \
  --cpu-offload-gb 30 --max-model-len 4096
```
Result: ~15 tok/s (vs 100+ for small models fully on GPU). CPU-offloaded layers are fetched per-token, so throughput drops significantly. Use `--max-model-len` to reduce KV cache reservation and free GPU memory for more model weights.

**AWQ quantization — recommended for large models on Strix Halo:**
```bash
# AWQ-4bit fits entirely in 62 GiB GPU memory, no CPU offloading needed
# cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit — 306K downloads, most popular AWQ quant
vllm serve cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit \
  --host 0.0.0.0 --port 8000 \
  --dtype half --enforce-eager --max-model-len 8192
```
Result: ~24 tok/s — **56% faster** than fp16+CPU offloading. Model weights ~18 GiB at 4-bit, fits entirely in GPU. Trade-off: some precision loss, but coding tests showed clean output with proper type hints and efficient algorithms. Monitor for reasoning degradation on complex tasks.

**Strix Halo (gfx1151) specifics:**
- Active ROCm development — kernels tuned for gfx1151 (April 2026)
- Uses ROCm (not Vulkan) for GPU acceleration
- 128GB unified memory works but vLLM expects to "own" GPU memory
- Benchmarks: Qwen3-8B ~70ms TPOT, Qwen3-4B ~37ms TPOT
- See `references/vllm-strix-halo.md` for detailed setup notes
- See `references/gemma-prefill-vllm-lemonade.md` for non-tiny Gemma long-prompt prefill methodology, Lemonade unload endpoints, prefix-cache gotchas, and vLLM CPU-offload notes

### llama.cpp server

**Best for**: Maximum control, GGUF models, minimal overhead. See `llama-cpp` skill for details.

- `llama-server -m MODEL.gguf --host 0.0.0.0 --port 8080`
- OpenAI-compatible at `/v1/chat/completions`

## Choosing a Server

| Feature | Lemonade | Ollama | vLLM | llama.cpp |
|---------|----------|--------|------|-----------|
| Auto-model-switch | ✓ | ✓ | ✗ (manual) | ✗ (manual) |
| Max concurrent LLMs | 1 | Multiple | 1 (but fast) | 1 |
| Multi-modal | ✓ (image, audio, TTS) | Limited | ✗ | ✗ |
| AMD optimization | ✓ (NPU, Vulkan, ROCm) | Basic | ROCm | Vulkan/ROCm |
| Setup complexity | Low (installer) | Low | Medium | Low |
| Throughput | Moderate | Moderate | High | Moderate |

## Hermes Config Patterns

### As a fallback provider

```yaml
# In delegation config or sub-agent config
delegation:
  base_url: http://192.168.1.23:13305/v1
  model: Qwen3.6-27B-GGUF
```

### For specific task routing

Route certain task types (review, drift) to local hardware:
- Use Hermes delegation with `base_url` pointing at the local server
- Set model name per task type
- Lemonade auto-handles loading/unloading

## KV Cache and Concurrent Request Behavior

This is critical for multi-agent workloads. How requests interleave determines whether your agents are fast or thrashing.

### Lemonade (llama.cpp backend)

**Default: sequential processing.** One request at a time. If Agent X and Agent Y hit the server simultaneously, one queues.

**KV cache thrashing:** When interleaved agents share a single Lemonade instance:
1. Agent X step 1 → fills KV cache with its prompt
2. Agent Y step 1 → **overwrites the cache** (different prompt prefix)
3. Agent X step 2 → must reprocess entire prompt from scratch (cache miss)

This makes interleaved multi-step agents extremely slow.

**Parallel mode:** llama.cpp supports `--parallel N` for concurrent slots. Configure via Lemonade:

```bash
# In config.json
{
  "llamacpp": {
    "args": "--parallel 2"  # or --parallel 4
  }
}
```

With `--parallel N`:
- N separate KV cache slots exist simultaneously
- Agent X and Agent Y can each keep their conversation state
- But they share compute (tokens/sec drops ~1/N per agent)
- With 128GB RAM and 20GB model, plenty of room for multiple KV caches at 200k context

**Health endpoint shows config:**
```bash
curl http://HOST:13305/v1/health
# Shows: ctx_size, llamacpp_backend, model_loaded, etc.
```

### vLLM

**Built for concurrency.** Three key mechanisms:

1. **PagedAttention** — KV cache managed like OS virtual memory (pages/blocks). Allocates on-demand, no pre-reservation waste.
2. **Continuous batching** — as soon as one request finishes, a new one fills its slot. No wasted compute.
3. **Automatic prefix caching** — if multiple requests share the same system prompt, the KV cache for that prefix is shared.

For multi-agent workloads, vLLM handles interleaved requests far better than llama.cpp. No cache thrashing — each request gets its own KV cache blocks dynamically.

**Strix Halo (gfx1151) support:** Active ROCm development. PR from April 2026 tuned kernels specifically for Strix Halo:
- Qwen3-4B: ~37ms TPOT (tokens per output time)
- Qwen3-8B: ~70ms TPOT
- Gemma-3-4B: ~37ms TPOT
- Hardware: LPDDR5X-8000 128GB, 20 CUs

```bash
# Quick start on Strix Halo
pip install vllm
vllm serve Qwen/Qwen3-8B --max-model-len 8192 --gpu-memory-utilization 0.9
```

### Shared Model Storage Pattern

When running multiple inference servers on the same machine, share a single model cache to avoid duplicate downloads:

```
/home/llm/                          # Shared model directory
├── models--unsloth--Qwen3.6-27B-GGUF/   # HuggingFace cache format
├── models--unsloth--gemma-4-31B-it-GGUF/
└── ...
```

**Lemonade**: Set `"models_dir": "/home/llm"` in config.json
**vLLM**: Set `export HF_HOME=/home/llm` before starting
**HuggingFace CLI**: Set `export HF_HOME=/home/llm` for `huggingface-cli download`

Both Lemonade and vLLM use HuggingFace cache format, so they can share the same directory. Models downloaded by one server are available to the other.

**Important**: vLLM prefers safetensors format over GGUF for optimal performance. If you only have GGUF models (from Lemonade), vLLM can still use them but may be slower. For best vLLM performance, download safetensors variants separately.

## Multi-Machine Routing

With two Strix Halo boxes (e.g., 192.168.1.23 and 192.168.1.24):
- Dedicate one box to inference, keep one for dev work
- Or run inference on both with intelligent routing
- Lemonade: each instance is independent, route via `base_url`
- vLLM: can do tensor parallelism across machines (advanced)

## Pitfalls

- **Lemonade: 1 LLM at a time** — if two sub-agents need different models simultaneously, they serialize. Plan model usage or keep agents on the same model.
- **Lemonade KV cache thrashing** — interleaved multi-step agents on a single Lemonade instance (without `--parallel`) will thrash the cache. Either use `--parallel`, keep agents sequential, or use vLLM instead.
- **Model loading latency** — first request to a new model takes seconds to load. Subsequent requests are fast. Budget this for time-sensitive tasks.
- **Hardware reality** — 16GB VRAM cards can only run small models (3-7B). 128GB unified memory systems can load 20-25GB models comfortably with plenty of KV cache headroom. Size models to your hardware.
- **Context window** — local models may have smaller context windows than cloud APIs. Check `ctx_size` in health endpoint. Lemonade default is 4096; can be set to 200k+.
- **Token throughput** — local models are slower than cloud APIs. Good for sub-agent work (review, drift) where latency matters less. Less ideal for interactive chat.
- **vLLM vs Lemonade for multi-agent** — if you need concurrent agents hitting the same model, vLLM's continuous batching and PagedAttention are significantly better than llama.cpp's `--parallel` mode. Use vLLM for production multi-agent serving, Lemonade for quick testing and model switching.
- **Long-prompt prefill benchmarks need cache discipline** — For vLLM vs Lemonade comparisons, do not mix model-load, warmup, prefix-cache, and real prefill latency. Send a tiny ACK after loading, then use unique prompts per size/repeat, plot against reported `usage.prompt_tokens`, and report cached-token counts when Lemonade/llama.cpp returns them. Unload Lemonade with `POST /api/v0/unload` and stop unused services between large-model runs. See `references/gemma-prefill-vllm-lemonade.md`.
- **vLLM CUDA graphs crash on Strix Halo inference** — Model loads fine, CUDA graph capture succeeds, but first inference request returns 500 "EngineCore encountered an issue". Use `--enforce-eager` flag to disable CUDA graphs. Slower but functional. Monitor vLLM ROCm releases for a fix. See `references/vllm-strix-halo.md`.
- **vLLM Triton fallback** — On gfx1151, ROCm custom paged attention may not be available. vLLM falls back to Triton automatically. Non-critical warning, works but may be slower.
- **vLLM HSA_OVERRIDE_GFX_VERSION** — Some ROCm versions need `HSA_OVERRIDE_GFX_VERSION=11.0.0` env var for the GPU to be recognized. Test without it first.
- **ROCm openmpi compat shim** — Arch's stock `openmpi` may not fully satisfy vLLM's ROCm dependency checks. May need an additional compat package from ROCm repos. See `references/vllm-strix-halo.md`.
- **uv venvs are user-scoped** — when using `uv venv` to create Python environments, the venv is owned by the creating user and lives in their home directory. Other users can't access it without explicit permissions. Either:
  - Create venvs in a shared location (`/home/llm/vllm-env`)
  - Or symlink/copy to a shared path
  - Or change ownership: `sudo chown -R shared-user:shared-group /path/to/venv`
- **Moving a venv after creation breaks it** — scripts in `bin/` have shebangs hardcoded to the original path (e.g. `#!/home/patch/.venv/bin/python3`), and `pyvenv.cfg` has a `home =` entry pointing to the original location. Python symlinks (`python`, `python3`) typically point to the actual CPython install (e.g. `~/.local/share/uv/python/...`) and survive moves, but all wrapper scripts break. See `references/venv-relocation.md` for the fix recipe.
- **ROCm system deps** — vLLM with ROCm needs `openmpi` (provides `libmpi_cxx.so.40`) and ROCm runtime packages installed system-wide. These can't be installed via pip/uv — they must be installed via the system package manager (`pacman`, `apt`, etc.) with sudo.
- **SSH sudoers setup** — When managing multiple machines, set up a dedicated `agent` user with NOPASSWD sudo for systemctl/journalctl. Use SSH config aliases (`agent-nimo`) for clean access. This avoids password prompts for service management while keeping package installs gated behind sudo.
