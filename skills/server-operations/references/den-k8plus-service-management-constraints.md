# den-k8plus Service Management Constraints

The `agent` user on den-k8plus has constrained systemd/sudo access
that affects how services are deployed, started, stopped, and checked.

## Sudo capabilities for the `agent` user

Verified via `sudo -l -U agent`:

| Operation | Allowed? | How |
|-----------|----------|-----|
| `systemctl status UNIT...` | YES (NOPASSWD) | `sudo /usr/bin/systemctl status *` |
| `systemctl show UNIT...` | YES (NOPASSWD) | `sudo /usr/bin/systemctl show *` |
| `systemctl cat UNIT...` | YES (NOPASSWD) | `sudo /usr/bin/systemctl cat *` |
| `systemctl list-units` | YES (NOPASSWD) | `sudo /usr/bin/systemctl list-units` |
| `journalctl` | YES (NOPASSWD) | `sudo /usr/bin/journalctl` |
| `systemctl restart/reload UNIT` | YES (NOPASSWD) | Via `/usr/local/sbin/agent-service restart UNIT` |
| `systemctl start UNIT` | **NO** | Not in sudoers |
| `systemctl stop UNIT` | **NO** | Not in sudoers |
| `systemctl disable UNIT` | **NO** | Not in sudoers |
| `systemctl enable UNIT` | **NO** | Not in sudoers |
| `systemctl daemon-reload` | YES (NOPASSWD) | Via `/usr/local/sbin/agent-systemctl-daemon-reload` |
| Install service file to `/etc/systemd/system/` | **NO** | Cannot write root-owned paths |

## What `agent-service` supports

The helper at `/usr/local/sbin/agent-service` wraps `systemctl` and
validates input, but only allows these actions: `reload`, `restart`,
`try-restart`. No `start`, `stop`, `status`, `enable`, `disable`.

Unit name validation: rejects names with slashes, dashes, or special
chars beyond `[A-Za-z0-9@_.:-]`.

## Working around these constraints

### Service deployment pattern

Since the agent user cannot write to `/etc/systemd/system/` or start
systemd services directly, use one of:

1. **Background process** — run the binary via `terminal(background=true)`
   with `notify_on_complete=false` (server/daemon pattern). The process
   is not supervised by systemd and will not survive reboot. Restart it
   after session interruptions or gateway failures.

2. **systemd --user service** — if the agent user's systemd --user
   instance is available (`loginctl enable-linger agent`), write unit
   files to `~/.config/systemd/user/` and manage with
   `systemctl --user start/stop/restart`.

3. **File a systemd unit request** — write the unit file to a temp
   location and note that it requires root to install to
   `/etc/systemd/system/`. Escalate via Den Channels/sysadmin.

### Checking service status

```bash
# Individual service
sudo systemctl status den-host.service --no-pager -l 2>/dev/null

# List running Den services
sudo systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null | grep -E 'den-|fleetops'

# Check if a specific service is active
sudo systemctl is-active den-host.service 2>/dev/null
```

### Restarting a service

```bash
# Using the verified helper (NOPASSWD)
sudo /usr/local/sbin/agent-service restart den-host

# After daemon-reload (when unit files changed)
sudo /usr/local/sbin/agent-systemctl-daemon-reload
sudo /usr/local/sbin/agent-service restart den-host
```

## Machine context

- den-k8plus is an Arch Linux machine running the main Den fleet
  control plane (den-host, SSH tunnels to den-srv).
- Den Core and den-channels run on den-srv (192.168.1.10), not locally.
  Services named den-core.service and den-channels.service do not
  exist on den-k8plus. FleetOps smoke checks should check
  den-host.service and fleetops (the local services), not remote ones.
- Systemd user units for den-gateway (historical) exist under the
  den-mcp-runner profile's home: `~/.config/systemd/user/den-gateway.service.d/override.conf`.
