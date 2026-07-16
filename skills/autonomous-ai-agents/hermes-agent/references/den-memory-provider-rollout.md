# Den-backed Hermes memory rollout pattern

Use this reference when enabling a downstream/Den-owned Hermes memory provider for a limited set of profiles. The reusable lesson is staged activation with worker isolation and manual-only behavior, not the exact task IDs or commit hashes.

## Ownership boundary

- Keep the upstream Hermes checkout clean: the Den provider code belongs in a Den-owned repo/plugin/overlay, not in `NousResearch/hermes-agent` source.
- Install Den-owned code to a durable shared runtime path and symlink it into each target profile's `plugins/` directory.
- Configure profile `plugins.enabled`/memory provider settings rather than hand-editing upstream package internals.

## Guinea-pig rollout gates

1. **Preserve before changing**
   - Back up target profile configs before editing.
   - Record the shared runtime install path and live facade URL in a repo/Den doc.
2. **Manual-only trial**
   - Enable the Den memory provider only for named guinea-pig profiles.
   - Set `deny_auto_behavior: true` during the trial so automatic memory ingestion, prefetch, or summarization stays blocked unless explicitly authorized.
3. **Explicit space mapping**
   - Configure profile-specific assistant spaces and, when useful, a shared knowledge-base smoke space.
   - Do not let a profile read/write broad project/global spaces by default.
4. **Worker isolation**
   - Audit spawned/worker profiles after rollout and verify they remain zero-memory.
   - Treat worker memory enablement as a separate opt-in task, not an accidental inheritance from profile templates.
5. **Clean/simulated-clean validation**
   - Verify from the upstream Hermes runtime plus the Den-owned install path, not only from a dirty development tree.
   - Run focused provider/installer tests, full relevant tests, live facade smoke, and gateway restart/status checks.
6. **Observation loop**
   - Schedule dry-run curation/observation reports for the trial window.
   - Reports should classify memory entries and recommend next gates without mutating memory during the manual-only phase.

## Config shape

Typical profile config during the guinea-pig stage:

```yaml
plugins:
  enabled:
    - den

memory:
  provider: den

den_memory:
  enabled: true
  deny_auto_behavior: true
  rest:
    base_url: http://<den-core-host>/den-core-api
  read_spaces:
    - assistant:<profile>
  write_spaces:
    - assistant:<profile>
```

## Verification checklist

- Installer is idempotent and safe to rerun after `hermes update` or profile recreation.
- Target profile plugin symlinks point to the shared Den-owned install path.
- Only the intended guinea-pig profiles have `memory.provider: den`.
- Spawned/worker profiles have no memory provider/read/write spaces enabled.
- Live Den memory facade returns healthy status.
- Gateway services restart cleanly and remain active.
- Dry-run curation jobs are scheduled with self-contained prompts and no mutation authority.
