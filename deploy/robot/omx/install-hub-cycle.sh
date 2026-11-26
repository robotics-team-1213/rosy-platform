#!/usr/bin/env bash
# Root helper for the OMX camera heal's hub power cycle (PR #917 review item 4). Run once on each cell PC:
#
#   sudo deploy/robot/omx/install-hub-cycle.sh --user <cell login> [--dry-run]
#
# Installs, root-owned:
#   /usr/local/sbin/rosy-omx-hub-cycle        the helper: two checked arguments, no shell, no imports from the release tree
#   /etc/sudoers.d/rosy-omx-hub-cycle         "<user> ALL=(root) NOPASSWD: /usr/local/sbin/rosy-omx-hub-cycle"
# Re-run after the helper changes: the installed copy is not part of the release switch. Idempotent.
# --dry-run prints what would change and needs no root.
set -euo pipefail

DRY=0
USER_NAME=${SUDO_USER:-}
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --user) USER_NAME=$2; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
[[ "$USER_NAME" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "--user <cell login> is required" >&2; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
HELPER=/usr/local/sbin/rosy-omx-hub-cycle
SUDOERS=/etc/sudoers.d/rosy-omx-hub-cycle
LINE="$USER_NAME ALL=(root) NOPASSWD: $HELPER"

if [ "$DRY" = 1 ]; then
  echo "+ install -o root -g root -m 0755 $HERE/rosy-omx-hub-cycle $HELPER"
  echo "+ write $SUDOERS (0440)"; echo "    $LINE"
  exit 0
fi
[ "$(id -u)" = 0 ] || { echo "run with sudo (or --dry-run)" >&2; exit 1; }
install -o root -g root -m 0755 "$HERE/rosy-omx-hub-cycle" "$HELPER"
TMP=$(mktemp /etc/sudoers.d/.rosy-omx-hub-cycle.XXXXXX)
printf '%s\n' "$LINE" > "$TMP"
chmod 0440 "$TMP"; chown root:root "$TMP"
visudo -cf "$TMP" >/dev/null || { rm -f "$TMP"; echo "sudoers check failed; nothing installed" >&2; exit 1; }
mv "$TMP" "$SUDOERS"
echo "done. Check: sudo -l -U $USER_NAME | grep rosy-omx-hub-cycle"
