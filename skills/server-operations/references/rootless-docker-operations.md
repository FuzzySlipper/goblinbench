---
name: rootless-docker-operations
description: "Use when administering Docker rootless mode for shared runtimes, app-stack migrations, compose projects, bind mounts, Unix sockets, and rootless-specific permission/device/port failures."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [docker, rootless-docker, compose, devops, permissions, migration]
    related_skills: [agent-server-access, hermes-deployment]
---

# Rootless Docker Operations

## Overview

Use this skill for Docker rootless-mode administration where the daemon runs as a non-root service user and other users or services access it through an explicitly shared Unix socket. The main operational difference from rootful Docker is that the Docker socket is no longer equivalent to host-root, but it is still powerful authority over that daemon's containers, networks, images, and mounted data.

Prefer durable, reviewable setups: a dedicated runtime user, a named access group, explicit `DOCKER_HOST`/Docker contexts, bind mounts with clear filesystem locations, and per-stack migration notes. Avoid copying opaque Docker/containerd internals between data roots unless doing a carefully staged offline recovery.

## When to Use

- A rootless Docker daemon is failing or needs to be shared with another Unix user/service.
- `docker compose` points at a stale socket such as `/run/user/<uid>/docker.sock`.
- Migrating compose stacks from rootful Docker or one rootless user to another.
- Recovering stacks with bind mounts or named volumes under a new rootless runtime.
- Debugging rootless-specific failures: permission denied on bind mounts, privileged port binding, device mounts, `chown` failures, TUN/GPU/USB access, or container UID/GID mapping surprises.

Do **not** use this skill as a substitute for container security review. A user with access to a shared rootless Docker socket can still control that runtime and containers using its mounted data.

## Governance Plan Before Changes

For any non-trivial rootless Docker change, state a short plan before acting:

- **Intent:** what runtime or stack is being repaired/migrated.
- **Scope:** affected host, runtime user, access group, socket, data root, compose directories.
- **Expected changes:** users/groups, Docker contexts, container/image/network creation, file ownership/mode changes, compose edits.
- **Verification:** `docker version`, `docker ps`, `docker compose config`, service logs, port/HTTP checks.
- **Rollback:** `docker compose down`, restore backed-up compose/env/config files, remove group membership or Docker context.
- **Escalation:** ask before changing systemd units, sysctls, broad filesystem permissions, firewall/routing, durable data, or privileged/device-heavy stacks.

## Shared Rootless Runtime Pattern

A maintainable shared rootless runtime usually has:

- Dedicated daemon user, e.g. `docker-rt`.
- Dedicated access group, e.g. `den-pi-docker` or `docker-rt-users`.
- Shared socket path outside a login session, e.g. `/run/<service>/docker-rt/docker.sock`.
- Socket permissions `srw-rw---- runtime-user:access-group`.
- Directory permissions allowing traversal by the access group.
- Interactive/admin users and service accounts added only to that access group when appropriate.
- Per-user Docker contexts pointing at the socket.

Example context setup for an interactive user:

```bash
docker context create den-docker-rt \
  --description 'Shared rootless Docker runtime' \
  --docker 'host=unix:///run/den-mcp/docker-rt/docker.sock'
docker context use den-docker-rt
docker version
docker compose version
```

For services, prefer explicit environment:

```bash
DOCKER_HOST=unix:///run/den-mcp/docker-rt/docker.sock docker ps
```

## Discovery Checklist

Before changing anything, inspect:

```bash
id <runtime-user>
id <service-user>
id <interactive-user>
stat -c '%A %U:%G %n' /run/... /run/.../docker.sock
sudo -u <user> docker context ls
sudo -u <user> env | grep -E '^DOCKER_|^XDG_RUNTIME_DIR=' || true
sudo -u <runtime-consumer> env DOCKER_HOST=unix:///path/to/docker.sock docker version
sudo -u <runtime-consumer> docker --context <context> version
```

For compose stacks:

```bash
find /data/docker -path '*/old/*' -prune -o \
  \( -name compose.yaml -o -name compose.yml -o -name docker-compose.yml -o -name docker-compose.yaml \) -print

cd /path/to/stack
docker compose config >/tmp/stack.rendered.yaml   # avoid printing secrets to transcript
```

Inspect metadata without dumping `.env` secrets: list services, images/builds, ports, mounts, `network_mode`, `privileged`, `devices`, `cap_add`, and named volumes.

