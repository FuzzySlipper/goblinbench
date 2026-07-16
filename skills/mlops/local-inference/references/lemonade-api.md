# Lemonade Server API Reference

Condensed from https://lemonade-server.ai/docs/ and live instance testing.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/chat/completions` | Chat completions (auto-loads model) |
| POST | `/v1/completions` | Text completions |
| POST | `/v1/embeddings` | Embeddings |
| POST | `/v1/responses` | Responses API |
| POST | `/v1/audio/transcriptions` | Whisper STT |
| POST | `/v1/audio/speech` | Kokoro TTS |
| POST | `/v1/images/generations` | SD image gen |
| POST | `/v1/images/edits` | Image editing |
| POST | `/v1/images/variations` | Image variations |
| POST | `/v1/images/upscale` | ESRGAN upscaling |
| GET | `/v1/models` | List downloaded models |
| GET | `/v1/models?show_all=true` | List all catalog models |
| GET | `/v1/models/{id}` | Get model details |
| GET | `/v1/health` | Server status + loaded models |
| WS | `/realtime` | Realtime audio transcription |

## Key Behaviors

- **Auto-loading**: Any `/v1/*` endpoint loads the requested model if not already loaded
- **Auto-unloading**: Only 1 LLM, 1 image, 1 audio, 1 embedding model loaded at a time
- **Model names**: Use the `id` field from `/v1/models` (e.g. `Qwen3.6-27B-GGUF`)
- **Recipe**: Models use backends like `llamacpp` (vulkan/rocm/cpu), `flm` (NPU), `whispercpp`, `sd-cpp`
- **Context size**: Configurable per model, visible in health endpoint `recipe_options.ctx_size`

## Health Endpoint Response

```json
{
  "status": "ok",
  "version": "10.3.0",
  "model_loaded": "Qwen3.6-27B-GGUF",
  "max_models": {"llm": 1, "audio": 1, "embedding": 1, "image": 1},
  "all_models_loaded": [
    {
      "model_name": "Qwen3.6-27B-GGUF",
      "backend_url": "http://127.0.0.1:8001/v1",
      "recipe": "llamacpp",
      "recipe_options": {"ctx_size": 200000, "llamacpp_backend": "vulkan"},
      "device": "gpu"
    }
  ],
  "websocket_port": 9000
}
```

## Chat Completions Request

```json
{
  "model": "Qwen3.6-27B-GGUF",
  "messages": [{"role": "user", "content": "Hello"}],
  "stream": false,
  "max_tokens": 1024,
  "temperature": 0.7
}
```

Supported params: `messages`, `model`, `stream`, `stop`, `temperature`, `repeat_penalty`, `top_k`, `top_p`, `tools`, `max_tokens`, `max_completion_tokens`

## Model Labels

Labels from `/v1/models` indicate capabilities:
- `hot` — suggested/recommended
- `tool-calling` — supports function calling
- `vision` — supports image input
- `coding` — optimized for code generation
- `reasoning` — reasoning/thinking models
- `image` — image generation models
- `audio`, `transcription` — audio models

## CLI Commands

```bash
lemonade list              # List available models
lemonade pull MODEL        # Download a model
lemonade run MODEL         # Load model and start chat
lemonade launch claude     # Start Claude Code integration
lemonade backends          # Show available backends
```

## Web UI

Root URL serves a Tauri-based web app (also works in browser). Features:
- Model Manager (download, browse catalog)
- Built-in chat interface
- Image generation
- Speech generation
- Logs viewer

## Performance Benchmarks (observed on Strix Halo 128GB)

- Qwen3.6-27B-GGUF Q4: ~12 tok/s generation, ~9.5 tok/s prompt processing
- Model load time: ~3-5 seconds
- 200k context window
