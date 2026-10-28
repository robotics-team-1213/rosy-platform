#!/usr/bin/env bash
# Real AMCL producer verification. Existing runner supplies isolated ROS domain.
set -euo pipefail
: "${OUT:?remote_sim must supply OUT}"
evidence="$OUT/native-map-amcl"
mkdir -p "$evidence"
preserve() {
  rc=$?
  trap - EXIT
  set +e
  for path in "$OUT/build/navigation" "$OUT/install/navigation"; do
    if [[ -d "$path" ]]; then
      find "$path" -type f \( -name '*.xml' -o -name '*.log' \
        -o -name 'compile_commands.json' -o -name 'build_id.hpp' \
        -o -name 'sdk-pins.txt' -o -name 'build-fingerprint.txt' -o -name 'link.txt' \
        -o -name 'CMakeCache.txt' \) \
        -exec cp --parents '{}' "$evidence" \;
    fi
  done
  printf '%s\n' "$rc" > "$evidence/exit-code.txt"
  exit "$rc"
}
trap preserve EXIT
git rev-parse HEAD > "$evidence/source-sha.txt"
# Explicit same-SHA interfaces generation and proven generated dependencies.
bash contracts/ros_idl/test/validate_map_adoption.sh
set +u
source "$OUT/install/setup.bash"
set -u
nav=middleware/drive/planning/nav2
python3 "$nav/test/native_map_grid/generate_vectors.py" > "$evidence/python-vectors.tsv"
export ROSY_NATIVE_MAP_VECTORS="$evidence/python-vectors.tsv"
colcon --log-base "$OUT/native-colcon-log" build --base-paths "$nav" \
  --build-base "$OUT/build" --install-base "$OUT/install" --packages-select navigation \
  --cmake-args -DROSY_NATIVE_MAP_READBACK=ON -DBUILD_TESTING=ON \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON 2>&1 | tee "$evidence/build.txt"
grep -Fx 'ROSY_NATIVE_MAP_READBACK:BOOL=ON' "$OUT/build/navigation/CMakeCache.txt"
set +u
source "$OUT/install/setup.bash"
set -u
[[ "$(realpath "$(ros2 pkg prefix navigation)")" == "$(realpath "$OUT/install/navigation")" ]]
[[ -x "$OUT/install/navigation/lib/navigation/rosy_verified_amcl" ]]
grep -F "$OUT/install/interfaces/" "$OUT/build/navigation/compile_commands.json"
colcon --log-base "$OUT/native-colcon-test-log" test --build-base "$OUT/build" \
  --install-base "$OUT/install" --packages-select navigation \
  --ctest-args -R '^native_map_(grid|amcl)$' --output-on-failure \
  2>&1 | tee "$evidence/test.txt"
colcon test-result --test-result-base "$OUT/build/navigation/test_results" --verbose \
  2>&1 | tee "$evidence/test-result.txt"
python3 - "$OUT/build/navigation/test_results" <<'PY'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
base = Path(sys.argv[1])
for target, expected in (('grid', 7), ('amcl', 10)):
    paths = list(base.rglob(f'native_map_{target}.gtest.xml'))
    assert len(paths) == 1, (target, paths)
    root = ET.parse(paths[0]).getroot()
    assert int(root.attrib['tests']) == expected, root.attrib
    for name in ('failures', 'errors', 'disabled'):
        assert int(root.attrib.get(name, 0)) == 0, root.attrib
    assert not root.findall('.//skipped')
    print(f'native_map_{target}: {expected} actual cases, no failures/errors/skips')
PY
python3 "$nav/test/check_installed_amcl.py" "$OUT/install/navigation" \
  2>&1 | tee "$evidence/installed-binary.txt"
