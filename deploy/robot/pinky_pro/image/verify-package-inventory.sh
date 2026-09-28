#!/usr/bin/env bash
# Verify that the offline ROSY payload contains and resolves every required package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIRED="$SCRIPT_DIR/required-ros-packages.txt"
INVENTORY=""
INSTALL_ROOT=""
ROS2="${ROSY_ROS2:-ros2}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --required) REQUIRED="${2:-}"; shift 2 ;;
        --inventory) INVENTORY="${2:-}"; shift 2 ;;
        --install-root) INSTALL_ROOT="${2:-}"; shift 2 ;;
        --ros2) ROS2="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

fail() { echo "FAIL: $*" >&2; exit 1; }

[[ -f "$REQUIRED" ]] || fail "missing required package list: $REQUIRED"
[[ -n "$INVENTORY" && -f "$INVENTORY" ]] || fail "missing package inventory"
[[ -n "$INSTALL_ROOT" && -d "$INSTALL_ROOT" ]] || fail "missing install root"
[[ -x "$ROS2" ]] || command -v "$ROS2" >/dev/null 2>&1 \
    || fail "ros2 command is unavailable: $ROS2"

INSTALL_ROOT="$(cd "$INSTALL_ROOT" && pwd -P)"
NORMALIZED_INVENTORY="$(mktemp)"
trap 'rm -f -- "$NORMALIZED_INVENTORY"' EXIT
tr -d '\r' < "$INVENTORY" | sed '/^[[:space:]]*$/d' > "$NORMALIZED_INVENTORY"
LC_ALL=C sort -c -u "$NORMALIZED_INVENTORY" \
    || fail "package inventory must be sorted and unique"

mapfile -t REQUIRED_PACKAGES < <(
    tr -d '\r' < "$REQUIRED" \
        | sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d'
)
(( ${#REQUIRED_PACKAGES[@]} > 0 )) || fail "required package list is empty"

for package in "${REQUIRED_PACKAGES[@]}"; do
    grep -Fxq -- "$package" "$NORMALIZED_INVENTORY" \
        || fail "missing required package from inventory: $package"
done

for package in "${REQUIRED_PACKAGES[@]}"; do
    prefix="$($ROS2 pkg prefix "$package" 2>/dev/null)" \
        || fail "ros2 pkg prefix failed for required package: $package"
    prefix="${prefix%$'\r'}"
    case "$prefix" in
        "$INSTALL_ROOT"|"$INSTALL_ROOT"/*) ;;
        *) fail "required package resolves outside release prefix: $package -> $prefix" ;;
    esac
done

echo "INVENTORY_VERIFIED ${#REQUIRED_PACKAGES[@]} $INSTALL_ROOT"
