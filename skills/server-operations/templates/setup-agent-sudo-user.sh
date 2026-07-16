#!/usr/bin/env bash
set -euo pipefail

# setup-agent-sudo-user.sh
#
# Create/update an auditable agent account for operational work and install a
# constrained sudoers drop-in. Intended to be run manually as root on a trusted
# LAN host after review.
#
# Safety posture:
# - locked password by default;
# - SSH key only, supplied explicitly or copied from a named local user;
# - minimal default supplementary groups;
# - no broad sudo unless explicitly requested as break-glass;
# - privileged routine actions go through root-owned helper scripts with argument checks;
# - sudoers is validated with visudo before installation.

AGENT_USER="${AGENT_USER:-agent}"
AGENT_GROUP="${AGENT_GROUP:-agents}"
SUDOERS_SOURCE="${SUDOERS_SOURCE:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/agent-sudoers.conf}"
SUDOERS_DEST="${SUDOERS_DEST:-/etc/sudoers.d/90-agent-sudo-user}"
DEFAULT_GROUPS="${DEFAULT_GROUPS:-adm systemd-journal}"
EXTRA_GROUPS="${EXTRA_GROUPS:-}"
COPY_SSH_FROM="${COPY_SSH_FROM:-}"
AUTHORIZED_KEYS_FILE="${AUTHORIZED_KEYS_FILE:-}"
INSTALL_SUDOERS="${INSTALL_SUDOERS:-1}"
INSTALL_HELPERS="${INSTALL_HELPERS:-1}"
LOCK_PASSWORD="${LOCK_PASSWORD:-1}"
ENABLE_PASSWD_SUDO="${ENABLE_PASSWD_SUDO:-0}"
ENABLE_NOPASSWD_ALL="${ENABLE_NOPASSWD_ALL:-0}"

SCRIPT_NAME="$(basename "$0")"

log() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "run this script with sudo or as root"
  fi
}