## Migrating Compose Stacks to Rootless Docker

Use staged migration. Do not bring everything up at once.

1. **Inventory stacks** and ignore explicit backup/old directories.
2. **Render compose config** to validate syntax/interpolation without starting containers.
3. **Classify risk:**
   - Simple bind-mount web apps first.
   - Named-volume stacks need a conversion/import plan.
   - Device/TUN/privileged/broad-backup stacks need individual plans.
4. **Back up config before edits:** compose files, `.env`, small app config files.
5. **Start one stack at a time:**
   ```bash
   cd /data/docker/<stack>
   docker compose up -d
   docker compose ps
   docker compose logs --tail=100
   ```
6. **Smoke test:** HTTP status, listening ports, healthchecks, app logs.
7. **Document result:** what changed, verification, blockers, rollback.

## Bind Mounts Preferred

For this user's infrastructure, prefer bind mounts over Docker named volumes. Bind mounts make data location obvious and simplify backup/recovery. If upstream compose files use named volumes, consider converting them to explicit directories under the stack directory or another intentional `/data/...` path.

Before conversion, map effective names. Compose prefixes unnamed volumes with the project name, which may come from top-level `name:` rather than the directory:

```yaml
name: lobehub
volumes:
  redis_data:
  rustfs-data:
```

Expected Docker volume names:

```text
lobehub_redis_data
lobehub_rustfs-data
```

If preserving state, copy/export only the specific volumes needed; do not merge an entire old Docker data root into the live rootless data root.

## Rootless Permission Model

Rootless Docker is not rootful Docker with a smaller hat. Container UIDs map through the runtime user's user namespace.

Important implications:

- Container UID `0` maps to the rootless daemon's host user, e.g. `docker-rt`, **not host root**.
- Container UID `1000` does **not** necessarily map to host UID `1000`; it may map to a subuid such as `165536 + 999` depending on the daemon's `uid_map`.
- Do not guess the offset. Read `/proc/<dockerd-or-rootlesskit-pid>/{uid_map,gid_map}` and calculate from the actual rows. A common map is `0 <daemon-host-uid> 1` plus `1 <subuid-start> 65536`, which means container UID 1000 maps to `subuid-start + 999`, not `subuid-start + 1000`.
- Old `PUID=1000` / `PGID=1000` patterns from LinuxServer-style images can break under a different rootless daemon user.
- Group-write on host bind mounts may not help if the container writes as a subuid-mapped numeric owner rather than as the daemon user's host UID.

Practical approach:

- For app-local bind mount directories, prefer a dedicated access group and setgid directories:
  ```bash
  sudo chgrp -R <docker-access-group> /data/docker/<stack>
  sudo chmod -R g+rwX /data/docker/<stack>
  sudo find /data/docker/<stack> -type d -exec chmod g+s {} +
  ```
- Avoid recursive permission changes on broad personal/media/backup trees unless explicitly approved.
- For rootless-friendly LinuxServer-style apps, consider setting app/database `PUID=0` and `PGID=0` so writes map to the rootless daemon user instead of an unexpected subuid. This is not host-root under rootless Docker.
- For images whose default `USER` is a non-root application account and which fail against a bind mount owned by the rootless daemon user, consider setting the compose service `user: "0:0"` after reviewing the image. Under rootless Docker this maps to the daemon user on the host, not host root. This is often useful for data services like object stores that need to manage their own bind-mounted data.
- Always back up `.env` and compose files before changing UID/GID or `user:` settings.

If `setfacl` is available, ACLs can be cleaner than group changes for narrowly granting the runtime user access. If not installed, do not install packages without approval.

## Common Rootless Failure Patterns

### Stale user socket

Symptom:

```text
failed to connect to the docker API at unix:///run/user/1000/docker.sock
```

Meaning: the Docker CLI context points at a rootless daemon for that login user, but no daemon/socket is active there. Fix by switching to the intended shared context or explicitly setting `DOCKER_HOST`.

### Bind mount permission denied

Symptoms in logs:

```text
permission denied
operation not permitted
can't create/write file
```

Check host path ownership/modes and the container's effective UID/GID. Remember that container UID 1000 under rootless may not be host UID 1000.

### Entrypoint `chown` loop

Some images recursively `chown` bind-mounted config on startup. Rootless Docker often cannot change ownership of existing host files to arbitrary mapped IDs. Options:

