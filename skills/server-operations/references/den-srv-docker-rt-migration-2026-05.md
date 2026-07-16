# den-srv docker-rt migration notes — 2026-05

This reference captures concrete findings from a den-srv migration where `/data/docker` application stacks were moved toward a shared rootless Docker daemon.

## Runtime model

- Host: `den-srv` (`192.168.1.10`).
- Shared rootless runtime user: `docker-rt`.
- Shared socket: `unix:///run/den-mcp/docker-rt/docker.sock`.
- Access group: `den-pi-docker`.
- Interactive admin user `patch` was added to `den-pi-docker` and given Docker context `den-docker-rt` pointing at the shared socket.
- `den-mcp` was removed from rootful `docker` group and retained access only through the shared rootless socket.

## Broken context symptom

`patch` originally had a selected Docker context pointing at a non-existent socket:

```text
unix:///run/user/1000/docker.sock
```

This produced:

```text
failed to connect to the docker API at unix:///run/user/1000/docker.sock
```

Fix was not to revive a personal rootless daemon, but to point `patch` at the shared `docker-rt` context.

## Data roots and old backup

- Current live data root: `/data/docker-rt`, owned by `docker-rt:den-pi-docker`.
- Old backup data root: `/data/docker-rt-bak`, owned by `patch:patch`, ~360G, with many unrelated containers/volumes.

Do not copy `/data/docker-rt-bak` wholesale into `/data/docker-rt`. It is an old general-purpose Docker data root, not a small config backup.

When exact Pi/Den MCP session terms were searched in backup metadata (`pi-sandbox`, `DenMcp`, `den-mcp`, `pi-session`, `agent/settings.json`, `/home/pi/.pi`), there were no matches.

## `/data/docker` stack inventory

Active non-`old` compose stacks found:

```text
/data/docker/arcane/compose.yaml
/data/docker/arr-servers/docker-compose.yml
/data/docker/audiobookshelf/docker-compose.yml
/data/docker/backrest/docker-compose.yml
/data/docker/booklore/docker-compose.yml
/data/docker/forgejo/docker-compose.yaml
/data/docker/frigate/docker-compose.yml
/data/docker/lobe-chat/docker-compose.yml
/data/docker/navidrome/docker-compose.yaml
/data/docker/next-explorer/docker-compose.yaml
/data/docker/syncthing/docker-compose.yaml
```

All rendered with `docker compose config` under the `patch` / `den-docker-rt` context.

## Stacks successfully started in batch 1

- Navidrome: healthy enough for HTTP, port `4533`, HTTP `302`.
- Audiobookshelf: port `13378`, HTTP `200`.
- BookLore: port `6060`, HTTP `200`, MariaDB healthy.

## Permission pattern used

`setfacl` was not installed. For app-local bind mount dirs, used group-based access:

```bash
sudo chgrp -R den-pi-docker /data/docker/<stack>
sudo chmod -R g+rwX /data/docker/<stack>
sudo find /data/docker/<stack> -type d -exec chmod g+s {} +
```

Avoided broad recursive changes under `/mnt/storage` and other personal/media trees.

## BookLore fixes

BookLore required several rootless/migration fixes:

1. Upstream image name changed:

```text
booklore/booklore:latest -> ghcr.io/booklore-app/booklore:latest
```

2. `.env` UID/GID values changed to `0`:

```text
APP_USER_ID=0
APP_GROUP_ID=0
DB_USER_ID=0
DB_GROUP_ID=0
```

Reason: in this rootless runtime, container UID 0 maps to host `docker-rt`, while container UID 1000 maps into the `docker-rt` subuid range rather than host `patch`.

3. MariaDB 11.4 rejected old config:

```text
innodb_flush_method = fdatasync
```

It disabled InnoDB and reported:

```text
Error while setting value 'fdatasync' to 'innodb-flush-method'
Unknown/unsupported storage engine: InnoDB
```

Fix: back up `custom.cnf` and comment the line.

## Stacks successfully started in batch 2