require_command() { command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"; }

usage() {
  cat <<EOF
Usage: sudo $SCRIPT_NAME [--dry-run]

Environment overrides:
  AGENT_USER=agent
  AGENT_GROUP=agents
  AUTHORIZED_KEYS_FILE=/path/to/authorized_keys
  COPY_SSH_FROM=existing_user
  EXTRA_GROUPS="docker"
  INSTALL_SUDOERS=1
  INSTALL_HELPERS=1
  LOCK_PASSWORD=1
  ENABLE_PASSWD_SUDO=0
  ENABLE_NOPASSWD_ALL=0
EOF
}

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $arg" ;;
  esac
done

run() {
  if [[ "$DRY_RUN" == 1 ]]; then
    printf 'DRY-RUN:'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

install_wrapper() {
  local path="$1" tmp
  tmp="$(mktemp)"
  cat >"$tmp"
  if [[ "$DRY_RUN" == 1 ]]; then
    log "DRY-RUN: install helper $path from generated content"
    rm -f "$tmp"
  else
    install -o root -g root -m 0755 "$tmp" "$path"
    rm -f "$tmp"
  fi
}

validate_identifier() {
  local label="$1" value="$2"
  [[ "$value" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || die "invalid $label: $value"
}

create_user_and_groups() {
  validate_identifier "user" "$AGENT_USER"
  validate_identifier "group" "$AGENT_GROUP"

  if ! getent group "$AGENT_GROUP" >/dev/null; then run groupadd "$AGENT_GROUP"; fi

  if ! id "$AGENT_USER" >/dev/null 2>&1; then
    run useradd --create-home --shell /bin/bash --gid "$AGENT_GROUP" "$AGENT_USER"
  else
    run usermod -aG "$AGENT_GROUP" "$AGENT_USER"
  fi

  if [[ "$LOCK_PASSWORD" == 1 ]]; then run passwd -l "$AGENT_USER" >/dev/null || true; fi

  local groups_to_add=() group
  for group in $DEFAULT_GROUPS $EXTRA_GROUPS; do
    validate_identifier "supplementary group" "$group"
    if getent group "$group" >/dev/null; then groups_to_add+=("$group"); else log "Skipping absent group: $group"; fi
  done
  if ((${#groups_to_add[@]})); then run usermod -aG "$(IFS=,; printf '%s' "${groups_to_add[*]}")" "$AGENT_USER"; fi
}

setup_ssh_dir() {
  local home source_keys=""
  home="$(getent passwd "$AGENT_USER" | cut -d: -f6)"
  [[ -n "$home" ]] || die "could not determine home directory for $AGENT_USER"

  run install -d -o "$AGENT_USER" -g "$AGENT_GROUP" -m 0700 "$home/.ssh"

  if [[ -n "$AUTHORIZED_KEYS_FILE" ]]; then
    source_keys="$AUTHORIZED_KEYS_FILE"
  elif [[ -n "$COPY_SSH_FROM" ]]; then
    validate_identifier "COPY_SSH_FROM user" "$COPY_SSH_FROM"
    local source_home
    source_home="$(getent passwd "$COPY_SSH_FROM" | cut -d: -f6 || true)"
    [[ -n "$source_home" ]] || die "could not determine home directory for $COPY_SSH_FROM"
    source_keys="$source_home/.ssh/authorized_keys"
  fi

  if [[ -n "$source_keys" ]]; then
    [[ -f "$source_keys" ]] || die "authorized_keys source not found: $source_keys"
    run install -o "$AGENT_USER" -g "$AGENT_GROUP" -m 0600 "$source_keys" "$home/.ssh/authorized_keys"
  elif [[ ! -e "$home/.ssh/authorized_keys" ]]; then
    run install -o "$AGENT_USER" -g "$AGENT_GROUP" -m 0600 /dev/null "$home/.ssh/authorized_keys"
    log "Created empty authorized_keys; add an SSH key before expecting login to work."
  else
    run chown "$AGENT_USER:$AGENT_GROUP" "$home/.ssh/authorized_keys"
    run chmod 0600 "$home/.ssh/authorized_keys"
  fi
}

install_helpers() {
  [[ "$INSTALL_HELPERS" == 1 ]] || return 0
  run install -d -o root -g root -m 0755 /usr/local/sbin

  install_wrapper /usr/local/sbin/agent-apt-update <<'EOF'
#!/bin/sh
set -eu
command -v apt-get >/dev/null 2>&1 || { echo "apt-get not found" >&2; exit 127; }
exec apt-get update
EOF

  install_wrapper /usr/local/sbin/agent-apt-install <<'EOF'
#!/bin/sh
set -eu
command -v apt-get >/dev/null 2>&1 || { echo "apt-get not found" >&2; exit 127; }
if [ "$#" -eq 0 ]; then echo "usage: agent-apt-install PACKAGE..." >&2; exit 2; fi
for pkg in "$@"; do
  case "$pkg" in
    -*|*[!A-Za-z0-9+._:=@-]*) echo "Refusing suspicious package name: $pkg" >&2; exit 2 ;;
  esac
done
exec apt-get -y install --no-install-recommends -- "$@"
EOF

  install_wrapper /usr/local/sbin/agent-systemctl-daemon-reload <<'EOF'
#!/bin/sh
set -eu
exec systemctl daemon-reload
EOF

  install_wrapper /usr/local/sbin/agent-service <<'EOF'
#!/bin/sh
set -eu
if [ "$#" -lt 2 ]; then echo "usage: agent-service ACTION UNIT..." >&2; exit 2; fi
action="$1"; shift
case "$action" in reload|restart|try-restart|status) ;; *) echo "Refusing unsupported service action: $action" >&2; exit 2 ;; esac
for unit in "$@"; do
  case "$unit" in -*|*/*|*[!A-Za-z0-9@_.:-]*) echo "Refusing suspicious unit name: $unit" >&2; exit 2 ;; esac
done
exec systemctl "$action" "$@"
EOF

  install_wrapper /usr/local/sbin/agent-tail-log <<'EOF'
#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then echo "usage: agent-tail-log /var/log/FILE" >&2; exit 2; fi
case "$1" in /var/log/*) ;; *) echo "Refusing non-/var/log path: $1" >&2; exit 2 ;; esac
exec tail -n 300 -- "$1"
EOF
}

install_sudoers() {
  [[ "$INSTALL_SUDOERS" == 1 ]] || return 0
  if [[ "$AGENT_USER" != "agent" ]]; then
    die "sudoers template currently grants privileges to literal user 'agent'; keep AGENT_USER=agent or provide a matching SUDOERS_SOURCE"
  fi
  if [[ "$ENABLE_PASSWD_SUDO" == 1 && "$ENABLE_NOPASSWD_ALL" == 1 ]]; then
    die "choose only one broad sudo mode: ENABLE_PASSWD_SUDO=1 or ENABLE_NOPASSWD_ALL=1"
  fi
  [[ -f "$SUDOERS_SOURCE" ]] || die "sudoers source not found: $SUDOERS_SOURCE"
  require_command visudo

  local tmp
  tmp="$(mktemp)"
  install -o root -g root -m 0440 "$SUDOERS_SOURCE" "$tmp"
  if [[ "$ENABLE_PASSWD_SUDO" == 1 ]]; then
    printf '\n# Break-glass: password-required broad sudo.\nagent ALL=(root) PASSWD: ALL\n' >>"$tmp"
    log "ENABLE_PASSWD_SUDO=1: added password-required break-glass sudo rule."
  fi
  if [[ "$ENABLE_NOPASSWD_ALL" == 1 ]]; then
    printf '\n# Break-glass: passwordless broad sudo. High-risk; remove after repair window.\nagent ALL=(root) NOPASSWD: ALL\n' >>"$tmp"
    log "ENABLE_NOPASSWD_ALL=1: added PASSWORDLESS broad sudo rule for break-glass repair work."
  fi
  visudo -cf "$tmp" >/dev/null
  if [[ "$DRY_RUN" == 1 ]]; then
    log "DRY-RUN: install sudoers $SUDOERS_DEST from validated $SUDOERS_SOURCE"
    rm -f "$tmp"
  else
    install -o root -g root -m 0440 "$tmp" "$SUDOERS_DEST"
    rm -f "$tmp"
    visudo -cf "$SUDOERS_DEST" >/dev/null
  fi
}

verify_install() {
  log ""; log "Verification summary:"
  id "$AGENT_USER" || true
  local home
  home="$(getent passwd "$AGENT_USER" | cut -d: -f6 || true)"
  if [[ -n "$home" ]]; then stat -c '  %A %U:%G %n' "$home" "$home/.ssh" "$home/.ssh/authorized_keys" 2>/dev/null || true; fi
  if [[ "$INSTALL_SUDOERS" == 1 && "$DRY_RUN" != 1 ]]; then visudo -cf "$SUDOERS_DEST"; fi
}

main() {
  need_root
  require_command groupadd; require_command useradd; require_command usermod; require_command passwd
  require_command install; require_command getent; require_command stat
  create_user_and_groups
  setup_ssh_dir
  install_helpers
  install_sudoers
  verify_install
  log ""; log "Agent sudo user setup complete."
  log "  user: $AGENT_USER"
  log "  group: $AGENT_GROUP"
  log "  sudoers: $SUDOERS_DEST"
  log "Recommended first remote test: ssh agent@<host> 'id && sudo -n /usr/local/sbin/agent-service status ssh.service'"
}

main "$@"
