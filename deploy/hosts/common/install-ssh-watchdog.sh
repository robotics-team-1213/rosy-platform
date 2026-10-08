#!/usr/bin/env bash
# Install or refresh the host-local SSH self-recovery check (idempotent). Run as root
# from this folder: sudo bash install-ssh-watchdog.sh
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
install -m 0755 "$here/rosy-ssh-watchdog" /usr/local/sbin/rosy-ssh-watchdog
install -m 0644 "$here/rosy-ssh-watchdog.service" /etc/systemd/system/rosy-ssh-watchdog.service
install -m 0644 "$here/rosy-ssh-watchdog.timer" /etc/systemd/system/rosy-ssh-watchdog.timer
# A ROSY robot (rosy-network present) skips the gateway check; see the script.
if [ -e /etc/systemd/system/rosy-network.service ] && [ ! -e /etc/default/rosy-ssh-watchdog ]; then
  echo "CHECK_GATEWAY=0" > /etc/default/rosy-ssh-watchdog
fi
# sshd and tailscaled must come back on their own after any reboot.
systemctl enable ssh >/dev/null 2>&1 || systemctl enable sshd >/dev/null 2>&1 || true
if systemctl list-unit-files tailscaled.service >/dev/null 2>&1; then systemctl enable tailscaled >/dev/null 2>&1 || true; fi
systemctl daemon-reload
systemctl enable --now rosy-ssh-watchdog.timer
DRY_RUN=1 /usr/local/sbin/rosy-ssh-watchdog
echo "rosy-ssh-watchdog installed: $(systemctl is-active rosy-ssh-watchdog.timer)"