- Arcane: port `3552`, HTTP `200`.
  - Converted Docker socket mount from rootful `/var/run/docker.sock` to shared rootless `/run/den-mcp/docker-rt/docker.sock`.
  - Converted named volume to bind mount `./data:/app/data`.
  - Set `PUID=0` / `PGID=0` after rootless startup failed trying to chown `/app/data` as old UID/GID.
  - First boot created a default admin account; do not store the password in notes and tell the user to change it.
- Lobe Chat: app port `3210` HTTP `302`, SearXNG `8088` HTTP `200`, Postgres/Redis/RustFS healthy.
  - Old named volume data was under `/data/docker-rt-bak/volumes/lobehub_redis_data/_data` and `/data/docker-rt-bak/volumes/lobehub_rustfs-data/_data`.
  - Copied those into explicit bind directories `/data/docker/lobe-chat/redis_data` and `/data/docker/lobe-chat/rustfs-data`.
  - Patched compose mounts from `redis_data:/data` and `rustfs-data:/data` to `./redis_data:/data` and `./rustfs-data:/data`.
  - Moved SearXNG host publish from `8080:8080` to `8088:8080` because `den-router` already listened on `8080`.
  - For local Lobe data dirs (`data`, `redis_data`, `rustfs-data`), ownership was changed to `docker-rt:den-pi-docker` and group/setgid permissions applied.
  - RustFS image uses `USER=rustfs`; it still failed with `Io error: Permission denied` until compose service `rustfs` was set to `user: "0:0"`.
  - Follow-ups: Postgres warns about collation version mismatch; Redis warns `vm.overcommit_memory` is disabled.
- Syncthing: port `8384`, HTTP `200`.
  - User removed the broad `/mnt/storage/docs/patch-vault` mount before migration.
  - LinuxServer image failed generating `/config/cert.pem` with old `PUID=1000` / `PGID=1000` under rootless bind mount.
  - Set `PUID=0` / `PGID=0`, chowned local config to `docker-rt:den-pi-docker`, and restarted successfully.

## Stacks successfully started in batch 3

- Forgejo: HTTP `200` on host port `3010`; SSH listener restored on host port `222`.
  - User approved preserving existing Git remotes by lowering the host's unprivileged port floor.
  - Persistent sysctl file: `/etc/sysctl.d/90-rootless-docker-ports.conf` with `net.ipv4.ip_unprivileged_port_start=222`.
  - Forgejo refused to run as container UID 0 (`Forgejo is not supposed to be run as root`). Final compose kept `USER_UID=1000` / `USER_GID=1000`.
  - Safe pattern was: make the bind-mounted Forgejo tree initially writable by `docker-rt:den-pi-docker`, recreate the container, and let Forgejo's entrypoint chown durable app/git data to the mapped subuid (`166535:166535` in this session).
- arr-servers: Gluetun, qBittorrent, SABnzbd, Prowlarr, Radarr, Sonarr, and Jellyfin all started under `docker-rt`.
  - LinuxServer-style containers were patched from `PUID=1000` / `PGID=1000` to `PUID=0` / `PGID=0`.
  - Only local config dirs under `/data/docker/arr-servers/{gluetun,qbittorrent,sabnzbd,prowlarr,radarr,sonarr,jellyfin}` were re-owned to `docker-rt:den-pi-docker`; `/mnt/storage` was not recursively changed.
  - Gluetun with `/dev/net/tun` and `NET_ADMIN` worked under rootless Docker; health was good and external IP probe from inside Gluetun returned a VPN IP.
  - HTTP checks passed: qBittorrent `8030` 200, SABnzbd `8035` 200, Prowlarr `9696` 200, Radarr `8037` 200, Sonarr `8038` 200, Jellyfin `8039` 302.
  - Controlled write probes succeeded for top-level `/downloads`, `/movies`, and `/tv`, but existing root-owned subdirectories under `/mnt/storage/movies` and `/mnt/storage/tv` still caused import failures into those specific directories. Do not normalize multi-TB media-tree ownership without explicit approval.
  - Gluetun logged inability to write `/gluetun/servers.json`, but service remained healthy.

