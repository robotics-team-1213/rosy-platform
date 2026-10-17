#!/usr/bin/env bash
# Same-SHA generated service and actual DDS, approved remote_sim only.
set -euo pipefail
: "${OUT:?remote_sim must supply OUT}"
evidence="$OUT/native-map-clients"
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
PYTHONPATH="$PWD/middleware/core/gateway:$PWD/middleware/core/services${PYTHONPATH:+:$PYTHONPATH}" \
  python3 middleware/core/gateway/test/check_native_map_clients.py \
  2>&1 | tee "$evidence/python-test.txt"