- Configure image to skip chown if supported.
- Change UID/GID env to rootless-compatible values.
- Pre-adjust ownership/permissions carefully.
- Replace with a more rootless-friendly image.
- Stop/remove restart-looping containers to avoid log spam while investigating.

### Privileged port binding

Rootless Docker cannot bind host ports below the system's unprivileged threshold, commonly 1024.

Symptoms:

```text
cannot expose privileged port 222
```

Options:

- Prefer changing host port to >=1024, e.g. `2222:22`, when clients are easy to update.
- Or approve a system-level policy change such as `net.ipv4.ip_unprivileged_port_start` when preserving existing client remotes matters.
- Or use an external proxy/redirect. Treat sysctl/network changes as escalation items.

If approved, make the sysctl persistent and verify both the value and listeners:

```bash
printf 'net.ipv4.ip_unprivileged_port_start=222\n' | sudo tee /etc/sysctl.d/90-rootless-docker-ports.conf >/dev/null
sudo sysctl -p /etc/sysctl.d/90-rootless-docker-ports.conf
sysctl net.ipv4.ip_unprivileged_port_start
ss -ltnp | grep -E ':(222|<app-http-port>)\\b'
```

Do not assume every application can run as container UID 0 just because rootless maps it to the daemon user. Some apps, such as Forgejo/Gitea, explicitly refuse to run as root. In those cases, keep the app's required non-root UID/GID in compose, ensure the bind mount is initially writable by the rootless daemon user, and let the entrypoint chown data into the mapped subuid range.

### Host-level backup services that need Docker quiescence

Do not reflexively migrate broad backup services into rootless Docker just because other app stacks are moving there. If a backup service needs to read host/system paths, root-owned files, broad mounts, or backup credentials, a host-level systemd service may be the safer architecture.

For Backrest/restic-style services backing up `/data/docker`, first identify the **live** service and config before touching stale compose directories:

```bash
sudo systemctl status backrest.service --no-pager
sudo systemctl cat backrest.service
sudo ss -ltnp | grep ':9898\b'
```

If the service is host-level but needs to quiesce rootless containers, prefer explicit `DOCKER_HOST` hooks over rootful `/var/run/docker.sock` commands:

```bash
DOCKER_HOST=unix:///run/den-mcp/docker-rt/docker.sock docker ps
```

Safer hook pattern:

1. Pre-backup hook saves the currently running container IDs to a state file under `/run/<service>/...` and stops exactly those containers.
2. Backup runs against the host filesystem.
3. Post-backup hook starts exactly the saved IDs and removes the state file.
4. Document manual recovery: rerun the post-hook if the host/service crashes after pre-hook and before post-hook.

Do not run stop/start hooks manually during business-critical uptime unless explicitly approved. Validate in list/dry mode first, syntax-check scripts, back up service config, restart the service only when no backup task is active, and verify the next schedule.

### Devices, TUN, GPU, USB, privileged mode

Stacks using any of these need special review:

```yaml
privileged: true
cap_add:
  - NET_ADMIN
devices:
  - /dev/net/tun:/dev/net/tun
  - /dev/dri:/dev/dri
  - /dev/bus/usb:/dev/bus/usb
network_mode: host
```

Rootless support varies by kernel, device permissions, cgroups, and daemon configuration. Do not bulk-start these with simple web apps.

Do not assume TUN/`NET_ADMIN` is impossible under rootless; test it deliberately. A Gluetun WireGuard stack can work under rootless Docker when `/dev/net/tun` is accessible and the runtime/kernel allow the needed operations. Verify with health status, VPN logs, exposed UI ports, and an external-IP probe from inside the VPN container:

```bash
docker compose ps
docker compose logs --tail=160 gluetun
docker exec gluetun wget -qO- --timeout=8 https://ifconfig.co
```

GPU/video-acceleration stacks need two separate checks: **image userspace support** and **rootless device access**. Newer GPUs may require newer Mesa/libva inside the container even if the host driver works. Probe both sides before changing the live stack:

