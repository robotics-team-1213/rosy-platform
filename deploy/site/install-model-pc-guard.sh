#!/usr/bin/env bash
# Hang guard for the model PC (OMEN). Run once on the model PC:
#
#   sudo deploy/site/install-model-pc-guard.sh [--dry-run] [--site-key "ssh-ed25519 AAAA... rosy-model-guard"]
#
# 2026-10-07 the model PC froze at 02:13 under memory pressure (NVIDIA NV_ERR_NO_MEMORY,
# ollama "host memory pressure", then an endless i915 "Purging GPU memory") and stayed down
# 17 h until someone pressed the power button. Its 32 GiB swap is a ZFS zvol, which can
# deadlock when the kernel needs memory to write swap. This script:
#   1. hardware watchdog: loads iTCO_wdt (Intel) or wdat_wdt, then systemd pets it
#      (RuntimeWatchdogSec=30s, RebootWatchdogSec=2min). A frozen kernel stops petting and
#      the board resets. Skipped with a message when no /dev/watchdog appears.
#   2. kernel: panic=10 and softlockup_panic=1, so a detected lockup reboots instead of hanging.
#   3. swap: turns the zvol swap off and comments its fstab line; zram grows to 100 % of RAM
#      (compressed RAM, not ZFS). The 4 GiB encrypted swap partition stays.
#   4. remote guard: /usr/local/sbin/rosy-model-guard-remote and a sudoers line that lets the
#      login user run only `systemctl reboot`; with --site-key, an authorized_keys entry that
#      can run nothing but that command (deploy/site/install-model-guard-check.sh is the
#      site host side).
# Idempotent. --dry-run prints what would change and needs no root.
set -euo pipefail

DRY=0
SITE_KEY=""
USER_NAME=${SUDO_USER:-rosy}
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --site-key) SITE_KEY=$2; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
HERE=$(cd "$(dirname "$0")" && pwd)
run() { if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }
put() {  # put <path> <mode> <content>
  if [ "$DRY" = 1 ]; then echo "+ write $1 ($2)"; printf '%s\n' "$3" | sed 's/^/    /'; return; fi
  printf '%s\n' "$3" > "$1.tmp" && chmod "$2" "$1.tmp" && mv "$1.tmp" "$1"
}
[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run with sudo (or --dry-run)" >&2; exit 1; }

# 1. hardware watchdog
for module in iTCO_wdt wdat_wdt; do
  if run modprobe "$module" 2>/dev/null && { [ "$DRY" = 1 ] || [ -e /dev/watchdog0 ]; }; then
    put /etc/modules-load.d/rosy-watchdog.conf 0644 "$module"
    put /etc/systemd/system.conf.d/rosy-watchdog.conf 0644 "[Manager]
RuntimeWatchdogSec=30s
RebootWatchdogSec=2min"
    run systemctl daemon-reexec
    echo "watchdog: $module"
    break
  fi
done
[ "$DRY" = 1 ] || [ -e /dev/watchdog0 ] || echo "watchdog: no device; hard hangs still need a power press" >&2

# 2. kernel lockups reboot
put /etc/sysctl.d/90-rosy-hang.conf 0644 "kernel.panic = 10
kernel.softlockup_panic = 1"
run sysctl -q --system

# 3. swap off ZFS, zram to the size of RAM
if grep -qE '^[^#].*/dev/zvol/rpool/swap2' /etc/fstab; then
  run swapoff /dev/zvol/rpool/swap2 || echo "swapoff failed (in use?); fstab still changed, reboot to apply" >&2
  run sed -i 's|^\(/dev/zvol/rpool/swap2 .*\)$|# rosy-model-pc-guard: zvol swap can deadlock under pressure\n# \1|' /etc/fstab
fi
if [ -f /etc/default/zramswap ]; then
  run sed -i -E 's/^#?PERCENT=.*/PERCENT=100/; s/^#?ALGO=.*/ALGO=zstd/' /etc/default/zramswap
  grep -q '^PERCENT=' /etc/default/zramswap || run sh -c 'echo PERCENT=100 >> /etc/default/zramswap'
  run systemctl restart zramswap.service
fi

# 4. remote guard command and its one sudo right
run install -m 0755 "$HERE/rosy-model-guard-remote" /usr/local/sbin/rosy-model-guard-remote
put /etc/sudoers.d/rosy-model-guard 0440 "$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl reboot"
[ "$DRY" = 1 ] || visudo -cf /etc/sudoers.d/rosy-model-guard >/dev/null
if [ -n "$SITE_KEY" ]; then
  KEYS=/home/$USER_NAME/.ssh/authorized_keys
  LINE="command=\"/usr/local/sbin/rosy-model-guard-remote\",restrict $SITE_KEY"
  if [ "$DRY" = 1 ]; then echo "+ append to $KEYS: $LINE"
  elif ! grep -qF "$SITE_KEY" "$KEYS" 2>/dev/null; then
    install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/.ssh"
    printf '%s\n' "$LINE" >> "$KEYS" && chown "$USER_NAME:$USER_NAME" "$KEYS" && chmod 0600 "$KEYS"
  fi
fi
echo "done. Check: swapon --show; ls /dev/watchdog*; sysctl kernel.panic; sudo -l -U $USER_NAME"
