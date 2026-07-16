---
name: agent-server-access
description: "Design, review, and deploy dedicated agent accounts for audited server administration with constrained sudo, SSH keys, and rollback."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [sysadmin, sudo, ssh, access-control, auditing, server-administration]
    related_skills: [hermes-deployment, den-mcp]
---

# Agent Server Access

## Overview

Use this skill when preparing a LAN/server host for agent-administered work via a dedicated `agent` account. The goal is auditable, recoverable operational access — not turning an agent into an unbounded passwordless root shell.

This covers user creation, SSH key provisioning, sudoers design, helper wrappers, validation, remote smoke tests, and rollback.

## Core posture

Treat access setup as an access-control design task, not just a setup script.

Default stance for this user's infrastructure:

- Prefer a dedicated `agent` account for auditability.
- Prefer SSH keys over passwords.
- Lock the password by default unless a deliberate break-glass path is chosen.
- Do **not** grant `NOPASSWD:ALL` casually.
- For messy repair windows where agent-driven sudo is safer than human copy/paste, allow an explicit, time-bounded break-glass `NOPASSWD:ALL` mode; document the rationale and remove it after repair.
- Grant routine passwordless sudo only for read-only inspection and tightly-scoped root-owned helper wrappers.
- Ask for approval before deploying anything that changes users, groups, SSH, sudoers, permissions, or authentication.
- Preserve rollback: sudoers drop-in removable; account lockable; SSH keys removable.

## Planning checklist before deployment

Before making changes on a target server, state a short plan:

1. **Intent** — why the agent account is needed.
2. **Scope** — target host, user, groups, sudoers file, helper scripts, SSH keys.
3. **Expected changes** — exact auth/sudo surfaces that will change.
4. **Verification** — local syntax checks plus remote SSH/sudo smoke tests.
5. **Rollback** — remove sudoers drop-in, remove/lock keys, lock/delete user if needed.
6. **Escalation conditions** — ambiguous existing sudoers, unclear SSH key source, secrets exposure risk, or need for broader sudo.

For target hosts such as `den-srv`, inspect/draft locally first. Do not deploy until the user approves the semantic plan.

If the target may already have an `agent` account or sudoers policy, switch from "create" to "audit and reconcile": test SSH, inspect `id`, `getent`, home/SSH permissions, sudo smoke status, and existing `/etc/sudoers.d/*agent*` files before rerunning setup or overwriting policy.

## Recommended model

### User and groups

- User: `agent`
- Primary group: `agents`
- Default supplementary groups should be minimal, often only:
  - `adm` for common log access on Debian-like systems;
  - `systemd-journal` for journal access.
- Add host-specific groups explicitly via `EXTRA_GROUPS`, not a broad default list.

Avoid adding `docker`, `libvirt`, `lxd`, or similar groups by default: those are commonly root-equivalent.

### SSH

For this user's fleet, prefer a **dedicated agent SSH keypair** over reusing the user's personal admin key. Generate the private key as the local account/process that will run the agent SSH client (often the Hermes `agent` user/profile home), **not as root**. Root is only needed on the target server to install the public key and set ownership/modes.

Example local key generation:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 \
  -f ~/.ssh/<target>-agent_ed25519 \
  -C "<source-host> <profile> Hermes agent -> <target> agent" \
  -N ""
