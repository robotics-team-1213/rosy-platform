#!/usr/bin/env bash
# Preliminary ROS-grid byte/identity tests, on approved remote_sim hosts only.
set -euo pipefail
: "${OUT:?remote_sim must supply OUT}"
evidence="$OUT/native-map-grid"
mkdir -p "$evidence"
preserve() {
  rc=$?
  trap - EXIT
  set +e
  if [[ -d "$OUT/grid-build" ]]; then
    find "$OUT/grid-build" -type f \( -name '*.xml' -o -name '*.log' \
      -o -name 'compile_commands.json' \) -exec cp --parents '{}' "$evidence" \;
  fi
  printf '%s\n' "$rc" > "$evidence/exit-code.txt"
  exit "$rc"
}
trap preserve EXIT
git rev-parse HEAD > "$evidence/source-sha.txt"
nav=middleware/drive/planning/nav2
python3 "$nav/test/native_map_grid/generate_vectors.py" > "$evidence/python-vectors.tsv"
export ROSY_NATIVE_MAP_VECTORS="$evidence/python-vectors.tsv"
cmake -S "$nav/test/native_map_grid" -B "$OUT/grid-build" \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON 2>&1 | tee "$evidence/cmake.txt"
cmake --build "$OUT/grid-build" --parallel 2 2>&1 | tee "$evidence/build.txt"
ctest --test-dir "$OUT/grid-build" -R '^native_map_grid$' \
  --no-tests=error --output-on-failure 2>&1 | tee "$evidence/test.txt"
python3 - "$OUT/grid-build" <<'PY'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
xml = list(Path(sys.argv[1]).rglob('native_map_grid.gtest.xml'))
assert len(xml) == 1, xml
root = ET.parse(xml[0]).getroot()
assert int(root.attrib['tests']) == 7, root.attrib
for name in ('failures', 'errors', 'disabled'):
    assert int(root.attrib.get(name, 0)) == 0, root.attrib
assert not root.findall('.//skipped')
print('native_map_grid: 7 actual gtest cases, no failures/errors/skips')
PY
