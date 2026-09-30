#!/usr/bin/env bash
# Install or refresh the D-373 site model watcher on the Ubuntu site host.
#
#   sudo deploy/site/install-model-watch.sh [--dry-run] [--src DIR] [--venv DIR]
#
# Idempotent. Creates the rosy-model-watch system user, /etc/rosy/model-watch
# (site SSH key, known_hosts), /etc/rosy/model-watch.yaml from the example if
# absent, an EMPTY token file placeholder (never token content), installs the
# unit and timer, and enables the timer only once the config has no <...>
# placeholders left. Then runs `rosy_ml doctor --watch-config` as the service
# user. Never overwrites an existing config, key, known_hosts or token file.
# --dry-run prints what would change and needs no root.
set -euo pipefail

DRY=0
SRC=/opt/rosy/model-watch/src
VENV=/opt/rosy/model-watch/venv
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --src) SRC=$2; shift ;;
    --venv) VENV=$2; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

SVC=rosy-model-watch
CONFIG=/etc/rosy/model-watch.yaml
KEYDIR=/etc/rosy/model-watch
KEY=$KEYDIR/site-ed25519
KNOWN=$KEYDIR/known_hosts
TOKEN=/etc/rosy/site/secrets/hf_token
UNITDIR=/etc/systemd/system
HERE=$(cd "$(dirname "$0")" && pwd)

run() { if [ "$DRY" = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi; }

[ "$DRY" = 1 ] || [ "$(id -u)" -eq 0 ] || { echo "run as root (sudo), or pass --dry-run" >&2; exit 1; }

getent passwd "$SVC" >/dev/null || run useradd --system --no-create-home --shell /usr/sbin/nologin "$SVC"
[ -d "$KEYDIR" ] || run install -d -o root -g "$SVC" -m 0750 "$KEYDIR"
[ -e "$CONFIG" ] || run install -o root -g "$SVC" -m 0640 "$HERE/model-watch.yaml.example" "$CONFIG"

# The site's own key (never an operator's): add its .pub to rosy's authorized_keys on each robot.
[ -e "$KEY" ] || run ssh-keygen -q -t ed25519 -N '' -C "$SVC@$(hostname)" -f "$KEY"
run chown "$SVC:$SVC" "$KEY"
run chmod 0600 "$KEY"
[ -e "$KNOWN" ] || run install -o root -g "$SVC" -m 0644 /dev/null "$KNOWN"

# Token: an empty placeholder with the right owner. An empty or missing file
# means no token (public repo); paste a read-only token with sudoedit.
[ -d "$(dirname "$TOKEN")" ] || run install -d -o root -g root -m 0755 "$(dirname "$TOKEN")"
[ -e "$TOKEN" ] || run install -o root -g "$SVC" -m 0640 /dev/null "$TOKEN"
run chown "root:$SVC" "$TOKEN"
run chmod 0640 "$TOKEN"

run install -m 0644 "$HERE/rosy-model-watch.service" "$HERE/rosy-model-watch.timer" "$UNITDIR/"
run systemctl daemon-reload

configured=0
if [ -r "$CONFIG" ] && ! grep -q '<[a-z-]*>' "$CONFIG"; then configured=1; fi
if [ "$configured" = 1 ]; then
  run systemctl enable --now rosy-model-watch.timer
else
  echo "timer NOT enabled: $CONFIG still has <...> placeholders"
fi

if [ "$configured" = 1 ] && [ -x "$VENV/bin/python" ] && [ -f "$SRC/tools/perception/rosy_ml.py" ]; then
  run runuser -u "$SVC" -- "$VENV/bin/python" "$SRC/tools/perception/rosy_ml.py" doctor --watch-config "$CONFIG" \
    || echo "doctor found problems (lines marked with a cross above)"
else
  echo "doctor skipped: needs a filled config, $VENV and a checkout in $SRC (see deploy/site/README.md)"
fi

cat <<EOF

Next steps (see deploy/site/README.md and docs/deployment/learned-perception-operators.md):
  1. Add this site key to rosy's authorized_keys on every robot:
       sudo cat $KEY.pub
  2. Pin each robot's host key in $KNOWN (from a trusted network).
  3. Fill robots, repo and replay_root in $CONFIG:  sudoedit $CONFIG
  4. Private HF repo: paste a READ-ONLY token:  sudoedit $TOKEN
  5. Re-run this script: it enables the timer and runs doctor.
EOF
