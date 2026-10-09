#!/usr/bin/env bash
# Install the guard's forced command on a watched PC (D-530). Run once per PC:
#
#   sudo deploy/hosts/common/install-guard-remote.sh [--dry-run] [--site-key "ssh-ed25519 AAAA... rosy-host-guard"] [--unit <unit>]...
#
# Installs /usr/local/sbin/rosy-host-guard-remote, /etc/rosy/host-guard/units (the units the guard
# watches and may ask the D-524 helper to restart; --unit replaces the list), and with --site-key an
# authorized_keys entry that can run nothing but the forced command. The helper and its one sudoers
# line are desired state (rosy-host-state install <role> --approve ..., D-530). Idempotent.
# --dry-run prints what would change and needs no root.
set -euo pipefail

DRY=0
SITE_KEY=""
UNITS=()
USER_NAME=${SUDO_USER:-$(id -un)}
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --site-key) SITE_KEY=$2; shift ;;
    --unit) UNITS+=("$2"); shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
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

run install -m 0755 "$HERE/rosy-host-guard-remote" /usr/local/sbin/rosy-host-guard-remote
if [ ${#UNITS[@]} -gt 0 ]; then
  run install -d -m 0755 /etc/rosy/host-guard
  put /etc/rosy/host-guard/units 0644 "$(printf '%s\n' "${UNITS[@]}")"
fi
if [ -n "$SITE_KEY" ]; then
  KEYS=/home/$USER_NAME/.ssh/authorized_keys
  LINE="command=\"/usr/local/sbin/rosy-host-guard-remote\",restrict $SITE_KEY"
  if [ "$DRY" = 1 ]; then echo "+ append to $KEYS: $LINE"
  elif ! grep -qxF -- "$LINE" "$KEYS" 2>/dev/null; then
    install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/.ssh"
    if grep -qF -- "$SITE_KEY" "$KEYS" 2>/dev/null; then
      echo "warning: $KEYS holds this key without the forced command; replacing that line" >&2
      grep -vF -- "$SITE_KEY" "$KEYS" > "$KEYS.tmp" || true
      mv "$KEYS.tmp" "$KEYS"
    fi
    printf '%s\n' "$LINE" >> "$KEYS" && chown "$USER_NAME:$USER_NAME" "$KEYS" && chmod 0600 "$KEYS"
  fi
fi
echo "done. Check: sudo -l -U $USER_NAME (rosy-host-control line); cat /etc/rosy/host-guard/units"
