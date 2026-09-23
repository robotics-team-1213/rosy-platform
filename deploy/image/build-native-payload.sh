#!/usr/bin/env bash
# Build the complete ROSY workspace into an offline native ROS 2 Jazzy payload.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE=""
RELEASE_ROOT=""
SOURCE_REVISION=""
RELEASE_ID=""
ROS_DISTRO="jazzy"
LOCK="$SCRIPT_DIR/inputs.lock.yaml"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --workspace) WORKSPACE="${2:-}"; shift 2 ;;
        --release-root) RELEASE_ROOT="${2:-}"; shift 2 ;;
        --source-revision) SOURCE_REVISION="${2:-}"; shift 2 ;;
        --release-id) RELEASE_ID="${2:-}"; shift 2 ;;
        --ros-distro) ROS_DISTRO="${2:-}"; shift 2 ;;
        --lock) LOCK="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

fail() { echo "FAIL: $*" >&2; exit 1; }

[[ "$(uname -m)" == "aarch64" ]] \
    || fail "native ROSY payloads must be built on aarch64"
[[ "$ROS_DISTRO" == "jazzy" ]] || fail "product ROS distribution must be jazzy"
[[ -d "$WORKSPACE/src" ]] || fail "workspace has no src directory: $WORKSPACE"
[[ -n "$RELEASE_ROOT" ]] || fail "--release-root is required"
[[ "$SOURCE_REVISION" =~ ^[0-9a-f]{40}$ ]] \
    || fail "--source-revision must be a full lowercase Git commit"
[[ "$RELEASE_ID" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$ ]] \
    || fail "--release-id must be YYYY.MM.DD-NNN"
[[ -f "/opt/ros/jazzy/setup.bash" ]] || fail "native ROS 2 Jazzy is not installed"
[[ -f "$LOCK" ]] || fail "input lock is missing: $LOCK"

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

# D-192 US-005: the RPLIDAR C1 driver the bringup launch includes. Not in the
# repository and not an apt package: install-pinky-hardware-deps.sh fetched
# the locked archive. This builder stays offline: it re-checks that archive
# against the lock, extracts it into a fresh directory and builds exactly
# that one package (review: a stamp next to an unpacked tree proved nothing).
VENDOR_ARCHIVES="${ROSY_VENDOR_ARCHIVES:-/usr/local/src/rosy-vendor}"
VENDOR_WORK="$(mktemp -d)"
trap 'rm -rf -- "$VENDOR_WORK"' EXIT
SLLIDAR_SRC="$("$SCRIPT_DIR/prepare-vendor-source.sh" --lock "$LOCK" \
    --archive-dir "$VENDOR_ARCHIVES" --dest "$VENDOR_WORK")" \
    || fail "sllidar_ros2 source did not verify against inputs.lock.yaml"
[[ "$SLLIDAR_SRC" == "$VENDOR_WORK/sllidar_ros2" ]] || fail "unexpected sllidar_ros2 path: $SLLIDAR_SRC"

ACTUAL_REVISION="$(git -C "$WORKSPACE" rev-parse HEAD)"
[[ "$ACTUAL_REVISION" == "$SOURCE_REVISION" ]] \
    || fail "workspace revision $ACTUAL_REVISION does not match $SOURCE_REVISION"
git -C "$WORKSPACE" diff --quiet || fail "workspace has unstaged changes"
git -C "$WORKSPACE" diff --cached --quiet || fail "workspace has staged changes"

mkdir -p "$RELEASE_ROOT"
RELEASE_ROOT="$(cd "$RELEASE_ROOT" && pwd -P)"
INSTALL_ROOT="$RELEASE_ROOT/install"
INVENTORY="$RELEASE_ROOT/rosy-packages.txt"
DEB_INVENTORY="$RELEASE_ROOT/deb-packages.txt"
NATIVE_RUNTIME_SOURCE="$WORKSPACE/deploy/robot/native"
FIRST_BOOT_SOURCE="$WORKSPACE/deploy/image/first-boot"
SD_TOOLS_SOURCE="$WORKSPACE/deploy/sd"
ROBOT_CONFIG_SOURCE="$WORKSPACE/deploy/robot/config"
CYCLONEDDS_SOURCE="$WORKSPACE/src/hardware/bringup/config/cyclonedds_localhost.xml"
UDEV_RULE_SOURCE="$WORKSPACE/deploy/robot/udev/99-rosy-motor.rules"
DISPLAY_UDEV_RULE_SOURCE="$WORKSPACE/deploy/robot/udev/99-rosy-display.rules"
RELEASE_PUBLIC_KEY="$WORKSPACE/deploy/release/public-keys/rosy-release-2026-01.pem"
[[ -d "$NATIVE_RUNTIME_SOURCE" ]] \
    || fail "native runtime support is missing: deploy/robot/native"
