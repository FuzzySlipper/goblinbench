---
name: strix-halo-local-inference
description: Local LLM inference on Strix Halo APUs — vLLM (ROCm) and Lemonade (Vulkan) setup, gotchas, and benchmarking results.
tags: [inference, amd, rocm, vulkan, strix-halo, vllm, lemonade, gguf, awq]
triggers:
  - Setting up or troubleshooting vLLM or Lemonade on Strix Halo
  - Choosing between ROCm and Vulkan backends
  - Quantization selection for Strix Halo memory limits
  - Benchmarking local inference throughput
---

# Strix Halo Local Inference

## Hardware: den-nimo (Ryzen AI 395, 128GB LPDDR5X)

- GPU: Radeon 8060S (RDNA 3.5, gfx1151), 40 CU
- Theoretical: 59.4 FP16 TFLOPS, 256 GB/s memory bandwidth
- GPU memory reported by ROCm: ~62 GiB (default GTT allocation, adjustable)
- SSH: `den-nimo` (patch user), `agent-nimo` (agent user, NOPASSWD sudo for systemctl only)

## Runtime Comparison (as of vLLM 0.20.1 + Lemonade 10.3.0)

| Metric | Lemonade Vulkan | vLLM ROCm |
|---|---|---|
| General tok/s | **54.9** | 24.2 |
| Coding tok/s | **56.5** | 24.2 |
| Model | Q4_K_XL GGUF (21GB) | AWQ-4bit (~18GB) |
| Startup | ~instant | ~5 min (download + load) |
| CUDA graphs | N/A | Broken (crashes on inference) |
| Multi-model | Single model only | Multiple model support |
| Batching | No | Yes |

**Winner for current use: Lemonade + Vulkan.** vLLM is a future path as ROCm matures.

## vLLM Setup

- **Binary:** `/usr/local/bin/vllm` + `/usr/local/bin/vllm-python` (v0.20.1+rocm721)
- **Venv:** `/opt/vllm/.venv` (Python 3.12, own copy at `/opt/vllm/python/`)
- **Critical:** `LD_LIBRARY_PATH=/opt/vllm/lib:$LD_LIBRARY_PATH` required for openmpi shim
- **Launch:** `HSA_OVERRIDE_GFX_VERSION=11.0.0 /usr/local/bin/vllm serve <model> --host 0.0.0.0 --port 8000 --dtype half --enforce-eager`

### Gotchas

1. **openmpi:** Arch stock openmpi can't satisfy ROCm requirements — needs compatibility shim at `/opt/vllm/lib/` (libmpi_cxx.so.40)
2. **CUDA graphs:** Graph capture succeeds but inference crashes. Must use `--enforce-eager`.
3. **GTT memory limit:** ROCm sees ~62 GiB by default. Adjustable via kernel params:
   ```
   # /etc/modprobe.d/amdgpu_llm_optimized.conf
   options ttm pages_limit=31457280        # 120 GiB
   options ttm page_pool_size=31457280     # pre-allocate all
   options amdgpu gttsize=122800           # deprecated but referenced by software
   ```
   Regenerate initramfs after changes.
4. **FP16 models >62 GiB won't fit** without CPU offloading. Use quantized models or `--cpu-offload-gb`.
5. **ROCm immature on gfx1151:** Track https://github.com/ROCm/ROCm/issues/4748

## Lemonade Setup

- **CLI:** `lemonade` (global install, port 13305)
- **Backend:** Vulkan (v8940) — most reliable on Strix Halo
- **Models:** GGUF format, managed via `lemonade list/load/pull`
- **Launch:** `lemonade load <model-name> --llamacpp vulkan --ctx-size 8192`
- **API:** OpenAI-compatible at `http://localhost:13305/v1/`

### Tips

- Vulkan is more stable and faster than ROCm on Strix Halo (wiki confirms)
- Try `AMD_VULKAN_ICD=RADV` to compare Mesa RADV vs AMDVLK
- Performance: `sudo tuned-adm profile accelerator-performance` (+3-8%)
- Set `amd_iommu=off` in kernel for ~6% faster memory reads

## Quant Selection for 128GB Strix Halo

- **Q4_K_XL GGUF / AWQ-4bit:** ~18-21 GiB, fits in 62 GiB GPU, ~55 tok/s (Vulkan)
- **FP16 (full):** ~70 GiB for 35B, needs CPU offloading, ~15 tok/s (ROCm)
- AWQ has better vLLM support (CompressedTensorsWNA16MoEMethod)
- Test quant quality empirically for coding tasks

## Key Reference Links

- Strix Halo Wiki: https://strixhalo.wiki/AI/AI_Capabilities_Overview
- vLLM on Strix Halo: https://strixhalo.wiki/AI/vLLM
- Build recipes: https://github.com/paudley/ai-notes/tree/main/strix-halo
- Docker toolboxes: https://strix-halo-toolboxes.com
- Performance benchmarks: https://kyuz0.github.io/amd-strix-halo-toolboxes/
