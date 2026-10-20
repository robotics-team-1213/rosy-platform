#!/usr/bin/env bash
# Same-SHA generated-interface check on an approved remote_sim host only.
set -euo pipefail
: "${OUT:?remote_sim must supply OUT}"
src="$PWD"
evidence="$OUT/native-map-wire"
mkdir -p "$evidence"

preserve() {
  rc=$?
  trap - EXIT
  set +e
  # The runner removes build/install afterwards. Preserve failure evidence too.
  for path in "$OUT/build/interfaces" "$OUT/wire-build/Testing"; do
    if [[ -d "$path" ]]; then
      find "$path" -type f \( -name '*.xml' -o -name '*Config.cmake' \
        -o -name '*.log' -o -name 'compile_commands.json' \) \
        -exec cp --parents '{}' "$evidence" \;
    fi
  done
  printf '%s\n' "$rc" > "$evidence/exit-code.txt"
  exit "$rc"
}
trap preserve EXIT
git rev-parse HEAD > "$evidence/source-sha.txt"
sha256sum contracts/ros_idl/srv/MapAdoption.srv > "$evidence/source-idl.sha256"
colcon build --base-paths contracts/ros_idl --build-base "$OUT/build" \
  --install-base "$OUT/install" --packages-select interfaces \
  --cmake-args -DBUILD_TESTING=ON 2>&1 | tee "$evidence/build.txt"
set +u
source "$OUT/install/setup.bash"
set -u
prefix="$(ros2 pkg prefix interfaces)"
[[ "$(realpath "$prefix")" == "$(realpath "$OUT/install/interfaces")" ]]
printf '%s\n' "$prefix" > "$evidence/interfaces-prefix.txt"
cmp contracts/ros_idl/srv/MapAdoption.srv "$prefix/share/interfaces/srv/MapAdoption.srv"
sha256sum "$prefix/share/interfaces/srv/MapAdoption.srv" \
  "$prefix/include/interfaces/interfaces/srv/map_adoption.hpp" \
  > "$evidence/generated.sha256"
python3 -c 'import interfaces.srv._map_adoption as m; print(m.__file__)' \
  | tee "$evidence/python-path.txt"
grep -F "$OUT/install/interfaces/" "$evidence/python-path.txt"
python3 contracts/ros_idl/test/map_adoption_wire/check_python.py \
  2>&1 | tee "$evidence/python-test.txt"
cmake -S "$src/contracts/ros_idl/test/map_adoption_wire" -B "$OUT/wire-build" \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON 2>&1 | tee "$evidence/cmake.txt"
cmake --build "$OUT/wire-build" --parallel 2 2>&1 | tee "$evidence/cpp-build.txt"
cp "$OUT/wire-build/compile_commands.json" "$evidence/compile_commands.json"
grep -F "$OUT/install/interfaces/" "$evidence/compile_commands.json"
ctest --test-dir "$OUT/wire-build" -R '^native_map_wire_cpp$' \
  --no-tests=error --output-on-failure --output-junit "$evidence/cpp-test.xml" \
  2>&1 | tee "$evidence/cpp-test.txt"
