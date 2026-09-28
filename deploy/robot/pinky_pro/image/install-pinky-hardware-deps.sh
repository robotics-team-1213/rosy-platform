#!/usr/bin/env bash
# Install checksum-pinned Pinky Pro native build dependencies on ARM64.
set -euo pipefail

LOCK=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --lock) LOCK="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

fail() { echo "FAIL: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail "hardware dependency installation requires root"
[[ "$(uname -m)" == "aarch64" ]] || fail "Pinky hardware dependencies require native aarch64"
[[ -f "$LOCK" ]] || fail "input lock is missing"

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

WIRINGPI_URL="$(lock_value hardware_dependencies wiringpi_url)"
WIRINGPI_SHA256="$(lock_value hardware_dependencies wiringpi_sha256)"
WS281X_URL="$(lock_value hardware_dependencies rpi_ws281x_url)"
WS281X_SHA256="$(lock_value hardware_dependencies rpi_ws281x_sha256)"
[[ "$WIRINGPI_URL" == https://* ]] || fail "wiringpi_url must use HTTPS"
[[ "$WS281X_URL" == https://* ]] || fail "rpi_ws281x_url must use HTTPS"
[[ "$WIRINGPI_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "wiringpi_sha256 is invalid"
[[ "$WS281X_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "rpi_ws281x_sha256 is invalid"
SLLIDAR_COMMIT="$(lock_value hardware_dependencies sllidar_ros2_commit)"
SLLIDAR_URL="$(lock_value hardware_dependencies sllidar_ros2_url)"
SLLIDAR_SHA256="$(lock_value hardware_dependencies sllidar_ros2_sha256)"
[[ "$SLLIDAR_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "sllidar_ros2_commit is invalid"
[[ "$SLLIDAR_URL" == https://* && "$SLLIDAR_URL" == *"/$SLLIDAR_COMMIT" ]] \
    || fail "sllidar_ros2_url must use HTTPS and name the locked commit"
[[ "$SLLIDAR_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "sllidar_ros2_sha256 is invalid"
VENDOR_ARCHIVES="${ROSY_VENDOR_ARCHIVES:-/usr/local/src/rosy-vendor}"
# D-247: the pinned rpi_ws281x has no Pi 5 rev 1.1 board ids (0xd04171 on
# rosy_18), so lamp_control, which links it statically, would fail ws2811_init.
WS281X_PATCH="$(dirname "$0")/$(lock_value hardware_dependencies rpi_ws281x_pi5_patch)"
WS281X_PATCH_SHA256="$(lock_value hardware_dependencies rpi_ws281x_pi5_patch_sha256)"
[[ -f "$WS281X_PATCH" ]] || fail "rpi_ws281x Pi 5 patch is missing: $WS281X_PATCH"
[[ "$WS281X_PATCH_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "rpi_ws281x_pi5_patch_sha256 is invalid"
[[ "$(sha256sum "$WS281X_PATCH" | awk '{print $1}')" == "$WS281X_PATCH_SHA256" ]] \
    || fail "rpi_ws281x Pi 5 patch does not match inputs.lock.yaml"

for command in apt-get curl sha256sum dpkg tar cmake patch; do
    command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

WORK="$(mktemp -d)"
cleanup() { rm -rf -- "$WORK"; }
trap cleanup EXIT

WIRINGPI_DEB="$WORK/wiringpi-arm64.deb"
WS281X_ARCHIVE="$WORK/rpi_ws281x.tar.gz"
curl --fail --location --proto '=https' --proto-redir '=https' --retry 3 \
    --output "$WIRINGPI_DEB" "$WIRINGPI_URL"
printf '%s  %s\n' "$WIRINGPI_SHA256" "$WIRINGPI_DEB" | sha256sum --check --strict
dpkg -i "$WIRINGPI_DEB"

curl --fail --location --proto '=https' --proto-redir '=https' --retry 3 \
    --output "$WS281X_ARCHIVE" "$WS281X_URL"
printf '%s  %s\n' "$WS281X_SHA256" "$WS281X_ARCHIVE" | sha256sum --check --strict
mkdir "$WORK/source"
tar -xzf "$WS281X_ARCHIVE" --strip-components=1 -C "$WORK/source"
patch --directory="$WORK/source" --strip=1 --forward --batch < "$WS281X_PATCH" \
    || fail "rpi_ws281x Pi 5 patch does not apply to the locked archive"
grep -q '0xd04171' "$WORK/source/rpihw.c" || fail "rpi_ws281x still lacks the Pi 5 rev 1.1 board id"
cmake -S "$WORK/source" -B "$WORK/build" -DBUILD_SHARED=OFF -DBUILD_TEST=OFF
cmake --build "$WORK/build" --parallel
cmake --install "$WORK/build"

# D-192: the RPLIDAR C1 driver archive for build-native-payload.sh, kept as
# the archive. The payload builder checks it against the lock again and
# extracts it itself (prepare-vendor-source.sh); nothing here is trusted later.
SLLIDAR_ARCHIVE="$WORK/sllidar_ros2.tar.gz"
curl --fail --location --proto '=https' --proto-redir '=https' --retry 3 \
    --output "$SLLIDAR_ARCHIVE" "$SLLIDAR_URL"
printf '%s  %s\n' "$SLLIDAR_SHA256" "$SLLIDAR_ARCHIVE" | sha256sum --check --strict
install -d -m 0755 "$VENDOR_ARCHIVES"
install -m 0644 "$SLLIDAR_ARCHIVE" "$VENDOR_ARCHIVES/sllidar_ros2-$SLLIDAR_COMMIT.tar.gz"

echo "PINKY_HARDWARE_BUILD_DEPS_INSTALLED"
