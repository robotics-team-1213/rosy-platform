#!/bin/bash
# Restore 0-byte CPython and ROS Python sources on Hub linux/arm64
# ros:jazzy-ros-base (2026-09-16). No-op when no 0-byte .py files exist.
# Set ROSY_HOLLOW_ROOT to prefix search paths (tests). ROSY_HOLLOW_DRY_RUN=1
# prints hollow paths and does not apt-get.
set -eo pipefail

ROOT="${ROSY_HOLLOW_ROOT:-}"
DRY="${ROSY_HOLLOW_DRY_RUN:-0}"

list_hollow_py() {
  local d
  for d in \
    "${ROOT}/usr/lib/python3.12" \
    "${ROOT}/usr/share/python3" \
    "${ROOT}/usr/lib/python3/dist-packages" \
    "${ROOT}/opt/ros"
  do
    if [ -d "$d" ]; then
      find "$d" -name '*.py' -size 0 2>/dev/null || true
    fi
  done
}

mapfile -t hollow < <(list_hollow_py)
if [ "${#hollow[@]}" -eq 0 ]; then
  echo "restore-hollow-python: skip (no 0-byte .py files)" >&2
  exit 0
fi

if [ "$DRY" = 1 ]; then
  printf '%s\n' "${hollow[@]}"
  echo "restore-hollow-python: dry-run would reinstall owners of ${#hollow[@]} files" >&2
  exit 0
fi

has_stdlib=0
has_debpython=0
for f in "${hollow[@]}"; do
  case "$f" in
    */usr/lib/python3.12/*) has_stdlib=1 ;;
    */usr/share/python3/*) has_debpython=1 ;;
  esac
done

if [ "$has_stdlib" = 1 ]; then
  apt-get install --reinstall -y --no-install-recommends \
    libpython3.12-minimal \
    libpython3.12-stdlib
fi
if [ "$has_debpython" = 1 ]; then
  apt-get install --reinstall -y --no-install-recommends \
    python3-minimal \
    python3
fi

declare -A seen=(
  [libpython3.12-minimal]=1
  [libpython3.12-stdlib]=1
  [python3-minimal]=1
  [python3]=1
)
rest=()
for f in "${hollow[@]}"; do
  while IFS= read -r line; do
    pkg="${line%%:*}"
    pkg="${pkg%%,*}"
    pkg="${pkg// /}"
    [ -n "$pkg" ] || continue
    [ -z "${seen[$pkg]:-}" ] || continue
    seen[$pkg]=1
    rest+=("$pkg")
  done < <(dpkg-query -S "$f" 2>/dev/null || true)
done

if [ "${#rest[@]}" -gt 0 ]; then
  apt-get install --reinstall -y --no-install-recommends "${rest[@]}"
fi
