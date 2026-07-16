# den-srv agent sudo access prep pattern

Session-derived details from preparing `agent` access for `den-srv` (`192.168.1.10`) from the sysadmin Hermes profile on `den-k8`.

## Decisions captured

- Access setup should be treated as an access-control design task with a semantic plan before deployment.
- User explicitly accepted broad sudo as a break-glass option because repeated human copy/paste of privileged commands is riskier during messy repair work.
- Default posture remains constrained helper sudo; broad sudo is opt-in and time-bounded.
- For non-interactive Hermes-driven repair, password prompts are brittle/unusable, so approved break-glass may need `NOPASSWD:ALL` rather than `PASSWD:ALL`.
- Prefer a dedicated agent SSH key over reusing the user's personal key; it improves revocation and attribution.
- Generate the private key as the local account that will run SSH (Hermes `agent` profile), not as root. Use root only on the target to install the public key and set permissions.
- Restrict the target `authorized_keys` entry with `from="<source-ip>"` when practical.

## Commands used locally for key generation

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 \
  -f ~/.ssh/den-srv-agent_ed25519 \
  -C "den-k8 sysadmin Hermes agent -> den-srv agent" \
  -N ""
chmod 600 ~/.ssh/den-srv-agent_ed25519
chmod 644 ~/.ssh/den-srv-agent_ed25519.pub
ssh-keygen -lf ~/.ssh/den-srv-agent_ed25519.pub
```

Find source IP for an SSH `from=` restriction:

```bash
ip route get 192.168.1.10
# observed in session: src 192.168.1.22
```

## Verification performed in staging

```bash
bash -n /home/stash/setup-agent-sudo-user.sh
visudo -cf /home/stash/agent-sudoers.template
```

Also simulated sudoers files with each broad mode appended and verified both parsed with `visudo -cf`.

## Target findings from den-srv

The target already had an `agent` account, so the plan shifted from creation to auditing/reconciling existing state.

Observed before enabling broad sudo:

- `agent@192.168.1.10` SSH worked after installing the dedicated public key.
- `agent` identity: `uid=1001(agent) gid=1001(agents) groups=1001(agents)`.
- passwd entry: `agent:x:1001:1001::/home/agent:/bin/sh`.
- SSH modes were acceptable: `/home/agent/.ssh` `0700`, `authorized_keys` `0600`.
- `sudo -n true` failed, so old sudoers did not provide usable non-interactive sudo.

After the user ran the new setup script with `ENABLE_NOPASSWD_ALL=1`:

- `agent` groups became `agents, adm, systemd-journal`.
- `sudo -n whoami` returned `root`.
- New active policy: `/etc/sudoers.d/90-agent-sudo-user` with constrained helpers plus `agent ALL=(root) NOPASSWD: ALL`.
- Old policy `/etc/sudoers.d/90-agents` remained until explicitly retired.

Legacy sudoers retirement pattern used:

```bash
backup_dir=/root/agent-sudoers-backups
backup_file="$backup_dir/90-agents.$(date +%Y%m%d-%H%M%S).bak"
sudo install -d -o root -g root -m 0700 "$backup_dir"
sudo cp -a /etc/sudoers.d/90-agents "$backup_file"
sudo rm /etc/sudoers.d/90-agents
sudo visudo -cf /etc/sudoers
sudo -n whoami
```

Actual backup created:

```text
/root/agent-sudoers-backups/90-agents.20260508-182902.bak
```

## Pitfalls found

- A broad root read helper over `/etc/*` was initially tempting, then removed. Even read-only `/etc` access can expose secrets (`shadow`, service credentials, tokens, private keys). Keep file-read helpers narrow and task-specific.
- Do not assume the account is absent. Existing `agent` users and legacy sudoers files are common on this fleet; audit first, then reconcile.
- User's TUI/terminal stack may make copy/paste unreliable. Run local commands directly when safe; give short target-side commands and file paths instead of long blobs when possible.
