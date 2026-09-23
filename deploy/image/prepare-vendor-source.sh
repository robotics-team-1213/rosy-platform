#!/usr/bin/env bash
# Extract one locked third-party ROS source archive for the payload build (D-192).
#
#   prepare-vendor-source.sh --lock LOCK --archive-dir DIR --dest EMPTY_DIR
#
# The archive was downloaded and checked by install-pinky-hardware-deps.sh; it
# is checked again here against the lock, extracted into DEST (which must be
# empty, normally a fresh mktemp -d) and accepted only if it holds exactly one
# ROS package, sllidar_ros2 at its root. Prints the package directory. Offline.
set -euo pipefail

LOCK=""
ARCHIVE_DIR=""
DEST=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --lock) LOCK="${2:-}"; shift 2 ;;
        --archive-dir) ARCHIVE_DIR="${2:-}"; shift 2 ;;
        --dest) DEST="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

fail() { echo "FAIL VENDOR_SOURCE $*" >&2; exit 1; }
[[ -f "$LOCK" ]] || fail "input lock is missing: $LOCK"
[[ -d "$ARCHIVE_DIR" ]] || fail "archive directory is missing: $ARCHIVE_DIR"
[[ -d "$DEST" ]] || fail "destination is missing: $DEST"
[[ -z "$(ls -A -- "$DEST")" ]] || fail "destination is not empty: $DEST"

lock_value() {
    local section="$1" wanted="$2"
    awk -v section="$section" -v wanted="$wanted" '
        $0 ~ "^" section ":[[:space:]]*$" { inside=1; next }
        inside && /^[^[:space:]]/ { exit }
        inside {
            key=$1; sub(/:$/, "", key)
            if (key == wanted) { $1=""; sub(/^[[:space:]]+/, ""); sub(/\r$/, ""); print; exit }
        }
    ' "$LOCK"
}

COMMIT="$(lock_value hardware_dependencies sllidar_ros2_commit)"
SHA256="$(lock_value hardware_dependencies sllidar_ros2_sha256)"
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "sllidar_ros2_commit is invalid"
[[ "$SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "sllidar_ros2_sha256 is invalid"
ARCHIVE="$ARCHIVE_DIR/sllidar_ros2-$COMMIT.tar.gz"
[[ -f "$ARCHIVE" ]] || fail "sllidar_ros2 archive is missing; run install-pinky-hardware-deps.sh first"

printf '%s  %s\n' "$SHA256" "$ARCHIVE" | sha256sum --check --strict --quiet \
    || fail "sllidar_ros2 archive is not the one inputs.lock.yaml names"

PACKAGE="$DEST/sllidar_ros2"
mkdir -p "$PACKAGE"
tar -xzf "$ARCHIVE" --strip-components=1 -C "$PACKAGE"

mapfile -t MANIFESTS < <(find "$DEST" -name package.xml -type f | LC_ALL=C sort)
[[ "${#MANIFESTS[@]}" -eq 1 && "${MANIFESTS[0]}" == "$PACKAGE/package.xml" ]] \
    || fail "sllidar_ros2 archive must hold exactly one ROS package at its root, found: ${MANIFESTS[*]:-none}"
grep -q '<name>sllidar_ros2</name>' "$PACKAGE/package.xml" \
    || fail "sllidar_ros2 archive holds another package"

printf '%s\n' "$PACKAGE"
