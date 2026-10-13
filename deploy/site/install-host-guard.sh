#!/usr/bin/env bash
# Install the host guard (D-530) on the guarding host: the site PC, or the model PC as the
# site PC's reverse guard. Run once:
#
#   sudo deploy/site/install-host-guard.sh [--dry-run]
#
# Creates the rosy-host-guard system user, /etc/rosy/host-guard/id_ed25519 (only when absent),
# hosts.conf from host-guard.conf.example (only when absent; edit it), known_hosts for every pc
# line, and /usr/local/bin/rosy-host-guard. Prints the public key for
# `sudo deploy/hosts/common/install-guard-remote.sh --site-key "<key>"` on each watched PC, then
# probes `health` on each. The units and their timer come from the site desired state:
# `sudo python3 deploy/hosts/common/rosy-host-state install site`.
set -euo pipefail

DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
HERE=$(cd "$(dirname "$0")" && pwd)
DIR=/etc/rosy/host-guard
run() { if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }
[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run with sudo (or --dry-run)" >&2; exit 1; }

id rosy-host-guard >/dev/null 2>&1 || run useradd --system --home /var/lib/rosy-host-guard --shell /usr/sbin/nologin rosy-host-guard
run install -d -m 0750 -o rosy-host-guard -g rosy-host-guard "$DIR" /var/lib/rosy-host-guard
if [ ! -f "$DIR/id_ed25519" ]; then
  run ssh-keygen -q -t ed25519 -N "" -C rosy-host-guard -f "$DIR/id_ed25519"
  run chown rosy-host-guard:rosy-host-guard "$DIR/id_ed25519" "$DIR/id_ed25519.pub"
fi
[ -f "$DIR/hosts.conf" ] || run install -m 0644 "$HERE/host-guard.conf.example" "$DIR/hosts.conf"
run install -m 0755 "$HERE/rosy-host-guard" /usr/local/bin/rosy-host-guard

targets=$(awk '!/^#/ && $2 == "pc" {print $3}' "$DIR/hosts.conf" 2>/dev/null || true)
for target in $targets; do
  case "$target" in *"<"*) echo "edit $DIR/hosts.conf: $target is still a placeholder"; continue ;; esac
  grep -q "${target#*@}" "$DIR/known_hosts" 2>/dev/null ||
    run sh -c "ssh-keyscan -T 10 ${target#*@} >> $DIR/known_hosts 2>/dev/null"
done
echo "guard public key (give to install-guard-remote.sh --site-key on each watched PC):"
[ "$DRY" = 1 ] || cat "$DIR/id_ed25519.pub"
[ "$DRY" = 1 ] && exit 0
for target in $targets; do
  case "$target" in *"<"*) continue ;; esac
  if sudo -u rosy-host-guard ssh -i "$DIR/id_ed25519" -o BatchMode=yes -o ConnectTimeout=10 \
       -o UserKnownHostsFile="$DIR/known_hosts" "$target" health; then
    echo "$target: health OK"
  else
    echo "$target: no answer yet (install the key there, then rerun)"
  fi
done
