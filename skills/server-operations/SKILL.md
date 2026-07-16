---
name: server-operations
description: "Use when administering shared servers for Hermes/agent work: access-control changes, audited agent accounts, SSH/sudo policy, rootless Docker runtimes, compose migrations, host services, and operational rollback."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [devops, sysadmin, server-administration, sudo, ssh, docker, rootless-docker, compose, auditing, rollback]
    related_skills: [hermes-deployment, den-mcp]
---

# Server Operations

## Overview

Use this umbrella skill for hands-on administration of shared LAN or production-like servers where Hermes/agents may need durable operational access, audited privilege boundaries, Docker/runtime changes, or app-stack migrations. Treat these tasks as governed server operations, not isolated command snippets: define scope, preserve rollback, avoid surprise privilege escalation, and verify from the account or service that will actually run the workload.

This skill consolidates two recurring classes:

1. **Agent access and privilege setup** — dedicated `agent` accounts, SSH keys, constrained sudoers, helper wrappers, break-glass sudo, smoke tests, and rollback.
2. **Rootless Docker operations** — shared rootless daemons, Docker contexts/sockets, compose migrations, bind-mount permissions, device access, host-service interactions, and recovery rules.

Session-specific runbooks and templates live in `references/` and `templates/`; keep this SKILL.md as the class-level operating model.

## When to Use

- Preparing a server for agent-administered work or reconciling an existing `agent` account.
- Designing, reviewing, or deploying SSH key access, sudoers policy, or root-owned helper wrappers.
- Making privileged changes to users, groups, SSH, sudo, systemd services, sysctls, udev rules, filesystem ownership/modes, Docker sockets, or compose stacks.
- Administering rootless Docker: shared socket access, contexts, daemon user/group membership, compose migrations, rootless permission/device failures, or backup hooks.
- You need an auditable plan with verification and rollback before touching shared infrastructure.

Do **not** use this skill to bypass security review. Docker socket access, sudoers changes, udev rules, and broad filesystem permission changes all require explicit scope and approval when they alter durable authority.

## Universal Governance Pattern

Before non-trivial server changes, write a concise plan:

1. **Intent** — what operational problem is being solved.
2. **Scope** — host, accounts, groups, files, services, sockets, data roots, and compose directories affected.
3. **Expected changes** — exact auth, privilege, Docker/runtime, network, or filesystem surfaces to change.
4. **Verification** — syntax checks, dry-runs, smoke tests, service logs, HTTP/port checks, and negative checks where useful.
5. **Rollback** — files to restore/remove, groups to revert, services to restart, containers to stop/start, keys to revoke.
6. **Escalation points** — broad sudo, root-owned files, secrets, sysctls, udev, firewall/routing, live backups, destructive data migration, or permissions on broad media/personal trees.

Ask for approval before deploying anything that changes users, groups, authentication, sudoers, system services, sysctls, udev rules, broad filesystem permissions, firewall/routing, or durable app data.

## Class 1: Agent Access and Privilege Setup

### Default posture

- Prefer a dedicated `agent` account for auditability.
- Prefer a dedicated agent SSH keypair over reusing the user's personal key.
- Generate the private key as the local account/profile that will run SSH, not as root; install only the public key on the target.
- Lock the password by default unless a deliberate break-glass path is chosen.
- Keep supplementary groups minimal (`adm`, `systemd-journal` where useful); avoid root-equivalent groups such as `docker`, `lxd`, or `libvirt` unless explicitly justified.
- Routine passwordless sudo should be constrained to read-only inspection and root-owned helper wrappers.
- Avoid `NOPASSWD:ALL`; allow it only as an explicit, time-bounded break-glass repair mode when non-interactive agent work is safer than repeated human copy/paste.

### Discovery before changing an existing host

If the host may already have an `agent` account or sudoers policy, audit and reconcile instead of blindly rerunning setup:

