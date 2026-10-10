#!/usr/bin/env bash
# D-553 addendum 4: the robot side of tools/release/ship.py, one ssh session per
# robot instead of rosy-release-push.ps1's 13 (each ~2.5 s from this PC). Runs
# as root (`sudo -n bash -s`); ship.py sends this file, the repo's
# rosy-release-unpack.sh and the signed tarball in the same stdin.
#
#   rosy-ship-remote.sh WORKDIR RELEASE_ID BASE_ID MODE SYNC HOLDER
#     WORKDIR  root-owned scratch dir holding rosy-release-unpack.sh and <id>.tar.gz
#     MODE     full   -> activate-release.sh (stops/starts the runtime), then the
#                        CORE release check and CORE readiness, as the push does
#              camera -> activator --restart-unit rosy-camera.service: CORE, I/O
#                        and the rest keep running. Falls back to full when the
#                        installed activator predates it, the base is not the
#                        current release (CORE's code must be the base's), CORE is
#                        not active, or rosy-navigation (loads control nodes) is.
#     SYNC     1 -> sync-image-layer.py of the new release, restart the active
#                   units it lists, CORE readiness again if any; 0 -> skip (the
#                   delta changed no deploy/robot/native file)
#     HOLDER   D-412 claim holder name
# Prints "PHASE <name> <seconds>" lines and a final "SHIP_OK ..." line.
set -uo pipefail

WORK="$1"; ID="$2"; BASE="$3"; MODE="$4"; SYNC="$5"; HOLDER="$6"
R="${ROSY_SHIP_ROOT:-}"  # tests only: a scratch root instead of /
export ROSY_ROOT="${R:-/}"
RT="$R/opt/rosy/native-runtime"
KEY="${ROSY_RELEASE_PUBLIC_KEY:-$R/etc/rosy/trusted-release-keys/rosy-release-2026-01.pem}"
T0=${EPOCHREALTIME/./}; LAST=$T0
phase() {
  local now=${EPOCHREALTIME/./}
  printf 'PHASE %s %d.%01d\n' "$1" $(((now - LAST) / 1000000)) $((((now - LAST) / 100000) % 10))
  LAST=$now
}
die() { echo "SHIP_FAILED $*"; exit 1; }
core_ready() {
  ( set -a; [ -f "$R/etc/rosy/runtime.env" ] && . "$R/etc/rosy/runtime.env"; set +a
    exec python3 -B "$RT/wait-core-ready.py" ) || die "CORE readiness failed; run rosy-release-push.ps1 -Rollback"
}

[[ "$ID" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$ ]] || die "bad release id $ID"
if [ -f "$RT/rosy_claim.py" ]; then
  python3 "$RT/rosy_claim.py" acquire --holder "$HOLDER" --purpose push --ttl-s 1800 >/dev/null \
    || die "claim refused (an update or another push holds $HOSTNAME)"
  trap 'python3 "$RT/rosy_claim.py" release --holder "$HOLDER" >/dev/null' EXIT
fi
phase claim

bash "$WORK/rosy-release-unpack.sh" "$ID" "$WORK/$ID.tar.gz" "$R/opt/rosy/releases" || die "unpack"
phase unpack

if [ "$MODE" = camera ]; then
  if ! grep -q -- '--restart-unit' "$RT/native_release.py"; then
    echo "NOTE installed activator predates camera-only activation: full"; MODE=full
  elif [ "$(readlink -f "$R/opt/rosy/current")" != "$(readlink -f "$R/opt/rosy/releases/$BASE")" ]; then
    echo "NOTE current release is not the base $BASE: full"; MODE=full
  elif ! systemctl is-active --quiet rosy-core.service; then
    echo "NOTE CORE is not running: full"; MODE=full
  elif systemctl is-active --quiet rosy-navigation.service; then
    echo "NOTE rosy-navigation runs control nodes too: full"; MODE=full
  fi
fi
if [ "$MODE" = camera ]; then
  python3 -B "$RT/native_release.py" --root "$ROSY_ROOT" --public-key "$KEY" \
    activate --release-id "$ID" --restart-unit rosy-camera.service || die "activate (camera; rolled back)"
  phase activate-camera
else
  "$RT/activate-release.sh" "$ID" || die "activate (rolled back by the activator)"
  phase activate
  p=$(systemctl show -p MainPID --value rosy-core.service)
  [ "$(readlink -f "/proc/$p/cwd")" = "$(readlink -f "$R/opt/rosy/current")" ] || {
    echo "NOTE CORE still on the previous release; restarting rosy-core"
    systemctl restart rosy-core.service || die "CORE restart failed; run rosy-release-push.ps1 -Rollback"
  }
  core_ready
  phase core-ready
fi

if [ "$SYNC" = 1 ]; then
  out=$(python3 -B "$R/opt/rosy/releases/$ID/deploy/robot/native/sync-image-layer.py") || die "image-layer sync: $out"
  units=$(printf '%s\n' "$out" | tail -n 1 | python3 -c '
import json, re, sys
d = json.load(sys.stdin)
assert d["ok"], d
print(" ".join(u for u in d["restart_units"] if re.fullmatch(r"rosy-[A-Za-z0-9-]+\.(service|path|timer)", u)))
') || die "image-layer sync result unreadable"
  if [ -n "$units" ]; then
    # shellcheck disable=SC2086
    systemctl restart $units || die "restart $units"
    echo "restarted: $units"
    core_ready
  fi
  phase image-layer
fi

now=${EPOCHREALTIME/./}
echo "SHIP_OK release=$ID mode=$MODE current=$(readlink -f "$R/opt/rosy/current") robot=$(($((now - T0)) / 1000))ms"
