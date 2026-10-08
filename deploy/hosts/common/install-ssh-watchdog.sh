#!/usr/bin/env bash
# Install or refresh the host-local SSH self-recovery check (idempotent). Run as root
# from this folder:  sudo bash install-ssh-watchdog.sh [--robot]
# --robot (or a ROSY robot detected by its rosy-network unit) writes ROSY_ROBOT=1:
# no gateway/NetworkManager steps and no reboot while rosy-core is active.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
robot=0
[ "${1:-}" = --robot ] && robot=1
systemctl cat rosy-network.service >/dev/null 2>&1 && robot=1
install -m 0755 "$here/rosy-ssh-watchdog" /usr/local/sbin/rosy-ssh-watchdog
install -m 0644 "$here/rosy-ssh-watchdog.service" /etc/systemd/system/rosy-ssh-watchdog.service
install -m 0644 "$here/rosy-ssh-watchdog.timer" /etc/systemd/system/rosy-ssh-watchdog.timer
# ROSY_ROBOT is rewritten on every install so a robot can never lose it; other
# local settings (BOOT_GRACE_S, MAX_REBOOTS, ...) are kept.
f=/etc/default/rosy-ssh-watchdog
touch "$f"
grep -v -e '^ROSY_ROBOT=' -e '^CHECK_GATEWAY=' "$f" > "$f.new" || true
echo "ROSY_ROBOT=$robot" >> "$f.new"
mv "$f.new" "$f"; chmod 0644 "$f"
# sshd and tailscaled must come back on their own after any reboot.
systemctl enable ssh >/dev/null 2>&1 || systemctl enable sshd >/dev/null 2>&1 || true
if systemctl cat tailscaled.service >/dev/null 2>&1; then systemctl enable tailscaled >/dev/null 2>&1 || true; fi
systemctl daemon-reload
systemctl enable --now rosy-ssh-watchdog.timer
# Dry run with the installed settings; it never changes the counters.
( set -a; . /etc/default/rosy-ssh-watchdog; set +a; DRY_RUN=1 /usr/local/sbin/rosy-ssh-watchdog )
echo "rosy-ssh-watchdog installed (ROSY_ROBOT=$robot): $(systemctl is-active rosy-ssh-watchdog.timer)"
