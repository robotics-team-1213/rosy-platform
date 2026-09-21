#!/usr/bin/env bash
# Install ROS 2 Jazzy and the native ROSY payload into a mounted Ubuntu Pi image.
set -euo pipefail

PAYLOAD=""
SOURCE_TREE=""
LOCK=""
RELEASE_ID=""
SOURCE_REVISION=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --payload) PAYLOAD="${2:-}"; shift 2 ;;
        --source-tree) SOURCE_TREE="${2:-}"; shift 2 ;;
        --lock) LOCK="${2:-}"; shift 2 ;;
        --release-id) RELEASE_ID="${2:-}"; shift 2 ;;
        --source-revision) SOURCE_REVISION="${2:-}"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

fail() { echo "FAIL: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail "rootfs customization requires root"
[[ "$(uname -m)" == "aarch64" ]] || fail "rootfs customization requires native arm64"
[[ -n "${ROSY_IMAGE_ROOT:-}" && -d "$ROSY_IMAGE_ROOT" ]] || fail "ROSY_IMAGE_ROOT is not mounted"
[[ -n "${ROSY_IMAGE_BOOT:-}" && -d "$ROSY_IMAGE_BOOT" ]] || fail "ROSY_IMAGE_BOOT is not mounted"
[[ -d "$PAYLOAD/install" && -d "$PAYLOAD/image-overlay" ]] || fail "native payload is incomplete"
[[ -d "$SOURCE_TREE" ]] || fail "ROSY source tree is missing"
[[ -f "$LOCK" ]] || fail "input lock is missing"
[[ "$RELEASE_ID" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$ ]] || fail "release id is invalid"
[[ "$SOURCE_REVISION" =~ ^[0-9a-f]{40}$ ]] || fail "source revision is invalid"

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

ROS_SOURCE_URL="$(lock_value ros apt_source_url)"
ROS_SOURCE_SHA="$(lock_value ros apt_source_sha256)"
WIRINGPI_URL="$(lock_value hardware_dependencies wiringpi_url)"
WIRINGPI_SHA="$(lock_value hardware_dependencies wiringpi_sha256)"
[[ "$ROS_SOURCE_URL" == https://* ]] || fail "ROS apt source package URL must use HTTPS"
[[ "$ROS_SOURCE_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "ROS apt source package SHA-256 is invalid"
[[ "$WIRINGPI_URL" == https://* ]] || fail "WiringPi package URL must use HTTPS"
[[ "$WIRINGPI_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "WiringPi package SHA-256 is invalid"

ROOT="$(realpath -e "$ROSY_IMAGE_ROOT")"
RELEASE="$ROOT/opt/rosy/releases/$RELEASE_ID"
[[ ! -e "$RELEASE" ]] || fail "release already exists in image"
for command in curl sha256sum chroot mount umount cp rm mkdir ln systemctl python3; do
    command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

MOUNTS=()
ROS_SOURCE_TMP=""
WIRINGPI_TMP=""
cleanup() {
    local index
    set +e
    for ((index=${#MOUNTS[@]}-1; index>=0; index--)); do
        umount -- "${MOUNTS[$index]}"
    done
    rm -f -- "$ROOT/tmp/ros2-apt-source.deb"
    rm -f -- "$ROOT/tmp/wiringpi-arm64.deb"
    rm -rf -- "$ROOT/tmp/rosy-src"
    [[ -z "$ROS_SOURCE_TMP" ]] || rm -f -- "$ROS_SOURCE_TMP"
    [[ -z "$WIRINGPI_TMP" ]] || rm -f -- "$WIRINGPI_TMP"
}
trap cleanup EXIT

mkdir -p "$ROOT/dev/pts" "$ROOT/proc" "$ROOT/sys" "$ROOT/run" "$ROOT/tmp"
for pair in "/dev:$ROOT/dev" "/dev/pts:$ROOT/dev/pts" "/proc:$ROOT/proc" "/sys:$ROOT/sys" "/run:$ROOT/run"; do
    source_path="${pair%%:*}"
    target_path="${pair#*:}"
    mount --bind "$source_path" "$target_path"
    MOUNTS+=("$target_path")
done

cp --remove-destination /etc/resolv.conf "$ROOT/etc/resolv.conf"
ROS_SOURCE_TMP="$(mktemp)"
curl --fail --location --proto '=https' --proto-redir '=https' --retry 3 \
    --output "$ROS_SOURCE_TMP" "$ROS_SOURCE_URL"
ACTUAL_ROS_SOURCE_SHA="$(sha256sum "$ROS_SOURCE_TMP" | awk '{print $1}')"
[[ "$ACTUAL_ROS_SOURCE_SHA" == "$ROS_SOURCE_SHA" ]] || fail "ROS apt source package checksum mismatch"
cp "$ROS_SOURCE_TMP" "$ROOT/tmp/ros2-apt-source.deb"
WIRINGPI_TMP="$(mktemp)"
curl --fail --location --proto '=https' --proto-redir '=https' --retry 3 \
    --output "$WIRINGPI_TMP" "$WIRINGPI_URL"
ACTUAL_WIRINGPI_SHA="$(sha256sum "$WIRINGPI_TMP" | awk '{print $1}')"
[[ "$ACTUAL_WIRINGPI_SHA" == "$WIRINGPI_SHA" ]] || fail "WiringPi package checksum mismatch"
cp "$WIRINGPI_TMP" "$ROOT/tmp/wiringpi-arm64.deb"

mkdir -p "$ROOT/etc/apt/sources.list.d"
python3 - "$LOCK" "$ROOT/etc/apt/sources.list.d/rosy-ubuntu.list" <<'PY'
from pathlib import Path
import sys

import yaml

lock_path, output_path = map(Path, sys.argv[1:])
lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
sources = lock["os"]["apt_sources"]
if not isinstance(sources, list) or not sources:
    raise SystemExit("locked Ubuntu apt_sources must be a non-empty list")
for source in sources:
    if not isinstance(source, str) or not source.startswith(
        "deb http://ports.ubuntu.com/ubuntu-ports noble"
    ):
        raise SystemExit(f"refusing unexpected Ubuntu apt source: {source!r}")
output_path.write_text("\n".join(sources) + "\n", encoding="utf-8")
PY

chroot "$ROOT" dpkg -i /tmp/ros2-apt-source.deb
chroot "$ROOT" dpkg -i /tmp/wiringpi-arm64.deb
chroot "$ROOT" apt-get update
chroot "$ROOT" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates locales network-manager openssh-server openssl python3 python3-yaml \
    python3-rosdep ros-jazzy-ros-base ros-jazzy-rmw-cyclonedds-cpp

cp -a "$SOURCE_TREE" "$ROOT/tmp/rosy-src"
if [[ ! -f "$ROOT/etc/ros/rosdep/sources.list.d/20-default.list" ]]; then
    chroot "$ROOT" rosdep init
fi
chroot "$ROOT" rosdep update --rosdistro jazzy
chroot "$ROOT" rosdep install --from-paths /tmp/rosy-src --ignore-src -r -y --rosdistro jazzy

chroot "$ROOT" getent group rosy-core >/dev/null 2>&1 || chroot "$ROOT" groupadd --gid 960 rosy-core
chroot "$ROOT" getent passwd rosy-core >/dev/null 2>&1 || \
    chroot "$ROOT" useradd --uid 960 --gid 960 --system --no-create-home --shell /usr/sbin/nologin rosy-core
chroot "$ROOT" getent group rosy-io >/dev/null 2>&1 || chroot "$ROOT" groupadd --gid 961 rosy-io
chroot "$ROOT" getent passwd rosy-io >/dev/null 2>&1 || \
    chroot "$ROOT" useradd --uid 961 --gid 961 --system --no-create-home --shell /usr/sbin/nologin rosy-io

mkdir -p "$RELEASE" "$ROOT/var/lib/rosy/maps" "$ROOT/etc/rosy/trusted-release-keys" \
    "$ROOT/etc/cloud/cloud.cfg.d"
cp -a "$PAYLOAD/." "$RELEASE/"
cp -a "$PAYLOAD/image-overlay/." "$ROOT/"
rm -rf -- "$RELEASE/image-overlay"
printf '%s\n' "$SOURCE_REVISION" > "$RELEASE/source-revision.txt"
chroot "$ROOT" dpkg-query -W '-f=${Package}\t${Version}\n' | LC_ALL=C sort > "$RELEASE/deb-packages.txt"

ln -s "releases/$RELEASE_ID" "$ROOT/opt/rosy/current"
printf 'network: {config: disabled}\n' > "$ROOT/etc/cloud/cloud.cfg.d/99-rosy-network.cfg"
rm -f -- "$ROOT/etc/machine-id" "$ROOT/var/lib/dbus/machine-id" "$ROOT/etc/ssh/ssh_host_"*
: > "$ROOT/etc/machine-id"

systemctl --root "$ROOT" enable NetworkManager.service ssh.service \
    rosy-first-boot.service rosy-release-recover.service rosy-runtime.target

while IFS= read -r package; do
    [[ -z "$package" || "$package" == \#* ]] && continue
    chroot "$ROOT" bash -lc \
        "source /opt/ros/jazzy/setup.bash && source /opt/rosy/current/install/setup.bash && ros2 pkg prefix '$package' >/dev/null"
done < "$PAYLOAD/required-ros-packages.txt"

python3 "$(dirname "$0")/verify-mounted-image.py" --root "$ROOT" --release-id "$RELEASE_ID"
echo "ROOTFS_CUSTOMIZED $RELEASE_ID"