chmod 600 ~/.ssh/<target>-agent_ed25519
chmod 644 ~/.ssh/<target>-agent_ed25519.pub
ssh-keygen -lf ~/.ssh/<target>-agent_ed25519.pub
```

Determine the source IP for an `authorized_keys` `from=` restriction:

```bash
ip route get <target-ip>
# look for: src <source-ip>
```

Recommended target `authorized_keys` line shape:

```text
from="<source-ip>" ssh-ed25519 AAAA... <source-host> Hermes agent -> <target> agent
```

- Create `~agent/.ssh` as `0700 agent:agents`.
- Install `authorized_keys` as `0600 agent:agents`.
- Accept keys from an explicit `AUTHORIZED_KEYS_FILE` or a named trusted source account (`COPY_SSH_FROM`).
- If no key is provided, create an empty `authorized_keys` and report that login will not work yet.

### Sudo policy

Prefer a sudoers drop-in such as `/etc/sudoers.d/90-agent-sudo-user` validated with `visudo -cf` before installation.

Good defaults:

- `Defaults:agent env_reset`
- explicit `secure_path`
- sudo logging to a dedicated file if supported, e.g. `/var/log/sudo-agent.log`
- `log_input,log_output` where supported by the target sudo version

Grant surfaces:

- Read-only inspection commands: `journalctl`, selected `systemctl status/list-*`, `ss`, `df`, `du`, `findmnt`, `lsblk`, `ip addr/route`, and optionally read-only Docker commands.
- Mutation commands only through root-owned helper scripts in `/usr/local/sbin/agent-*`.

Avoid:

- `agent ALL=(root) NOPASSWD: ALL`
- broad root file-read helpers over `/etc/*` — `/etc` contains secret-bearing files.
- package-manager wrappers that accept arbitrary flags.
- service wrappers that allow arbitrary unit names or destructive actions by default.

### Break-glass broad sudo

Sometimes the safe operational choice is a short repair window with broad sudo: if the agent must untangle a messy server and the alternative is a human repeatedly copy/pasting privileged commands, an explicit audited `NOPASSWD:ALL` mode can reduce mistakes. Treat this as a **semantic approval** item, not a default.

Supported modes in the template script:

- `ENABLE_PASSWD_SUDO=1` appends `agent ALL=(root) PASSWD: ALL`.
- `ENABLE_NOPASSWD_ALL=1` appends `agent ALL=(root) NOPASSWD: ALL`.
- The script should reject enabling both at once.

Use `ENABLE_NOPASSWD_ALL=1` for non-interactive Hermes repair work only when approved. Pair it with a dedicated SSH key, ideally `from="<source-ip>"` restricted. After the repair window, reinstall with both broad switches set to `0` or remove the broad sudoers drop-in.

### Helper wrappers

Helper wrappers should be root-owned, mode `0755`, and validate arguments internally before executing privileged tools.

Reasonable helpers:

- `agent-apt-update`
- `agent-apt-install PACKAGE...` with package-name validation and no arbitrary flags
- `agent-systemctl-daemon-reload`
- `agent-service ACTION UNIT...` limited to safe actions such as `reload`, `restart`, `try-restart`, `status`, and unit-name validation
- `agent-tail-log /var/log/FILE` limited to `/var/log/*` and bounded output

## Validation sequence

Run locally/during staging before deployment:

```bash
bash -n setup-agent-sudo-user.sh
visudo -cf agent-sudoers.conf
# Also validate generated broad-mode sudoers snippets before deployment:
#   cat agent-sudoers.conf <(printf '\nagent ALL=(root) PASSWD: ALL\n') | visudo -cf -
#   cat agent-sudoers.conf <(printf '\nagent ALL=(root) NOPASSWD: ALL\n') | visudo -cf -
shellcheck setup-agent-sudo-user.sh   # if available
```

After deployment on the target:

```bash
id agent
getent passwd agent
getent group agents
stat -c '%A %U:%G %n' ~agent ~agent/.ssh ~agent/.ssh/authorized_keys
visudo -cf /etc/sudoers.d/90-agent-sudo-user
ssh -i ~/.ssh/<target>-agent_ed25519 -o BatchMode=yes agent@<host> 'id && hostname'
ssh -i ~/.ssh/<target>-agent_ed25519 -o BatchMode=yes agent@<host> 'sudo -n whoami'
ssh -i ~/.ssh/<target>-agent_ed25519 -o BatchMode=yes agent@<host> 'sudo -n /usr/local/sbin/agent-service status ssh.service || sudo -n systemctl status ssh.service'
ssh -i ~/.ssh/<target>-agent_ed25519 -o BatchMode=yes agent@<host> 'sudo -n /usr/local/sbin/agent-tail-log /var/log/syslog >/dev/null || true'
```

If legacy sudoers files exist, retire by backing up outside `/etc/sudoers.d` before removal, then validate the aggregate policy and smoke-test sudo:

```bash
sudo install -d -o root -g root -m 0700 /root/agent-sudoers-backups
sudo cp -a /etc/sudoers.d/<legacy-agent-file> /root/agent-sudoers-backups/<legacy-agent-file>.$(date +%Y%m%d-%H%M%S).bak
sudo rm /etc/sudoers.d/<legacy-agent-file>
sudo visudo -cf /etc/sudoers
sudo -u agent sudo -n whoami   # or test remotely over SSH as agent
```

Adjust service names (`ssh.service` vs `sshd.service`) and log files (`/var/log/syslog` vs `/var/log/messages`) by distro.

## Rollback

If access must be revoked quickly:

```bash
sudo rm -f /etc/sudoers.d/90-agent-sudo-user
sudo passwd -l agent
sudo install -o agent -g agents -m 0600 /dev/null ~agent/.ssh/authorized_keys
```

If the account should be removed entirely, first archive anything needed from `~agent`, then use the distro's user deletion command carefully.

## Documentation

For significant access setup or changes, document in Den space `den-network`:

- datetime;
- target host;
- requested access model;
- files installed/changed;
- sudo surface granted;
- SSH key source;
- verification result;
- rollback path;
- follow-up risks.

## Supporting files

- `templates/setup-agent-sudo-user.sh` — reviewed starter script for creating the `agent` user, SSH directory, helpers, and validated sudoers drop-in.
- `templates/agent-sudoers.conf` — constrained sudoers starter policy.
- `references/den-srv-agent-sudo-access-prep.md` — session note capturing the den-srv prep discussion and safety decisions.

## Pitfalls

1. **Reading existing sudoers with sudo is itself an escalation.** If a sudoers source is root-only, ask before reading it; do not normalize unnecessary privilege use.
2. **Broad `/etc` read access leaks secrets.** Even read-only helpers can disclose `/etc/shadow`, service credentials, tokens, and private keys.
3. **Supplementary groups can be root-equivalent.** `docker`, `lxd`, `libvirt`, and similar groups must be deliberate host-specific decisions.
4. **`NOPASSWD:ALL` destroys audit boundaries.** It is fast, but it removes the useful distinction between agent work and root work.
5. **Sudoers templates hardcode users.** If a template grants `agent`, refuse `AGENT_USER=other` unless the template is regenerated or separately reviewed.
6. **Dry-run scripts can lie about later state.** Verify actual installed files, modes, and sudoers parse results after real deployment.
7. **Generate agent SSH keys as the client identity, not root.** The private key should live where the agent process can read it; only the public key is installed on the server by root/sudo.
8. **Restrict dedicated agent keys by source IP when practical.** Use `ip route get <target>` to find the source IP and prepend `from="<source-ip>"` to the authorized key line.
10. **Audit existing state before rerunning setup.** If `agent` or old sudoers files already exist, verify the real state first (`id`, `getent`, SSH perms, sudo smoke, sudoers drop-ins). Re-running setup can add a second policy file rather than replacing the old one.
11. **Retire legacy sudoers by backup-then-remove, not blind deletion.** Move/copy old files to a root-only backup directory outside `/etc/sudoers.d`, remove the active drop-in, run `visudo -cf /etc/sudoers`, then verify `sudo -n whoami` still works through the intended policy.
12. **Terminal/TUI copy-paste can be unreliable.** When the user reports copy/paste trouble, run local key-generation and file-inspection steps directly as the agent. Avoid asking the user to copy long public keys; prefer pointing to a public key file, using short commands, or a temporary LAN-only public-key transfer service with explicit approval.
