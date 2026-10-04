#!/usr/bin/env bash
# D-446 rootless installation. Existing config/key and watch settings are preserved.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=${XDG_DATA_HOME:-$HOME/.local/share}/rosy/model-code
CONF=${XDG_CONFIG_HOME:-$HOME/.config}/rosy/model-code.json
LIB=$HOME/.local/lib/rosy-model-code
UNITS=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
PYTHON= PUBLIC= KEY_ID= WORK= WATCH= ENABLE=0
LEGACY=()
while [ $# -gt 0 ]; do
  case "$1" in
    --python) PYTHON=$2; shift ;;
    --public-key) PUBLIC=$2; shift ;;
    --key-id) KEY_ID=$2; shift ;;
    --work-dir) WORK=$2; shift ;;
    --legacy-root) LEGACY+=("$2"); shift ;;
    --watch-config) WATCH=$2; shift ;;
    --enable) ENABLE=1 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
[ "$(id -u)" -ne 0 ] || { echo 'install as the model-PC operator user, without sudo' >&2; exit 2; }
for value in "$PYTHON" "$PUBLIC" "$WORK"; do
  case "$value" in /*) ;; *) echo 'python, public-key and work-dir must be absolute paths' >&2; exit 2 ;; esac
done
[ -x "$PYTHON" ] && [ -r "$PUBLIC" ] && [ -d "$WORK" ] && [ -n "$KEY_ID" ] && [ ${#LEGACY[@]} -gt 0 ]
# Units deliberately use the standard home paths; refuse XDG overrides rather
# than installing a service which silently reads a different configuration.
[ "$CONF" = "$HOME/.config/rosy/model-code.json" ] || { echo 'custom XDG_CONFIG_HOME is not supported by these units' >&2; exit 2; }
install -d -m 0700 "$ROOT" "$ROOT/inbox" "$(dirname "$CONF")" "$LIB" "$UNITS"
if [ -e "$ROOT/public-key.pem" ]; then
  cmp -s "$PUBLIC" "$ROOT/public-key.pem" || { echo 'enrolled key differs; key rotation needs a separate operation' >&2; exit 2; }
else
  install -m 0600 "$PUBLIC" "$ROOT/public-key.pem"
fi
if [ ! -e "$CONF" ]; then
  python3 - "$CONF" "$ROOT" "$KEY_ID" "$PYTHON" "$WORK" "${LEGACY[@]}" <<'PY'
import json,sys,pathlib
out,root,key,python,work,*legacy=sys.argv[1:]
pathlib.Path(out).write_text(json.dumps(dict(root=root,key_id=key,public_key=root+'/public-key.pem',python=python,work_dir=work,legacy_roots=legacy))+'\n')
PY
  chmod 0600 "$CONF"
fi
install -m 0644 "$HERE/rosy_model_code.py" "$HERE/candidate_signing.py" "$LIB/"
python3 -I "$LIB/rosy_model_code.py" --config "$CONF" status
install -m 0644 "$HERE/rosy-model-code-update.service" "$HERE/rosy-model-code-update.timer" \
  "$HERE/rosy-model-code-watch.service" "$HERE/rosy-model-code-watch.timer" "$UNITS/"
if [ -n "$WATCH" ]; then
  [ -e "$(dirname "$CONF")/model-watch.yaml" ] || install -m 0600 "$WATCH" "$(dirname "$CONF")/model-watch.yaml"
fi
systemctl --user daemon-reload
if [ "$ENABLE" = 1 ]; then
  systemctl --user enable --now rosy-model-code-update.timer
  if [ -e "$(dirname "$CONF")/model-watch.yaml" ]; then
    # Doctor is a readiness check, not a shadow push. Non-zero leaves watch disabled.
    python3 -I "$LIB/rosy_model_code.py" --config "$CONF" exec rosy_ml.py doctor --watch-config "$(dirname "$CONF")/model-watch.yaml"
    systemctl --user enable --now rosy-model-code-watch.timer
  fi
fi
echo 'installed: model-PC code control; existing checkout, venv, data and credentials preserved'
