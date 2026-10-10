#!/bin/bash
# D-563 3 on the model PC: (robot session dir, ceiling recording dir) -> review-ready
# map-projected drivable dataset + quick overlays + review sheets (finalize needs verdicts).
#   map_labels_run.sh SESSION_DIR CEILING_DIR OUT_DIR ROBOT_DEVICE MARKER_ID [derive args...]
# env: PYTHON (default python3), HEADING_EDGE (default 0,1; the sticker's forward edge),
#      CALIBRATION_ROOT (robot calibration store), AVAIL_GB (script printing free GB incl. ARC)
#      + NEED_GB (default 8) to wait for memory first (D-566 3), TOOL_COMMIT (snapshot without .git).
# Each step runs under systemd-run --user --scope -p MemoryMax=6G when systemd-run exists.
set -euo pipefail
[ $# -ge 5 ] || { sed -n 2,8p "$0"; exit 2; }
session=$1 ceiling=$2 out=$3 robot=$4 marker=$5; shift 5
here=$(cd "$(dirname "$0")" && pwd); repo=$(cd "$here/../.." && pwd)
ds=$repo/learning/training/perception/dataset; py=${PYTHON:-python3}
commit=${TOOL_COMMIT:-$(git -C "$repo" rev-parse HEAD 2>/dev/null || cat "$repo/COMMIT")}
run() { if command -v systemd-run >/dev/null; then systemd-run --user --scope -p MemoryMax=6G --quiet "$@"; else "$@"; fi; }
if [ -n "${AVAIL_GB:-}" ]; then
  until [ "$($py "$AVAIL_GB")" -ge "${NEED_GB:-8}" ]; do echo "waiting for memory"; sleep 30; done
fi
run "$py" "$here/ceiling_poses.py" --rec "$ceiling" --marker-id "$marker" --heading-edge "${HEADING_EDGE:-0,1}"
run "$py" "$ds/map_projected_drivable.py" derive --session "$session" --ceiling "$ceiling" --robot "$robot" \
  ${CALIBRATION_ROOT:+--calibration-root "$CALIBRATION_ROOT"} --out "$out" --clock-offset-s auto \
  --session-name "$(basename "$session")" --tool-commit "$commit" "$@"
run "$py" "$ds/map_projected_drivable.py" overlays --out "$out" --dest "$out.overlays.png"
frames=$("$py" -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["frames"]))' "$out/manifest.json")
# D-554: at least 20 canaries and 8 % of frames.
canaries=$("$py" -c "import sys; n=int(sys.argv[1]); print(max(0.1, 22 / max(n, 1)))" "$frames")
run "$py" "$ds/lane_derived_drivable.py" sheets --out "$out" --dest "$out.sheets" --key "$out.canary-key.json" \
  --canaries "$canaries"
echo "review: $out.sheets (key $out.canary-key.json, keep it away from the reviewer);"
echo "then lane_derived_drivable.py import-verdicts ... and finalize --out $out"