[[ -d "$FIRST_BOOT_SOURCE" ]] \
    || fail "Ubuntu first-boot support is missing: deploy/image/first-boot"
[[ -d "$SD_TOOLS_SOURCE" ]] \
    || fail "SD personalization support is missing: deploy/sd"
[[ -f "$UDEV_RULE_SOURCE" ]] \
    || fail "motor udev rule is missing: deploy/robot/udev/99-rosy-motor.rules"
[[ -f "$DISPLAY_UDEV_RULE_SOURCE" ]] \
    || fail "display udev rule is missing: deploy/robot/udev/99-rosy-display.rules"
[[ ! -e "$RELEASE_ROOT/deploy/robot/native" ]] \
    || fail "release root already contains native runtime support"
[[ -f "$RELEASE_PUBLIC_KEY" ]] \
    || fail "selected release public key is missing"

# shellcheck disable=SC1091
set +u
source /opt/ros/jazzy/setup.bash
set -u

rosdep install --from-paths "$WORKSPACE/src" "$SLLIDAR_SRC" --ignore-src -r -y \
    --rosdistro "$ROS_DISTRO"

(
    cd "$WORKSPACE"
    colcon build --base-paths src "$SLLIDAR_SRC" --merge-install \
        --install-base "$INSTALL_ROOT" --event-handlers console_direct+
    colcon list --base-paths src "$SLLIDAR_SRC" --names-only | LC_ALL=C sort -u > "$INVENTORY.tmp"
)
mv -f -- "$INVENTORY.tmp" "$INVENTORY"
dpkg-query -W -f='${Package}\t${Version}\n' | LC_ALL=C sort > "$DEB_INVENTORY.tmp"
mv -f -- "$DEB_INVENTORY.tmp" "$DEB_INVENTORY"
printf '%s\n' "$SOURCE_REVISION" > "$RELEASE_ROOT/source-revision.txt"
# D-189: the CORE Python runtime this release was built and tested against.
# native_release.py refuses to activate it on an image with a different one.
sha256sum "$SCRIPT_DIR/device-python-requirements.txt" | awk '{print $1}' \
    > "$RELEASE_ROOT/python-runtime.sha256"
printf '%s\n' "$RELEASE_ID" > "$INSTALL_ROOT/.rosy-release"
cp "$SCRIPT_DIR/required-ros-packages.txt" "$RELEASE_ROOT/required-ros-packages.txt"
mkdir -p "$RELEASE_ROOT/deploy/robot"
"$NATIVE_RUNTIME_SOURCE/install-native-runtime.sh" "$RELEASE_ROOT/deploy/robot/native"

# Stage the immutable image-owned bootstrap tools separately from the
# switchable release.  Recovery cannot live below /opt/rosy/current because
# it must run precisely when that link was interrupted.
OVERLAY="$RELEASE_ROOT/image-overlay"
mkdir -p "$OVERLAY/opt/rosy" "$OVERLAY/opt/rosy/deploy" \
    "$OVERLAY/etc/systemd/system" "$OVERLAY/etc/udev/rules.d" \
    "$OVERLAY/etc/rosy/trusted-release-keys"
