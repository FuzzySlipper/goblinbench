# Hermes Den Channels plugin runtime hotfix and restart pattern

Use this reference when a Den-owned Hermes platform plugin bug is fixed in the shared plugin runtime and running gateway services must reload it.

## Scope

This applies to native Hermes gateway profiles that have `plugins.enabled` containing `platforms/den_channels` and/or `platforms.den_channels.enabled: true`. Ambassador-only tools are not the same as native delivery consumers.

## Runtime/source paths

Common paths on den-k8/den-k8plus:

- Durable source repo: `/home/dev/den-hermes/plugins/platforms/den_channels/adapter.py`
- Shared runtime plugin: `/home/agents/runtime/den-hermes-plugins/platforms/den_channels/adapter.py`
- Profile plugin path: `/home/agents/profiles/<profile>/plugins/platforms/den_channels/adapter.py`

Before copying source over runtime, compare source/runtime. The live shared runtime can contain intentional runtime-only patches from recent Den tasks. If they differ, do not blindly run the installer or overwrite runtime; reconcile or apply a minimal hotfix to both places.

## Detect profiles that need restart

Use profile config, not process name alone, to find native Den Channels consumers:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml, subprocess
active=set()
out=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'], text=True)
for line in out.splitlines():
    unit=line.split()[0]
    if unit.startswith('hermes-gateway@') and unit.endswith('.service'):
        active.add(unit[len('hermes-gateway@'):-len('.service')])
for cfg in sorted(Path('/home/agents/profiles').glob('*/config.yaml')):
    profile=cfg.parent.name
    if profile not in active:
        continue
    data=yaml.safe_load(cfg.read_text()) or {}
    plugins=(data.get('plugins') or {}).get('enabled') or []
    if isinstance(plugins, str):
        plugins=[plugins]
    platforms=data.get('platforms') or {}
    dc=platforms.get('den_channels') if isinstance(platforms, dict) else None
    if 'platforms/den_channels' in plugins or (isinstance(dc, dict) and dc.get('enabled') is True):
        print(profile)
PY
```

## Restart pattern

Restart active native consumers after changing the shared adapter:

```bash
for profile in <profiles>; do
  systemctl --user restart "hermes-gateway@${profile}.service"
done
sleep 3
for profile in <profiles>; do
  systemctl --user is-active "hermes-gateway@${profile}.service"
done
```

If only one recipient is being smoked, restart that profile first, run the smoke, then restart the remaining native consumers once the hotfix is proven.

## Verification

- Run the adapter/unit regression from the source repo.
- Import the live runtime adapter directly in a small Python smoke if the runtime was hotfixed outside source.
- Run installer verification for at least one representative profile:

```bash
python scripts/install_den_channels_plugin.py --verify-only \
  --profile den-mcp-planner \
  --shared-root /home/agents/runtime/den-hermes-plugins \
  --hermes-runtime-root /home/agent/.hermes/hermes-agent
```

- For delivery bugs, send a live direct-agent message to the target profile and verify the receiving profile session DB or channel reply, not just the Channels event readback.

## Pitfall: event readback green, receiving agent still wrong

For direct-agent message text issues, Channels event readback may be correct (`body` is human text, `summary` is generated evidence) while the Hermes adapter still maps `summary` into `MessageEvent.text`. Always verify the receiving Hermes profile's actual session/message, not only the Channels event payload.