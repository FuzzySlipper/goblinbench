#!/usr/bin/env bash
# verify-bwrap.sh — Confirm bwrap is usable on this host with the patterns
# the subprocess-sandbox skill relies on. Run this BEFORE committing to a
# bubblewrap-based design on a new host. Exits 0 if all checks pass, 1
# otherwise. Prints a one-line summary at the end.

set -u

pass=0
fail=0

ok() { printf "  ok    %s\n" "$1"; pass=$((pass + 1)); }
bad() { printf "  FAIL  %s\n" "$1"; fail=$((fail + 1)); }

echo "bwrap verification for subprocess-sandbox skill"
echo "================================================"
echo

# 1. bwrap binary exists and is executable
if command -v bwrap >/dev/null 2>&1; then
    ver=$(bwrap --version 2>/dev/null)
    ok "bwrap found: $ver"
else
    bad "bwrap not in PATH"
    echo
    echo "FATAL: bwrap is the only sandbox primitive this skill assumes."
    echo "Install:  Arch  -> pacman -S bubblewrap"
    echo "          Debian-> apt install bubblewrap"
    echo "          NixOS -> nix-env -iA nixos.bubblewrap"
    echo
    echo "Summary: 0 passed, 1 failed (binary missing)"
    exit 1
fi

# 2. Kernel supports user namespaces (required for non-setuid bwrap)
if [ -r /proc/sys/kernel/unprivileged_userns_clone ] \
   || [ -d /proc/self/ns/user ]; then
    ok "user namespaces appear available"
else
    bad "no /proc/self/ns/user — kernel likely lacks user namespace support"
fi

# 3. Basic exec works — simplest possible bwrap
if bwrap --ro-bind / / --tmpfs /tmp -- /bin/true 2>/dev/null; then
    ok "basic exec via bwrap works"
else
    bad "bwrap --ro-bind / / -- /bin/true failed"
fi

# 4. Host /usr/bin/bash is reachable through --ro-bind / /
if bwrap --ro-bind / / --tmpfs /tmp -- /usr/bin/bash -c 'echo bwrap-bash-ok' 2>/dev/null \
   | grep -q '^bwrap-bash-ok$'; then
    ok "inner bash exec works through --ro-bind / /"
else
    bad "inner bash exec failed — Gotcha 1 from references/bwrap-gotchas.md applies"
fi

# 5. Writable bind under tmpfs parent works
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
touch "$workdir/seed"
if bwrap --ro-bind / / --tmpfs /tmp \
        --bind "$workdir" /tmp/sb-verify-work \
        -- /usr/bin/bash -c 'touch /tmp/sb-verify-work/newfile && echo ok' 2>/dev/null \
   | grep -q '^ok$'; then
    ok "writable bind under tmpfs parent works"
else
    bad "writable bind under tmpfs parent failed — Gotcha 2 applies"
fi

# 6. Write escape to host /tmp is blocked when --tmpfs /tmp
if bwrap --ro-bind / / --tmpfs /tmp --bind "$workdir" /tmp/sb-verify-work \
        -- /usr/bin/bash -c 'touch /tmp/escape-attempt' 2>/dev/null; then
    if [ -e /tmp/escape-attempt ]; then
        bad "agent escaped to host /tmp"
        rm -f /tmp/escape-attempt
    else
        ok "host /tmp not polluted (tmpfs overlay working)"
    fi
else
    # Non-zero exit is fine here — we just want to check host /tmp isn't touched
    if [ -e /tmp/escape-attempt ]; then
        bad "agent escaped to host /tmp despite non-zero exit"
        rm -f /tmp/escape-attempt
    else
        ok "host /tmp not polluted (tmpfs overlay working)"
    fi
fi

# 7. Write to read-only host path is blocked
if bwrap --ro-bind / / --tmpfs /tmp --bind "$workdir" /tmp/sb-verify-work \
        -- /usr/bin/bash -c 'touch /etc/sb-verify-escape 2>/dev/null' 2>/dev/null; then
    :
fi
if [ -e /etc/sb-verify-escape ]; then
    bad "agent wrote to /etc — read-only bind not working"
    rm -f /etc/sb-verify-escape
else
    ok "host /etc not writable (read-only bind working)"
fi

echo
echo "Summary: $pass passed, $fail failed"
if [ "$fail" -eq 0 ]; then
    echo "Ready to use the subprocess-sandbox skill on this host."
    exit 0
else
    echo "Sandbox design will not work as expected on this host. See references/bwrap-gotchas.md."
    exit 1
fi
