# Downstream overlays and upstreamable Hermes patches

Use this reference when a local Hermes runtime contains both generic fixes and deployment-/product-specific behavior. The goal is to preserve the live runtime, keep upstream PRs clean, and move downstream behavior into a durable plugin/overlay owned outside `NousResearch/hermes-agent`.

## Pattern

1. Preserve the live runtime before editing it:
   - record `git rev-parse HEAD`, `git status --short`, remotes, and relevant config paths;
   - export a patch series/bundle for local commits and dirty diffs;
   - store artifacts under a durable runtime/overlay archive, not only in `/tmp`.
2. Classify local changes into lanes:
   - **Generic upstreamable Hermes fixes**: small PR-shaped patches that make sense in upstream Hermes with no Den/product-specific code bundled in.
   - **Downstream-owned overlays/plugins**: adapters, delivery contracts, profile glue, service integration, or operational behavior that belongs to the downstream system.
3. Move downstream code to the downstream repo or shared plugin root. Prefer a single source-of-truth install path symlinked into Hermes profile plugin directories over copying per profile.
4. Add an idempotent installer that:
   - creates/updates the shared plugin path;
   - links it into each target profile's plugin directory;
   - enables the plugin in `config.yaml` without duplicating entries;
   - is safe to rerun after `hermes update` or profile recreation.
5. Validate with a clean or simulated-clean upstream Hermes checkout plus the downstream install path. Do not rely on the currently mutated runtime as proof.
6. Restart affected gateway/services and verify the plugin registers and completes one live or fake delivery end-to-end.
7. Document which generic commits remain upstreamable/local-overlay work until upstream or the current runtime includes them.

## Den/Hermes example

For the Den Channels extraction, the durable model was:

- generic upstreamable lane: `discord.allow_bots` config bridge, kept as a narrow patch independent of Den Channels code;
- Den-owned lane: `den_channels` platform adapter and Den-specific gateway delivery/context/status behavior moved to the Den-owned bridge repo/plugin path;
- shared install path: `/home/agents/runtime/den-hermes-plugins/platforms/den_channels`;
- profile plugin entries symlink to the shared install path;
- clean-room validation used upstream Hermes plus the Den-owned plugin path, then live gateway restarts and a direct-agent delivery smoke.

The important reusable lesson is the ownership boundary, not the exact task IDs: upstream Hermes should receive generic framework improvements; downstream adapters and deployment contracts should live in downstream-owned plugins/overlays with a repeatable installer and clean-checkout validation.