## Media/NFS permission normalization

The user clarified that root ownership of media directories was not desired; media should be broadly manageable over the trusted LAN/NFS share. Inspection found `/mnt/storage` was a mergerfs mount exported over NFS, with mixed `root:root` / `patch:patch` ownership and many `0755` directories. After explicit approval, the chosen broad-LAN convenience policy was applied only to:

```text
/mnt/storage/downloads
/mnt/storage/movies
/mnt/storage/tv
```

Policy:

```text
group:       den-pi-docker
directories: 2777 / drwxrwsrwx
files:       666  / -rw-rw-rw-
```

Verification checked zero non-conforming dirs/files/groups and repeated container write probes, including a previously blocked Sonarr path under `/tv/Ghosts (US)/Season 5`. This is intentionally permissive for trusted home/LAN media; revisit if the host becomes hostile multi-user infrastructure.

## Backrest handling

Backrest was found to be an active host-level root systemd service, not a live Docker stack:

```text
backrest.service
/usr/local/bin/backrest
BACKREST_DATA=/data/backrest/data
BACKREST_CONFIG=/data/backrest/config/config.json
port 9898
```

`/data/docker/backrest` existed but was stale/unused. Keeping Backrest as a host service was the correct architecture because it backs up root/system paths and broad host mounts:

```text
/data/docker
/mnt/gate-data/docker
/mnt/storage/appdata
/mnt/storage/backup
/mnt/storage/pictures
/opt
```

Health finding: backups were completing even though the pre-backup hook failed. Latest verified snapshot in-session was `29474b5b91abd03d395ee47c27a09df6eaadb226686c087988fc7c10074b6830` from `2026-05-08 06:00`, processing about 2.63 TB / 2,038,409 files and adding about 972 MB. A recent repo check reported `7 / 7 snapshots` and no errors.

Problem: Backrest's hook used stale rootful Docker commands (`docker ps -q ... docker stop ...`) and failed daily. Backups still ran, but against live `/data/docker` app data.

Repair pattern applied:

- Created `/usr/local/sbin/backrest-docker-rt-pre.sh` and `/usr/local/sbin/backrest-docker-rt-post.sh`.
- Hook scripts target `DOCKER_HOST=unix:///run/den-mcp/docker-rt/docker.sock`.
- Pre-hook saves currently running docker-rt container IDs to `/run/backrest/docker-rt-running-containers` and stops them.
- Post-hook starts exactly the saved IDs and removes the state file.
- Backed up config to `/data/backrest/config/config.json.bak.2026-05-08-23-06-05.pre-docker-rt-hooks` and changed hooks to call the scripts.
- Verified with script syntax checks, non-disruptive list mode, service restart, HTTP 200 on `127.0.0.1:9898`, and next backup schedule.

Manual recovery if containers are stranded after a crash between hooks:

```bash
sudo /usr/local/sbin/backrest-docker-rt-post.sh start
```

Consider a watchdog/timer for stale `/run/backrest/docker-rt-running-containers` if this pattern becomes important elsewhere.

## Frigate RX 9070 XT ROCm/VAAPI migration

Frigate was migrated successfully under `docker-rt` rootless Docker for the user's AMD Radeon RX 9070 XT / Navi 48 card.

Compose/config paths:

```text
/data/docker/frigate/docker-compose.yml
/data/docker/frigate/config.yaml
```

Important discovery: compose mounted `.:/config`, so the active config was the top-level `/data/docker/frigate/config.yaml`; a nested `/data/docker/frigate/frigate/config.yaml` was stale/secondary.

Image research result:

- Standard `ghcr.io/blakeblackshear/frigate:stable` / `0.17.1` had Mesa `22.3.6`, too old for Navi 48.
- `ghcr.io/blakeblackshear/frigate:0.17.1-rocm` / `stable-rocm` had Mesa `25.0.7-2~bpo12+1`, matching upstream reports where new AMD hardware began working.

Final compose/config:

