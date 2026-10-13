#!/usr/bin/env bash
# Install or refresh the D-373 site model watcher on the Ubuntu site host.
#
#   sudo deploy/site/install-model-watch.sh [--dry-run] [--src DIR] [--venv DIR]
#
# Idempotent. Creates the rosy-model-watch system user, /etc/rosy/model-watch
# (site SSH key, known_hosts), /etc/rosy/model-watch.yaml from the example if
# absent, the store folder and its layout (when missing), a unit drop-in that
# makes the store writable for the service, installs the unit and timer, and
# enables the timer only once the config has no <...> placeholders left. With
# `backend: hf` only, an EMPTY token file placeholder (never token content).
# Installs the unit's entry point /opt/rosy/model-watch/bin/rosy-model-watch,
# which finds the watcher in the checkout before or after the D-427 move.
# Then runs its `doctor --watch-config` as the service user. Never
# overwrites an existing config, key, known_hosts or token file.
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
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

SVC=rosy-model-watch
CONFIG=/etc/rosy/model-watch.yaml
KEYDIR=/etc/rosy/model-watch
KEY=$KEYDIR/site-ed25519
KNOWN=$KEYDIR/known_hosts
TOKEN=/etc/rosy/site-secrets/hf_token
UNITDIR=/etc/systemd/system
DROPIN=$UNITDIR/rosy-model-watch.service.d
HERE=$(cd "$(dirname "$0")" && pwd)
WRAPPER=/opt/rosy/model-watch/bin/rosy-model-watch

run() { if [ "$DRY" = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi; }
# first uncommented `key: value` of the config (the example when none is installed yet)
cfg_value() {
  local file=$CONFIG
  [ -r "$file" ] || file=$HERE/model-watch.yaml.example
  sed -n "s/^$1:[[:space:]]*//p" "$file" | head -n 1 | tr -d '\r' | sed "s/[[:space:]]*#.*$//; s/^[\"']//; s/[\"']$//"
}

[ "$DRY" = 1 ] || [ "$(id -u)" -eq 0 ] || { echo "run as root (sudo), or pass --dry-run" >&2; exit 1; }

getent passwd "$SVC" >/dev/null || run useradd --system --no-create-home --shell /usr/sbin/nologin "$SVC"
[ -d "$KEYDIR" ] || run install -d -o root -g "$SVC" -m 0750 "$KEYDIR"
[ -e "$CONFIG" ] || run install -o root -g "$SVC" -m 0640 "$HERE/model-watch.yaml.example" "$CONFIG"

# The site's own key (never an operator's): add its .pub to rosy's authorized_keys on each robot.
[ -e "$KEY" ] || run ssh-keygen -q -t ed25519 -N '' -C "$SVC@$(hostname)" -f "$KEY"
run chown "$SVC:$SVC" "$KEY"
run chmod 0600 "$KEY"
[ -e "$KNOWN" ] || run install -o root -g "$SVC" -m 0644 /dev/null "$KNOWN"

BACKEND=$(cfg_value backend)
BACKEND=${BACKEND:-inbox}
STORE=$(cfg_value store)

# The store (D-373 decision 8). A local folder is created with its layout; a NAS or
# Drive mount that already exists keeps its owner, only missing layout dirs are added.
if [ "$BACKEND" = inbox ]; then
  case "$STORE" in
    /*) ;;
    *) echo "store: must be an absolute path in $CONFIG (got '$STORE')" >&2; exit 2 ;;
  esac
  [ -d "$STORE" ] || run install -d -o "$SVC" -g "$SVC" -m 2770 "$STORE"
  for sub in datasets models models/inbox models/accepted models/rejected; do
    [ -d "$STORE/$sub" ] || run install -d -o "$SVC" -g "$SVC" -m 2770 "$STORE/$sub"
  done
  # ProtectSystem=strict: the store is the only path besides StateDirectory the unit may write
  run install -d -o root -g root -m 0755 "$DROPIN"
  if [ "$DRY" = 1 ]; then
    printf '+ write %s: [Service] ReadWritePaths=%s\n' "$DROPIN/store.conf" "$STORE"
  else
    printf '[Service]\nReadWritePaths=%s\n' "$STORE" > "$DROPIN/store.conf"
    run chmod 0644 "$DROPIN/store.conf"
  fi
fi

# Token (backend hf only): an empty placeholder with the right owner. An empty or
# missing file means no token (public repo); paste a read-only token with sudoedit.
if [ "$BACKEND" = hf ]; then
  [ -d "$(dirname "$TOKEN")" ] || run install -d -o root -g root -m 0755 "$(dirname "$TOKEN")"
  [ -e "$TOKEN" ] || run install -o root -g "$SVC" -m 0640 /dev/null "$TOKEN"
  run chown "root:$SVC" "$TOKEN"
  run chmod 0640 "$TOKEN"
fi

run install -D -o root -g root -m 0755 "$HERE/rosy-model-watch" "$WRAPPER"
run install -m 0644 "$HERE/rosy-model-watch.service" "$HERE/rosy-model-watch.timer" "$UNITDIR/"
run systemctl daemon-reload

configured=0
if [ -r "$CONFIG" ] && ! grep -v '^[[:space:]]*#' "$CONFIG" | grep -q '<[a-z-]*>'; then configured=1; fi
if [ "$configured" = 1 ]; then
  run systemctl enable --now rosy-model-watch.timer
else
  echo "timer NOT enabled: $CONFIG still has <...> placeholders"
fi

# The watcher's intake imports these; a missing one is a config error (watch exit 6).
VENV_MODULES="onnxruntime onnx cv2 numpy yaml"
VENV_PIP="onnxruntime onnx==1.23.1 opencv-python-headless numpy PyYAML"
if [ -x "$VENV/bin/python" ]; then
  for module in $VENV_MODULES; do
    if ! "$VENV/bin/python" -c "import $module" 2>/dev/null; then
      echo "venv $VENV lacks $module: sudo $VENV/bin/pip install $VENV_PIP" >&2
    fi
  done
fi

# This checkout's copy of the wrapper (none is installed yet under --dry-run) says
# whether $SRC holds the watcher at either location.
if [ "$configured" = 1 ] && [ -x "$VENV/bin/python" ] \
    && ROSY_MODEL_WATCH_SRC=$SRC bash "$HERE/rosy-model-watch" locate >/dev/null 2>&1; then
  run runuser -u "$SVC" -- env ROSY_MODEL_WATCH_SRC="$SRC" ROSY_MODEL_WATCH_VENV="$VENV" \
    "$WRAPPER" doctor --watch-config "$CONFIG" \
    || echo "doctor found problems (lines marked with a cross above)"
else
  echo "doctor skipped: needs a filled config, $VENV and a checkout in $SRC (see deploy/site/README.md)"
fi

cat <<EOF

Next steps (see deploy/site/README.md and docs/deployment/learned-perception-operators.md):
  1. Add this site key to rosy's authorized_keys on every robot:
       sudo cat $KEY.pub
  2. Pin each robot's host key in $KNOWN (from a trusted network).
  3. Fill robots and replay_root (and store, if not $STORE) in $CONFIG:  sudoedit $CONFIG
     Moving the store to a NAS or Google Drive later: mount it, change store:, re-run this script.
  4. Only with backend: hf and a private repo: paste a READ-ONLY token:  sudoedit $TOKEN
  5. Re-run this script: it enables the timer and runs doctor.
EOF
