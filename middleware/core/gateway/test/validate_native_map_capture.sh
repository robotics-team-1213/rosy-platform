#!/usr/bin/env bash
# Actual generated response types and serialization on approved remote_sim only.
set -euo pipefail
: "${OUT:?remote_sim must supply OUT}"
evidence="$OUT/native-map-capture"
mkdir -p "$evidence"
preserve() {
  rc=$?
  trap - EXIT
  printf '%s\n' "$rc" > "$evidence/exit-code.txt"
  exit "$rc"
}
trap preserve EXIT
git rev-parse HEAD > "$evidence/source-sha.txt"
bash contracts/ros_idl/test/validate_map_adoption.sh
set +u
source "$OUT/install/setup.bash"
set -u
# Domain converter comes from this shipped source, generated ROS types from OUT.
PYTHONPATH="$PWD/middleware/core/services${PYTHONPATH:+:$PYTHONPATH}" \
  python3 middleware/core/gateway/test/check_native_map_capture.py \
  2>&1 | tee "$evidence/python-test.txt"