```yaml
image: ghcr.io/blakeblackshear/frigate:0.17.1-rocm
environment:
  - LIBVA_DRIVER_NAME=radeonsi
devices:
  - /dev/bus/usb:/dev/bus/usb
  - /dev/dri/renderD128:/dev/dri/renderD128
```

```yaml
ffmpeg:
  hwaccel_args: preset-vaapi
```

Backups created:

```text
/data/docker/frigate/docker-compose.yml.bak.20260509-003327.pre-rx9070-rocm
/data/docker/frigate/config.yaml.bak.20260509-003327.pre-rx9070-rocm
```

Rootless DRI lesson: adding `docker-rt` to `render`/`video` and restarting the rootless Docker service was necessary but not sufficient; inside rootless containers `/dev/dri/renderD128` appeared as `nobody:nogroup`. A narrow render-node udev rule fixed VAAPI access without loosening `/dev/dri/card*`:

```text
/etc/udev/rules.d/90-docker-rt-render.rules
SUBSYSTEM=="drm", KERNEL=="renderD*", MODE="0666", GROUP="render"
```

One-shot verification inside the ROCm image:

```text
Mesa Gallium driver 25.0.7-2~bpo12+1 for AMD Radeon Graphics (radeonsi, gfx1201, ACO, DRM 3.64, Linux 6.17.13)
H264/HEVC/VP9/AV1 decode entrypoints present
```

USB Coral had the same rootless device-access issue. The Coral appeared as `18d1:9302` at `/dev/bus/usb/001/003`; Frigate logged `No EdgeTPU was detected` until a narrow USB udev rule/current chmod allowed writes:

```text
/etc/udev/rules.d/91-docker-rt-coral.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="18d1", ATTR{idProduct}=="9302", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="1a6e", MODE="0666", GROUP="plugdev"
```

Frigate-local config/db tree `/data/docker/frigate` had to be re-owned to `docker-rt:den-pi-docker` with setgid dirs after startup failed with:

```text
Config file is read-only, unable to migrate config file.
peewee.OperationalError: attempt to write a readonly database
```

Camera storage `/mnt/storage/video/cameras` also needed the trusted-LAN media policy (`group=den-pi-docker`, dirs `2777`, files `666`) after Frigate could not write recordings/clips under `/media/frigate`.

Final verification:

```text
Frigate health: healthy
HTTP 127.0.0.1:5000 -> 200
Frigate version: 0.17.1-416a9b7
Coral: TPU found, inference_speed ~24 ms
ffmpeg args: -hwaccel vaapi -hwaccel_device /dev/dri/renderD128 -hwaccel_output_format vaapi, scale_vaapi=...
```

Known remaining issue: `3dprinter` camera RTSP at `192.168.1.7:554` timed out repeatedly and produced ffmpeg restart log noise; unrelated to the AMD/rootless migration.

## Deferred/blocker examples

- `next-explorer`: restart loop from entrypoint `chown` against bind-mounted config files; rootless cannot perform that chown. Stop/remove restart loop during investigation.
- `frigate`: resolved on `0.17.1-rocm` with VAAPI on RX 9070 XT, USB Coral access, Frigate-local ownership fixes, camera-storage permissions, and narrow udev rules for render/Coral devices. Remaining issue is the unrelated `3dprinter` RTSP timeout.
- Backrest is resolved as a host-level service with docker-rt quiescence hooks; do not migrate it into rootless Docker casually.

## Documentation created during session

Den notes created:

```text
den-network/den-mcp-docker-rt-patch-access-and-pi-build-2026-05-08
den-network/docker-rt-bak-review-2026-05-08
den-network/data-docker-rootless-docker-rt-inventory-2026-05-08
den-network/data-docker-rootless-migration-batch-1-2026-05-08
den-network/data-docker-rootless-migration-batch-2-2026-05-08
den-network/data-docker-rootless-migration-batch-3-2026-05-08
den-network/den-srv-media-permission-policy-2026-05-08
den-network/backrest-audit-docker-rt-hook-repair-2026-05-08
den-network/frigate-rx9070xt-hwaccel-research-2026-05-08
den-network/frigate-rx9070xt-rootless-rocm-migration-2026-05-09
```