```bash
id agent || true
getent passwd agent || true
getent group agents || true
stat -c '%A %U:%G %n' ~agent ~agent/.ssh ~agent/.ssh/authorized_keys 2>/dev/null || true
sudo -l -U agent 2>/dev/null || true
sudo -u agent sudo -n true 2>/dev/null && echo sudo-ok || echo sudo-not-ok
```

Inspect existing `/etc/sudoers.d/*agent*` only when authorized; reading root-only sudoers is itself a privileged action.

### SSH pattern

Create the local key as the agent client identity:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/<target>-agent_ed25519 \
  -C "<source-host> <profile> Hermes agent -> <target> agent" -N ""
chmod 600 ~/.ssh/<target>-agent_ed25519
chmod 644 ~/.ssh/<target>-agent_ed25519.pub
ssh-keygen -lf ~/.ssh/<target>-agent_ed25519.pub
ip route get <target-ip>   # find src <source-ip> for optional authorized_keys from= restriction
```

On the target, install `~agent/.ssh` as `0700 agent:agents` and `authorized_keys` as `0600 agent:agents`; use `from="<source-ip>"` restrictions when practical.

### Sudoers and helpers

Use a validated `/etc/sudoers.d/90-agent-sudo-user` drop-in with explicit `Defaults:agent`, `secure_path`, and sudo logging where supported. Prefer root-owned helper scripts in `/usr/local/sbin/agent-*` for mutation:

- `agent-apt-update`
- `agent-apt-install PACKAGE...` with package-name validation and no arbitrary flags
- `agent-systemctl-daemon-reload`
- `agent-service ACTION UNIT...` for limited actions and validated unit names
- `agent-tail-log /var/log/FILE` bounded to `/var/log/*`

Validate before installation:

```bash
bash -n setup-agent-sudo-user.sh
visudo -cf agent-sudoers.conf
```

After deployment:

```bash
id agent
stat -c '%A %U:%G %n' ~agent ~agent/.ssh ~agent/.ssh/authorized_keys
visudo -cf /etc/sudoers.d/90-agent-sudo-user
ssh -i ~/.ssh/<target>-agent_ed25519 -o BatchMode=yes agent@<host> 'id && hostname'
ssh -i ~/.ssh/<target>-agent_ed25519 -o BatchMode=yes agent@<host> 'sudo -n whoami'
```

Rollback: remove the sudoers drop-in, lock the account, and clear/revoke SSH keys.

## Class 2: Rootless Docker Operations

### Shared runtime pattern

A maintainable shared rootless Docker runtime usually has:

- A dedicated daemon user, e.g. `docker-rt`.
- A dedicated access group, e.g. `docker-rt-users` or a fleet-specific group.
- A shared socket path outside a login session, e.g. `/run/<service>/docker-rt/docker.sock`.
- Socket permissions `srw-rw---- runtime-user:access-group` and directory traversal permissions for that group.
- Explicit Docker contexts for humans and explicit `DOCKER_HOST=unix:///.../docker.sock` for services.

Example:

```bash
docker context create shared-rootless \
  --description 'Shared rootless Docker runtime' \
  --docker 'host=unix:///run/<service>/docker-rt/docker.sock'
docker context use shared-rootless
docker version
```

### Discovery checklist

```bash
id <runtime-user>
id <consumer-user>
stat -c '%A %U:%G %n' /run/<service> /run/<service>/docker-rt /run/<service>/docker-rt/docker.sock
sudo -u <consumer-user> docker context ls
sudo -u <consumer-user> env | grep -E '^DOCKER_|^XDG_RUNTIME_DIR=' || true
sudo -u <consumer-user> env DOCKER_HOST=unix:///run/<service>/docker-rt/docker.sock docker version
```

For compose stacks, render config without dumping secrets, inventory services/images/ports/mounts/devices, and start one stack at a time.

### Migration principles

- Prefer bind mounts over Docker named volumes so data location is obvious and backup/recovery is simpler.
- Never copy an entire old Docker data root into a live rootless data root. Recover only the specific images/volumes/data directories needed.
- Back up compose files, `.env`, and small config files before edits.
- Classify risky stacks separately: `privileged`, `network_mode: host`, `cap_add`, `/dev/net/tun`, GPU/USB devices, broad host mounts, backup services, or low host ports.
- Stop/remove restart loops while investigating to reduce log spam and avoid repeated destructive entrypoint behavior.

### Rootless permission model

Rootless Docker maps container UIDs through the daemon user's user namespace:

- Container UID `0` maps to the rootless daemon's host user, not host root.
- Container UID `1000` may map to a subuid range, not host UID `1000`; read `/proc/<dockerd-or-rootlesskit-pid>/{uid_map,gid_map}` before calculating.
- LinuxServer-style `PUID=1000` / `PGID=1000` patterns often need review; for rootless-friendly apps, `PUID=0` / `PGID=0` or `user: "0:0"` can map writes to the runtime user, but some apps refuse to run as root inside the container.

For app-local bind mounts, prefer narrow group/setgid permissions:

```bash
sudo chgrp -R <docker-access-group> /data/docker/<stack>
sudo chmod -R g+rwX /data/docker/<stack>
sudo find /data/docker/<stack> -type d -exec chmod g+s {} +
```

Do not recursively change multi-terabyte media/personal trees or broad host paths without explicit approval. Use controlled container write probes first.

### Common rootless failures

- **Stale user socket:** `failed to connect ... /run/user/<uid>/docker.sock` means the selected context points at a dead personal rootless daemon; switch to the intended shared context or set `DOCKER_HOST`.
- **Bind mount permission denied:** check host path ownership/modes and container effective UID/GID under the rootless map.
- **Entrypoint chown loops:** rootless cannot chown arbitrary bind-mounted host files; configure the image to skip chown, adjust UID/GID, pre-adjust permissions, or choose a rootless-friendly image.
- **Privileged ports:** rootless cannot bind below the unprivileged threshold unless a system-level policy such as `net.ipv4.ip_unprivileged_port_start` is deliberately changed.
- **Devices/TUN/GPU/USB:** verify host permissions, runtime-user permissions, container userspace support, and app-level health. Narrow udev rules for render nodes or specific USB VID/PID are preferable to broad device exposure.
- **Host-level backup services:** do not move broad host backup tools into rootless Docker casually. A host systemd service with explicit `DOCKER_HOST` pre/post hooks may be safer.

## Documentation and Knowledge Capture

For significant server operations, document:

- datetime and target host;
- access/runtime model;
- files installed/changed;
- privilege or socket access granted;
- compose/services/data paths affected;
- verification result;
- rollback path;
- follow-up risks.

Prefer class-level updates in this SKILL.md for repeated lessons. Put specific host migrations, API excerpts, command transcripts, and reproduction recipes under `references/`. Put reusable scripts under `scripts/` or `templates/`.

## Supporting Files

- `templates/setup-agent-sudo-user.sh` — reviewed starter for `agent` user, SSH directory, helper scripts, and validated sudoers drop-in.
- `references/agent-server-access.md` — detailed source notes from the former dedicated access skill, including den-srv prep decisions.
- `references/rootless-docker-operations.md` — detailed source notes from the former rootless Docker skill, including den-srv migration findings.
- `references/den-srv-agent-sudo-access-prep.md` — preserved session reference from the old access skill.
- `references/den-srv-docker-rt-migration-2026-05.md` — preserved session reference from the old rootless Docker skill.
- `references/static-frontend-service-cutover.md` — standalone static frontend service cutover checklist: build sentinel/runtime config, systemd service split, API proxy smoke tests, old embedded UI retirement, and rollback evidence.
- `references/den-web-static-deploy-and-gateway-routing.md` — Den Web-specific static deploy notes: sentinel caching/restart behavior, root backup + rsync pattern, smoke commands, and `/api/gateway/*` route-collision pitfall when adding separate den-gateway APIs.
- `references/den-web-channels-gateway-decommission-deploy.md` — Gateway-decommission deploy/smoke notes: stale build sentinel after rsync may need `den-web.service` restart, `/den-gateway-api/fleet-ops` 502 is a known legacy caveat, and Den Web membership freshness should be backed by Den Channels lifecycle/grace projections.
- `references/den-core-live-capability-route-smoke.md` — Den Core live route recovery and capability executor smoke pattern: detect stale `/den-core-api` deployments, use the owned deploy script, preserve rollback path, invoke/read back capability calls, and disable temporary executor registrations after smoke.
- `references/den-k8plus-service-management-constraints.md` — constrained systemd/sudo capabilities for the `agent` user on den-k8plus: what `sudo systemctl` operations are available, the `agent-service` wrapper limitations, service deployment workarounds, and local service discovery.
- `references/hermes-den-channels-plugin-runtime-restart.md` — operational pattern for hotfixing the shared Den Channels Hermes plugin runtime, detecting native `platforms/den_channels` gateway profiles, restarting them via user systemd, and verifying the receiving Hermes session rather than only Channels event readback.

## Common Pitfalls

1. Treating access setup as a script run rather than an access-control design review.
2. Granting broad `NOPASSWD:ALL` or Docker group/socket access without time bounds and rollback.
3. Reading root-only config or sudoers files without acknowledging that the read is a privileged escalation.
4. Assuming an account, sudoers drop-in, Docker context, or compose stack is absent; audit existing state first.
5. Copying old Docker data roots wholesale into a live daemon.
6. Guessing rootless UID/GID mappings instead of reading the active `uid_map`/`gid_map`.
7. Applying recursive permission fixes to broad media, backup, or personal trees when only app-local bind mounts needed changes.
8. Confusing container image/userspace incompatibility with Docker/rootless failure; inspect internal logs and test candidate images.
- Forgetting that host services such as backup tools may intentionally stay outside Docker even during Docker migrations.
- **Assuming a systemd service exists on the current machine:** Service names like `den-core.service` and `den-channels.service` run on den-srv (192.168.1.10), not on den-k8plus (the agent fleet machine). Before writing smoke checks, status commands, or FleetOps action templates that reference a service, verify it exists locally with `sudo systemctl list-units --type=service | grep <pattern>` or check the known machine topology. A smoke test that checks for non-local services will always report "failed" on den-k8plus.
11. Treating a green service health check as proof that newly merged API routes are live. Compare `/health` commit metadata with the expected repo head, then smoke the exact client-facing route path. If a new route returns the SPA fallback or `405`, suspect stale deployment or proxy/static fallback before debugging the feature code.
12. Leaving a live registry/config entry pointing at a temporary smoke-test process. For capability/executor smokes, disable or revert the registry entry after the invocation readback unless the executor is supervised and intended to remain running.
13. For Den Web static deploys, assuming rsyncing `wwwroot` refreshes every served artifact. If `den-web-build.json` on disk has the expected commit but HTTP still returns an old sentinel, restart `den-web.service`, wait for port 18080, and rerun the smoke before diagnosing the build.
14. During Den Gateway decommissioning, treating known legacy `/den-gateway-api/*` 502 failures as proof that new direct Core/Channels work failed. Separate legacy Gateway caveats from direct `/api/*` Channels, `/den-core-api/*` Core, static root, and exact feature-route smokes.

## Verification Checklist

- [ ] A plan states intent, scope, expected changes, verification, rollback, and escalation points.
- [ ] Existing server state was audited before applying setup scripts or compose changes.
- [ ] SSH/sudo/Docker/context changes were tested from the intended user or service account.
- [ ] Syntax checks passed for scripts, sudoers, compose files, systemd units, sysctl/udev snippets, or hooks as applicable.
- [ ] Logs and health checks were reviewed after changes.
- [ ] Secrets were not dumped into transcripts or notes.
- [ ] Rollback artifacts exist and were named in the summary.
- [ ] Session-specific details were saved to `references/` rather than spawning a new narrow skill.