"$NATIVE_RUNTIME_SOURCE/install-native-runtime.sh" "$OVERLAY/opt/rosy/native-runtime"
cp -a "$FIRST_BOOT_SOURCE" "$OVERLAY/opt/rosy/first-boot"
cp -a "$SD_TOOLS_SOURCE" "$OVERLAY/opt/rosy/deploy/sd"
# The native units address the motor bus as /dev/rosy-motor; the image must
# carry the rule so a freshly flashed device has the alias on first boot.
cp "$UDEV_RULE_SOURCE" "$OVERLAY/etc/udev/rules.d/"
# D-190: the boot display's LCD and GPIO chip groups.
cp "$DISPLAY_UDEV_RULE_SOURCE" "$OVERLAY/etc/udev/rules.d/"
cp "$FIRST_BOOT_SOURCE/rosy-first-boot.service" "$OVERLAY/etc/systemd/system/"
cp "$NATIVE_RUNTIME_SOURCE/rosy-release-recover.service" "$OVERLAY/etc/systemd/system/"
cp "$NATIVE_RUNTIME_SOURCE/rosy-sd-provision.service" "$OVERLAY/etc/systemd/system/"
cp "$NATIVE_RUNTIME_SOURCE/rosy-core.service" "$OVERLAY/etc/systemd/system/"
cp "$NATIVE_RUNTIME_SOURCE/rosy-runtime.target" "$OVERLAY/etc/systemd/system/"
# D-192 US-005: the hardware runtimes ship installed but not enabled; the
# default target stays CORE-only (D-161). An operator starts one by hand.
cp "$NATIVE_RUNTIME_SOURCE/rosy-io.service" "$OVERLAY/etc/systemd/system/"
cp "$NATIVE_RUNTIME_SOURCE/rosy-navigation.service" "$OVERLAY/etc/systemd/system/"
cp "$NATIVE_RUNTIME_SOURCE/rosy-boot-status.service" "$OVERLAY/etc/systemd/system/"
cp "$NATIVE_RUNTIME_SOURCE/rosy-boot-status.timer" "$OVERLAY/etc/systemd/system/"
# D-192 US-003: one more run right after the runtime target settles.
cp "$NATIVE_RUNTIME_SOURCE/rosy-boot-status-ready.service" "$OVERLAY/etc/systemd/system/"
# D-190: the LCD and buzzer, unprivileged and outside CORE, enabled by the image.
cp "$NATIVE_RUNTIME_SOURCE/rosy-boot-display.service" "$OVERLAY/etc/systemd/system/"
# D-176: boot settings file and fallback AP, both root and outside CORE.
cp "$NATIVE_RUNTIME_SOURCE/rosy-config.service" "$OVERLAY/etc/systemd/system/"
cp "$NATIVE_RUNTIME_SOURCE/rosy-network.service" "$OVERLAY/etc/systemd/system/"
cp "$NATIVE_RUNTIME_SOURCE/defaults.yaml" "$OVERLAY/etc/rosy/defaults.yaml"
mkdir -p "$OVERLAY/etc/systemd/journald.conf.d"
cp "$NATIVE_RUNTIME_SOURCE/journald-60-rosy.conf" "$OVERLAY/etc/systemd/journald.conf.d/60-rosy.conf"
mkdir -p "$OVERLAY/etc/tmpfiles.d"
cp "$NATIVE_RUNTIME_SOURCE/tmpfiles-rosy-logs.conf" "$OVERLAY/etc/tmpfiles.d/rosy-logs.conf"
# D-189 D4: root-owned /var/lib/rosy and the navigation-owned maps directory.
cp "$NATIVE_RUNTIME_SOURCE/tmpfiles-rosy-state.conf" "$OVERLAY/etc/tmpfiles.d/rosy-state.conf"
cp "$NATIVE_RUNTIME_SOURCE/rosy-runtime.env" "$OVERLAY/etc/rosy/runtime.env.template"
cp "$ROBOT_CONFIG_SOURCE/motion_profiles.yaml" "$OVERLAY/etc/rosy/motion_profiles.yaml"
cp "$CYCLONEDDS_SOURCE" "$OVERLAY/etc/rosy/cyclonedds.xml"
cp "$RELEASE_PUBLIC_KEY" \
    "$OVERLAY/etc/rosy/trusted-release-keys/rosy-release-2026-01.pem"

# shellcheck disable=SC1090
set +u
source "$INSTALL_ROOT/setup.bash"
set -u
"$SCRIPT_DIR/verify-package-inventory.sh" \
    --required "$SCRIPT_DIR/required-ros-packages.txt" \
    --inventory "$INVENTORY" \
    --install-root "$INSTALL_ROOT"
"$SCRIPT_DIR/verify-package-inventory.sh" \
    --required "$SCRIPT_DIR/vendor-ros-packages.txt" \
    --inventory "$INVENTORY" \
    --install-root "$INSTALL_ROOT"

echo "PAYLOAD_BUILT $RELEASE_ROOT"
