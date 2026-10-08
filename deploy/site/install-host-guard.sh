#!/usr/bin/env bash
# Install the model PC hang guard check on the site host (Ubuntu, systemd). Run once:
#
#   sudo deploy/site/install-model-guard-check.sh [--dry-run] [--host rosy@100.98.162.71]
#
# Creates the rosy-model-guard system user, /etc/rosy/model-guard/id_ed25519 (only when
# absent) and known_hosts, /usr/local/bin/rosy-model-guard-check, and the
# rosy-model-guard.service/.timer (every 10 min). Prints the public key: pass it to
# `sudo deploy/site/install-model-pc-guard.sh --site-key "<key>"` on the model PC. The
# timer is enabled only once the model PC answers `health` with that key.
set -euo pipefail

DRY=0
HOST=rosy@100.98.162.71
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --host) HOST=$2; shift ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
HERE=$(cd "$(dirname "$0")" && pwd)
run() { if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }
[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run with sudo (or --dry-run)" >&2; exit 1; }

id rosy-model-guard >/dev/null 2>&1 || run useradd --system --home /var/lib/rosy-model-guard --shell /usr/sbin/nologin rosy-model-guard
run install -d -m 0750 -o rosy-model-guard -g rosy-model-guard /etc/rosy/model-guard /var/lib/rosy-model-guard
if [ ! -f /etc/rosy/model-guard/id_ed25519 ]; then
  run ssh-keygen -q -t ed25519 -N "" -C rosy-model-guard -f /etc/rosy/model-guard/id_ed25519
  run chown rosy-model-guard:rosy-model-guard /etc/rosy/model-guard/id_ed25519 /etc/rosy/model-guard/id_ed25519.pub
fi
if [ ! -s /etc/rosy/model-guard/known_hosts ]; then
  run sh -c "ssh-keyscan -T 10 ${HOST#*@} > /etc/rosy/model-guard/known_hosts 2>/dev/null"
fi
run install -m 0755 "$HERE/rosy-model-guard-check" /usr/local/bin/rosy-model-guard-check
cat_unit() {
  if [ "$DRY" = 1 ]; then echo "+ write $1"; else cat > "$1"; fi
}
cat_unit /etc/systemd/system/rosy-model-guard.service <<EOF
[Unit]
Description=Rosy model PC hang guard check
After=network-online.target

[Service]
Type=oneshot
User=rosy-model-guard
Environment=GUARD_HOST=$HOST
ExecStart=/usr/local/bin/rosy-model-guard-check
EOF
cat_unit /etc/systemd/system/rosy-model-guard.timer <<'EOF'
[Unit]
Description=Check the Rosy model PC every 10 minutes

[Timer]
OnBootSec=10min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
EOF
run systemctl daemon-reload
echo "site guard public key (give to install-model-pc-guard.sh --site-key):"
[ "$DRY" = 1 ] || cat /etc/rosy/model-guard/id_ed25519.pub
if [ "$DRY" = 0 ] && sudo -u rosy-model-guard ssh -i /etc/rosy/model-guard/id_ed25519 -o BatchMode=yes \
     -o UserKnownHostsFile=/etc/rosy/model-guard/known_hosts -o ConnectTimeout=10 "$HOST" health >/dev/null 2>&1; then
  systemctl enable --now rosy-model-guard.timer && echo "timer enabled"
else
  echo "timer not enabled yet: install the key on the model PC, then rerun this script"
fi