```bash
# Host capability, run as root if render device is group-restricted
sudo env LIBVA_DRIVER_NAME=radeonsi vainfo --display drm --device /dev/dri/renderD128

# Rootless runtime user's device access
id <runtime-user>
stat -c '%A %U:%G %n' /dev/dri/card0 /dev/dri/renderD128
sudo -u <runtime-user> test -r /dev/dri/renderD128 && echo readable
sudo -u <runtime-user> test -w /dev/dri/renderD128 && echo writable

# Container userspace package check without starting the service
DOCKER_HOST=unix:///run/.../docker.sock docker run --rm --entrypoint /bin/sh \
  --device /dev/dri/renderD128:/dev/dri/renderD128 \
  -e LIBVA_DRIVER_NAME=radeonsi <candidate-image> -lc \
  'cat /etc/os-release; dpkg-query -W mesa-va-drivers libgl1-mesa-dri libva2 2>/dev/null || true; vainfo --display drm --device /dev/dri/renderD128'
```

If the runtime user cannot open `/dev/dri/*`, adding it to `render`/`video` and restarting the rootless daemon/session is a host permission change affecting all containers on that runtime; ask for approval and plan rollback. Do not mistake `vainfo: Failed to open the given device` for an application config issue until group/device access is checked.

For rootless Docker, supplementary groups may still not be enough inside the container: device nodes can appear as `nobody:nogroup` even after the daemon user joins `render`/`video`. If a narrowly scoped test succeeds only after loosening the render node, prefer a narrow udev rule for render nodes rather than exposing card/control nodes:

```udev
SUBSYSTEM=="drm", KERNEL=="renderD*", MODE="0666", GROUP="render"
```

USB accelerators such as Google Coral have the same rootless device-access class. Identify the exact USB VID/PID with `lsusb` and `udevadm info`, test the current `/dev/bus/usb/...` node, then use a narrow udev rule if required. For Coral USB, common IDs are initialized Google `18d1:9302` and pre-init Global Unichip `1a6e:*`:

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="18d1", ATTR{idProduct}=="9302", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="1a6e", MODE="0666", GROUP="plugdev"
```

After device permission fixes, verify from the app, not just `docker run`: for Frigate, check container health, `/api/stats`, `TPU found`, and ffmpeg process args containing `-hwaccel vaapi -hwaccel_device /dev/dri/renderD128`.

For media/download stacks, distinguish local config bind-mount permissions from broad media-tree permissions. It is usually acceptable to re-own app-local config dirs under `/data/docker/<stack>/...`; do not recursively change multi-terabyte media trees such as `/mnt/storage/movies` or `/mnt/storage/tv` without explicit approval. Use controlled container write probes first:

```bash
docker exec sabnzbd sh -c 'touch /downloads/.rootless-write-test && rm -f /downloads/.rootless-write-test'
docker exec radarr  sh -c 'touch /movies/.rootless-write-test && rm -f /movies/.rootless-write-test'
docker exec sonarr  sh -c 'touch /tv/.rootless-write-test && rm -f /tv/.rootless-write-test'
```

### Old database/app config incompatible with updated image

A migration may expose stale config unrelated to rootless mode. Example class: a newer database image rejects an old config setting, causing a misleading healthcheck failure. Inspect internal error logs, not just `docker compose logs`.

## Data-Root Recovery Rules

Never casually copy one Docker data root into another live daemon's data root. Risks include:

- containerd metadata/database mismatch;
- overlay/content-store corruption;
- ownership mismatch between old user and new runtime user;
- resurrecting unrelated containers/networks;
- breaking an otherwise healthy daemon.

If old data is needed:

1. Identify exact image/container/volume names.
2. Prefer Docker-native export/import when the old daemon can run.
3. For named volume recovery, copy only the specific volume `_data` into a staged bind-mount directory with backups.
4. Preserve original backup until the migrated stack is verified.

## Verification Checklist

- [ ] `docker version` works for the intended service/interactive users against the shared socket.
- [ ] The user is not accidentally using a stale `rootless` context or rootful `/var/run/docker.sock`.
- [ ] Socket owner/group/mode match the intended access model.
- [ ] Compose config renders without printing secrets.
- [ ] Only one stack is started at a time during migration.
- [ ] Logs are checked after startup; restart loops are stopped.
- [ ] HTTP/port/health checks pass where applicable.
- [ ] Config edits have timestamped backups.
- [ ] Permission changes are limited to intended app data dirs.
- [ ] Higher-risk stacks with devices, TUN, host networking, privileged mode, or broad mounts have separate plans.
- [ ] Operational notes record actions, verification, blockers, and rollback.

## References

- `references/den-srv-docker-rt-migration-2026-05.md` — concrete session notes from migrating den-srv `/data/docker` stacks to a shared rootless `docker-rt` runtime, including Backrest host-service handling and media/NFS permission normalization.
