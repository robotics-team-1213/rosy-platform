#!/usr/bin/env bash
# Genuine installed plugin + Costmap2DROS lifecycle and native application tests.
set -euo pipefail
: "${OUT:?remote_sim must supply OUT}"
evidence="$OUT/native-map-static"
mkdir -p "$evidence"
preserve() {
  rc=$?
  trap - EXIT
  set +e
  for path in "$OUT/build/navigation" "$OUT/install/navigation"; do
    if [[ -d "$path" ]]; then
      find "$path" -type f \( -name '*.xml' -o -name '*.log' -o -name 'CMakeCache.txt' \
        -o -name 'compile_commands.json' -o -name 'link.txt' -o -name 'build_id.hpp' \
        -o -name 'sdk-pins.txt' -o -name 'build-fingerprint.txt' \) \
        -exec cp --parents '{}' "$evidence" \;
    fi
  done
  printf '%s\n' "$rc" > "$evidence/exit-code.txt"
  exit "$rc"
}
trap preserve EXIT
git rev-parse HEAD > "$evidence/source-sha.txt"
# Full same-SHA interfaces/native build + grid/AMCL/installed binary verification.
bash middleware/drive/planning/nav2/test/validate_native_amcl.sh
set +u
source "$OUT/install/setup.bash"
set -u
colcon --log-base "$OUT/static-colcon-log" test --build-base "$OUT/build" \
  --install-base "$OUT/install" --packages-select navigation \
  --ctest-args -R '^native_map_static$' --output-on-failure 2>&1 | tee "$evidence/test.txt"
colcon test-result --test-result-base "$OUT/build/navigation/test_results" --verbose \
  2>&1 | tee "$evidence/test-result.txt"
python3 - "$OUT/build/navigation/test_results" <<'PY'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
paths = list(Path(sys.argv[1]).rglob('native_map_static.gtest.xml'))
assert len(paths) == 1, paths
root = ET.parse(paths[0]).getroot()
assert int(root.attrib['tests']) == 14, root.attrib
for name in ('failures', 'errors', 'disabled'):
    assert int(root.attrib.get(name, 0)) == 0, root.attrib
assert not root.findall('.//skipped')
print('native_map_static: 14 actual cases, no failures/errors/skips')
PY
