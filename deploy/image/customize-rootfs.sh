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
# D-225 2.2: where the sealed factory release metadata is exported for the dist.
FACTORY_EXPORT="$PAYLOAD/factory-release"
[[ ! -e "$FACTORY_EXPORT" ]] || fail "payload already holds a factory release export: $FACTORY_EXPORT"
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
PYTHON_REQUIREMENTS="$(dirname "$0")/$(lock_value python_runtime requirements)"
PYTHON_REQUIREMENTS_SHA="$(lock_value python_runtime requirements_sha256)"
CORE_PROBE="$(dirname "$0")/probe-core-runtime.py"
IO_PROBE="$(dirname "$0")/probe-io-runtime.py"
DISPLAY_PROBE="$(dirname "$0")/probe-display-runtime.py"
UART_CONFIG="$(dirname "$0")/../robot/configure-uart-pi5.sh"
BOOT_OVERLAY="$(dirname "$0")/../robot/configure-boot-overlay-pi5.sh"
[[ "$ROS_SOURCE_URL" == https://* ]] || fail "ROS apt source package URL must use HTTPS"
[[ "$ROS_SOURCE_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "ROS apt source package SHA-256 is invalid"
[[ "$WIRINGPI_URL" == https://* ]] || fail "WiringPi package URL must use HTTPS"
[[ "$WIRINGPI_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "WiringPi package SHA-256 is invalid"
[[ -f "$PYTHON_REQUIREMENTS" ]] || fail "CORE Python requirements lock is missing"
[[ "$PYTHON_REQUIREMENTS_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "CORE Python requirements SHA-256 is invalid"
[[ "$(sha256sum "$PYTHON_REQUIREMENTS" | awk '{print $1}')" == "$PYTHON_REQUIREMENTS_SHA" ]] \
    || fail "CORE Python requirements do not match inputs.lock.yaml"
[[ -f "$CORE_PROBE" ]] || fail "CORE runtime probe is missing"
[[ -f "$IO_PROBE" ]] || fail "hardware runtime probe is missing"
[[ -f "$DISPLAY_PROBE" ]] || fail "boot display probe is missing"
[[ -f "$UART_CONFIG" ]] || fail "UART4 motor bus configuration is missing"
[[ -f "$BOOT_OVERLAY" ]] || fail "Pi 5 boot overlay configuration is missing"

ROOT="$(realpath -e "$ROSY_IMAGE_ROOT")"
[[ "$(realpath -e "$ROSY_IMAGE_BOOT")" == "$ROOT/boot/firmware" ]] \
    || fail "ROSY_IMAGE_BOOT is not the image's /boot/firmware"
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
    rm -rf -- "$ROOT/tmp/rosy-native-probe"
    rm -rf -- "$ROOT/tmp/rosy-core-probe"
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
    ca-certificates chrony dnsmasq-base locales network-manager openssh-server openssl python3 python3-pip python3-yaml \
    python3-rosdep ros-jazzy-ros-base ros-jazzy-rmw-cyclonedds-cpp
# D-190: the boot display (rosy-boot-display.service). RPi.GPIO on the Pi 5 is
# the rpi-lgpio compatibility layer; spidev drives the ST7789; PIL, numpy and
# DejaVu draw the card. From the locked Ubuntu suites like every apt package
# here; the versions land in deb-packages.txt and the verifier checks them.
chroot "$ROOT" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3-spidev python3-rpi-lgpio python3-numpy python3-pil fonts-dejavu-core

cp -a "$SOURCE_TREE" "$ROOT/tmp/rosy-src"
if [[ ! -f "$ROOT/etc/ros/rosdep/sources.list.d/20-default.list" ]]; then
    chroot "$ROOT" rosdep init
fi
chroot "$ROOT" rosdep update --rosdistro jazzy
ROSDEP_PATH_OUTPUT="$(
    python3 "$(dirname "$0")/resolve-required-source-paths.py" \
        --source-root "$ROOT/tmp/rosy-src" \
        --required "$PAYLOAD/required-ros-packages.txt" \
        --chroot-prefix /tmp/rosy-src
)" || fail "could not resolve required ROSY package dependency closure"
[[ -n "$ROSDEP_PATH_OUTPUT" ]] || fail "required ROSY package dependency closure is empty"
mapfile -t ROSDEP_SOURCE_PATHS <<< "$ROSDEP_PATH_OUTPUT"
# D-192: third-party packages the release builds itself (sllidar_ros2, which
# bringup exec_depends on) are not in these source paths; skip their keys so
# rosdep never tries to resolve them, whether or not rosdistro knows them.
mapfile -t VENDOR_ROS_PACKAGES < <(
    tr -d '\r' < "$(dirname "$0")/vendor-ros-packages.txt" \
        | sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d'
)
(( ${#VENDOR_ROS_PACKAGES[@]} > 0 )) || fail "vendor ROS package list is empty"
chroot "$ROOT" rosdep install --from-paths "${ROSDEP_SOURCE_PATHS[@]}" \
    --ignore-src -r -y --rosdistro jazzy --skip-keys "${VENDOR_ROS_PACKAGES[*]}"
# D-189 D2: rosdep resolves python3-pydantic/python3-fastapi to Ubuntu's apt
# pydantic 1.10 and fastapi 0.101, and nothing provides websockets. CORE needs
# the hash-locked set. Root pip on Ubuntu installs into
# /usr/local/lib/python3.12/dist-packages, which precedes /usr/lib/python3 on
# sys.path. No --prefix: Debian's posix_prefix scheme would pick site-packages,
# which is not on sys.path at all.
mkdir -p "$ROOT/tmp/rosy-core-probe"
cp "$PYTHON_REQUIREMENTS" "$ROOT/tmp/rosy-core-probe/device-python-requirements.txt"
cp "$CORE_PROBE" "$ROOT/tmp/rosy-core-probe/probe-core-runtime.py"
cp "$IO_PROBE" "$ROOT/tmp/rosy-core-probe/probe-io-runtime.py"
cp "$DISPLAY_PROBE" "$ROOT/tmp/rosy-core-probe/probe-display-runtime.py"
chmod -R a+rX "$ROOT/tmp/rosy-core-probe"  # the probe runs as rosy-core
# umask 022: the service users must be able to read what root installs.
(umask 022 && chroot "$ROOT" python3 -m pip install --no-cache-dir --break-system-packages \
    --ignore-installed --require-hashes --no-deps --only-binary=:all: \
    -r /tmp/rosy-core-probe/device-python-requirements.txt) \
    || fail "CORE Python runtime did not install from the hash lock"
# D-189: record which runtime the image carries; native_release.py refuses a
# release built for another one (python-runtime.sha256 in its signed payload).
install -d -m 0755 "$ROOT/usr/local/share/rosy"
printf '%s\n' "$PYTHON_REQUIREMENTS_SHA" > "$ROOT/usr/local/share/rosy/python-runtime.sha256"
chmod 0644 "$ROOT/usr/local/share/rosy/python-runtime.sha256"
chroot "$ROOT" apt-get clean

chroot "$ROOT" getent group rosy-core >/dev/null 2>&1 || chroot "$ROOT" groupadd --gid 960 rosy-core
chroot "$ROOT" getent passwd rosy-core >/dev/null 2>&1 || \
    chroot "$ROOT" useradd --uid 960 --gid 960 --system --no-create-home --shell /usr/sbin/nologin rosy-core
chroot "$ROOT" getent group rosy-io >/dev/null 2>&1 || chroot "$ROOT" groupadd --gid 961 rosy-io
chroot "$ROOT" getent passwd rosy-io >/dev/null 2>&1 || \
    chroot "$ROOT" useradd --uid 961 --gid 961 --system --no-create-home --shell /usr/sbin/nologin rosy-io
# D-190: the boot display's own account; no login shell, no home of its own
# (the unit gives it HOME=/var/lib/rosy/display). SupplementaryGroups= in the
# units names spi, gpio and i2c; systemd refuses to start a unit whose group
# does not exist, so make sure they do. 99-rosy-display.rules assigns them.
chroot "$ROOT" getent group rosy-display >/dev/null 2>&1 || chroot "$ROOT" groupadd --gid 962 rosy-display
chroot "$ROOT" getent passwd rosy-display >/dev/null 2>&1 || \
    chroot "$ROOT" useradd --uid 962 --gid 962 --system --no-create-home --shell /usr/sbin/nologin rosy-display
for group in spi gpio i2c; do
    chroot "$ROOT" getent group "$group" >/dev/null 2>&1 || chroot "$ROOT" groupadd --system "$group"
done

mkdir -p "$RELEASE" "$ROOT/etc/rosy/trusted-release-keys" "$ROOT/etc/cloud/cloud.cfg.d"
# D-189 D4: the same layout tmpfiles-rosy-state.conf enforces at every boot.
install -d -m 0755 -o root -g root "$ROOT/var/lib/rosy"
chroot "$ROOT" install -d -m 2750 -o rosy-io -g rosy-core /var/lib/rosy/maps
cp -a "$PAYLOAD/." "$RELEASE/"
cp -a "$PAYLOAD/image-overlay/." "$ROOT/"
rm -rf -- "$RELEASE/image-overlay"
# D-192 US-004: the motor bus is UART4 (vendor bringup.py: /dev/ttyAMA4, 1 Mbaud).
# Without dtoverlay=uart4-pi5 there is no ttyAMA4 and so no /dev/rosy-motor.
# Same script and same edit as the on-device retrofit, pointed at the image.
# It also drops console=serial0/ttyAMA0/ttyAMA4 from the boot cmdline and masks
# serial-getty@ttyAMA0/ttyAMA4: Ubuntu's console=serial0 lands on the LiDAR
# UART (rosy-pinky-e4us, release 2026.09.24-010).
bash "$UART_CONFIG" --image-root "$ROOT" \
    || fail "could not enable the UART4 motor bus in the image"

# D-247: the BNO055 IMU sits on I2C0 (GPIO0/GPIO1, 0x28). The Ubuntu base
# enables only i2c_arm (/dev/i2c-1), so without this there is no /dev/i2c-0.
# Verified on rosy_18 (Pi 5 rev 1.1, 6.8.0-1064-raspi) 2026-09-26: chip id
# 0xA0. A runtime `dtoverlay` does not work on this kernel; config.txt only.
bash "$BOOT_OVERLAY" --image-root "$ROOT" --overlay "dtoverlay=i2c0-pi5,pins_0_1"     --comment "Rosy IMU bus (BNO055) on Raspberry Pi 5 GPIO0/GPIO1"     || fail "could not enable the I2C0 IMU bus in the image"
printf '%s\n' "$SOURCE_REVISION" > "$RELEASE/source-revision.txt"
chroot "$ROOT" dpkg-query -W '-f=${Package}\t${Version}\n' | LC_ALL=C sort > "$RELEASE/deb-packages.txt"

ln -s "releases/$RELEASE_ID" "$ROOT/opt/rosy/current"
printf 'network: {config: disabled}\n' > "$ROOT/etc/cloud/cloud.cfg.d/99-rosy-network.cfg"
rm -f -- "$ROOT/etc/machine-id" "$ROOT/var/lib/dbus/machine-id" "$ROOT/etc/ssh/ssh_host_"*
: > "$ROOT/etc/machine-id"

# chrony: CORE SRS §25 — UTC ISO 8601 timestamps and evidence freshness are
# cross-module premises; NTP reachability is a runtime concern, not an image one.
systemctl --root "$ROOT" enable NetworkManager.service chrony.service ssh.service \
    rosy-first-boot.service rosy-first-boot-retry.timer rosy-release-recover.service \
    rosy-runtime.target \
    rosy-boot-status.service rosy-boot-status.timer rosy-boot-status-ready.service \
    rosy-config.service rosy-network.service rosy-boot-display.service \
    rosy-login-code.service rosy-hw-probe.service rosy-hw-probe.path
# D-174 T0: the console banner is rendered at runtime into /run/rosy-boot/issue.
mkdir -p "$ROOT/etc/issue.d"
ln -sfn /run/rosy-boot/issue "$ROOT/etc/issue.d/rosy.issue"
# D-193: the one-time login code on the console (no LCD), written by
# rosy-login-code.service into /run/rosy-boot/login.issue (0600, root).
ln -sfn /run/rosy-boot/login.issue "$ROOT/etc/issue.d/60-rosy-login.issue"
# D-193: `sudo rosy-login-code [--role ...] [--minutes ...]` prints a code to
# the caller's terminal only; the wrapper resolves the link.
mkdir -p "$ROOT/usr/local/sbin"
ln -sfn /opt/rosy/native-runtime/rosy-login-code "$ROOT/usr/local/sbin/rosy-login-code"
# D-247: `sudo rosy-hw-probe [--stdout]` re-runs the board device probe.
ln -sfn /opt/rosy/native-runtime/rosy-hw-probe "$ROOT/usr/local/sbin/rosy-hw-probe"
# D-175 L2: `rosy-diag collect` on PATH; the wrapper resolves the link.
mkdir -p "$ROOT/usr/local/bin"
ln -sfn /opt/rosy/native-runtime/rosy-diag "$ROOT/usr/local/bin/rosy-diag"

while IFS= read -r package; do
    [[ -z "$package" || "$package" == \#* ]] && continue
    chroot "$ROOT" bash -lc \
        "source /opt/ros/jazzy/setup.bash && source /opt/rosy/current/install/setup.bash && ros2 pkg prefix '$package' >/dev/null"
done < "$PAYLOAD/required-ros-packages.txt"

# D-174 F5: import smoke test of the installed native entrypoints, run where the
# image installs them. Recovery runs against an empty probe root, so it touches
# no image state and does not exercise the key or openssl; -B keeps bytecode out
# of the signed release tree.
NATIVE_PROBE=/tmp/rosy-native-probe
rm -rf -- "$ROOT$NATIVE_PROBE"
mkdir -p "$ROOT$NATIVE_PROBE"
RELEASE_KEY=/etc/rosy/trusted-release-keys/rosy-release-2026-01.pem
chroot "$ROOT" python3 -B /opt/rosy/native-runtime/native_release.py \
    --root "$NATIVE_PROBE" --public-key "$RELEASE_KEY" recover \
    || fail "installed native-runtime recovery entrypoint does not run"
chroot "$ROOT" python3 -B /opt/rosy/releases/$RELEASE_ID/deploy/robot/native/native_release.py \
    --root "$NATIVE_PROBE" --public-key "$RELEASE_KEY" recover \
    || fail "installed release native entrypoint does not run"
chroot "$ROOT" python3 -B /opt/rosy/first-boot/rosy-first-boot.py --help >/dev/null \
    || fail "installed first-boot entrypoint does not run"
for entrypoint in rosy-boot-status.py rosy-config-apply.py rosy-network.py rosy-boot-display.py \
    rosy-hw-probe.py rosy-login-code.py; do
    chroot "$ROOT" python3 -B "/opt/rosy/native-runtime/$entrypoint" --help >/dev/null \
        || fail "installed native entrypoint does not run: $entrypoint"
done
# D-247: rosy-hw-probe.service runs `python3 -I` as root; its torque-free motor
# ping needs dynamixel_sdk from the system site, not from a release PYTHONPATH.
chroot "$ROOT" python3 -I -c 'import dynamixel_sdk' \
    || fail "root python3 -I cannot import dynamixel_sdk (rosy-hw-probe motor ping)"
rm -rf -- "$ROOT$NATIVE_PROBE"

[[ "$(tr -d '[:space:]' < "$RELEASE/python-runtime.sha256")" == "$PYTHON_REQUIREMENTS_SHA" ]] \
    || fail "release python-runtime.sha256 does not match the image's Python runtime lock"

# D-189 B: import what rosy-core.service loads at start, as the unit runs it:
# user rosy-core, its HOME, no login shell, no user site, runtime.env if the
# image has one, ROS and the release sourced. Assert the pinned set and
# pydantic 2. -B keeps bytecode out of the signed release tree.
chroot "$ROOT" setpriv --reuid=rosy-core --regid=rosy-core --clear-groups \
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/var/lib/rosy/core PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
    bash --noprofile --norc -c 'set -a; if [ -r /etc/rosy/runtime.env ]; then . /etc/rosy/runtime.env; fi; set +a; source /opt/ros/jazzy/setup.bash && source /opt/rosy/current/install/setup.bash && exec python3 -B /tmp/rosy-core-probe/probe-core-runtime.py --requirements /tmp/rosy-core-probe/device-python-requirements.txt' \
    || fail "CORE does not import inside the image"
# D-192 US-005: the hardware runtime, as rosy-io.service runs it: user
# rosy-io, its HOME, no login shell, no user site. dynamixel_sdk, rosylib
# and the bringup nodes import; sllidar_ros2 and the launch files resolve in
# the release; the units are installed, not enabled. Opens no device.
chroot "$ROOT" setpriv --reuid=rosy-io --regid=rosy-io --clear-groups \
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/var/lib/rosy/io PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
    bash --noprofile --norc -c 'set -a; if [ -r /etc/rosy/runtime.env ]; then . /etc/rosy/runtime.env; fi; set +a; source /opt/ros/jazzy/setup.bash && source /opt/rosy/current/install/setup.bash && exec python3 -B /tmp/rosy-core-probe/probe-io-runtime.py' \
    || fail "the hardware runtime does not import inside the image"
# D-190: the boot display, as rosy-boot-display.service runs it: user
# rosy-display, its HOME, LG_WD and working directory (its StateDirectory),
# RPI_LGPIO_CHIP, no shell, no user site, the release on PYTHONPATH and no
# ROS. spidev, RPi.GPIO (rpi-lgpio), rosylib and the boot card import and
# render; the unit is enabled with its sandbox. Opens no device.
# lgpio creates its notification files in LG_WD or the working directory at
# import (release 007 build: FileNotFoundError without them), so the probe
# needs the state directory the unit gets from systemd. Creating it here with
# the unit's owner and mode is what StateDirectory= would do on first start.
install -d -o 962 -g 962 -m 0750 "$ROOT/var/lib/rosy/display"
chroot "$ROOT" setpriv --reuid=rosy-display --regid=rosy-display --clear-groups \
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/var/lib/rosy/display PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
    LG_WD=/var/lib/rosy/display RPI_LGPIO_CHIP=4 \
    PYTHONPATH=/opt/rosy/current/install/lib/python3.12/site-packages \
    bash --noprofile --norc -c 'cd /var/lib/rosy/display && exec python3 -B /tmp/rosy-core-probe/probe-display-runtime.py' \
    || fail "the boot display does not import inside the image"
rm -rf -- "$ROOT/tmp/rosy-core-probe"

# D-225 2.2: nothing writes into the factory release after this point, so seal
# it (manifest.json + SHA256SUMS) and hand both files to create-image-manifest.py
# through the payload workspace. The image stays unsigned; the offline signer
# signs this SHA256SUMS and first boot installs that signature from the SD bundle.
python3 "$(dirname "$0")/../release/build_payload_release.py" seal \
    --release-dir "$RELEASE" --release-id "$RELEASE_ID" \
    || fail "could not seal the factory release"
[[ ! -e "$RELEASE/SHA256SUMS.sig" ]] || fail "the image must not carry a factory release signature"
mkdir -p "$FACTORY_EXPORT"
cp -- "$RELEASE/manifest.json" "$RELEASE/SHA256SUMS" "$FACTORY_EXPORT/"

python3 "$(dirname "$0")/verify-mounted-image.py" --root "$ROOT" --release-id "$RELEASE_ID"
echo "ROOTFS_CUSTOMIZED $RELEASE_ID"
