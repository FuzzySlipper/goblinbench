# Pi/Lemonade coding-agent runs: prefer JSON event mode

Session learning from GoblinBench local-Qwen runs through `@earendil-works/pi-coding-agent` against a Lemonade OpenAI-compatible server.

## Symptom

A GoblinBench coding scenario using pi with Lemonade/Qwen and `--mode text` repeatedly exited with code `137` after about 20 seconds when launched by the normal C# runner. The same workspace and bwrap command could complete when driven manually, making the first-order suspects (host OOM, scenario timeout, bwrap launch failure) misleading.

## Isolation pattern

1. Confirm scenario timeout in the parsed scenario object, not just in JSON.
2. Capture the bwrap argv from the runner trace and replay it manually.
3. Compare three launch paths:
   - direct pi outside bwrap,
   - pi inside copied/replayed bwrap argv,
   - normal harness runner.
4. If text mode exits 137 but manual/bwrap paths work, try pi `--mode json` before deeper infrastructure surgery.
5. Preserve full stdout/stderr as artifacts, not as a full inline `run.json` payload; pi JSON mode can emit multi-megabyte event streams.

## Practical candidate shape

For GoblinBench pi/Lemonade candidates, prefer:

```json
{
  "cli_args": [
    "--print",
    "--no-session",
    "--no-extensions",
    "--extension", "/home/dev/goblinbench/scripts/lemonade-pi-extension.js",
    "--provider", "lemonade",
    "--model", "Qwen3.6-35B-A3B-GGUF",
    "--mode", "json"
  ]
}
```

Keep the Lemonade extension as the provider registration path; pi does not expose a generic `--base-url` flag for this use case.

## Artifact guidance

- Write full event stream to `stdout.log` / `stderr.log` in the candidate artifact directory.
- Keep only a bounded tail and stream length in `output.json` / `run.json`.
- Treat partial patches from killed agents as runner-health failures even when scorer partial credit is nonzero.

## Related sandbox footgun

If bwrap starts from a read-only host root (`--ro-bind / /`), add a fresh device mount (`--dev /dev`) before binding the workspace. Otherwise `/dev/null` may be visible but not writable in the namespace, causing strange subprocess failures such as `Permission denied` on shell redirection or Node spawn stdio setup.
