#!/usr/bin/env bash
# Install the device-twin rootfs inside `docker build` (twin only, never shipped).
# CTX holds: repo.tar (git archive HEAD), twin/ (tools/device_twin), keys/
# (throwaway test public key), releases/<factory>.tar.gz and twin.env.
set -euo pipefail

CTX="$1"
# shellcheck disable=SC1091
. "$CTX/twin.env"   # FACTORY_RELEASE PYTHON_RUNTIME API_BASE REPO API_PORT

SRC="$(mktemp -d)"
tar -xf "$CTX/repo.tar" -C "$SRC"
NATIVE="$SRC/deploy/robot/pinky_pro/native"

# Accounts, as customize-rootfs.sh creates them.
groupadd --gid 960 rosy-core && useradd --uid 960 --gid 960 --system --no-create-home --shell /usr/sbin/nologin rosy-core
groupadd --gid 961 rosy-io && useradd --uid 961 --gid 961 --system --no-create-home --shell /usr/sbin/nologin rosy-io
groupadd --gid 963 rosy-camera && useradd --uid 963 --gid 963 --system --no-create-home --shell /usr/sbin/nologin rosy-camera
groupadd --gid 962 rosy-display && useradd --uid 962 --gid 962 --system --no-create-home --shell /usr/sbin/nologin rosy-display
for group in spi gpio i2c dialout video; do getent group "$group" >/dev/null || groupadd --system "$group"; done
# The operator account the publish tool's (fake) ssh logs in as; sudo -n like the robot.
useradd --create-home --shell /bin/bash rosy
echo 'rosy ALL=(root) NOPASSWD: ALL' > /etc/sudoers.d/rosy && chmod 0440 /etc/sudoers.d/rosy

# Present on the robot's Ubuntu (kmod, udev) but not in the minimal container;
# rosy-auto-update.service lists both in ReadWritePaths= without "-", so a
# missing one fails the unit with 226/NAMESPACE.
install -d -m 0755 /etc/modprobe.d /etc/udev/rules.d

# The immutable native runtime, exactly as the image installs it.
mkdir -p /opt/rosy/releases
bash "$NATIVE/install-native-runtime.sh" /opt/rosy/native-runtime
# The udev rules and modprobe options the image overlay installs (build-native-payload.sh).
install -m 0644 "$SRC"/deploy/robot/pinky_pro/udev/*.rules /etc/udev/rules.d/
install -m 0644 "$SRC"/deploy/robot/pinky_pro/modprobe/*.conf /etc/modprobe.d/

# The real rosy units (sync-image-layer.py UNITS), plus the image-only first-boot gate as a stub.
for unit in rosy-release-recover.service rosy-sd-provision.service rosy-core.service rosy-runtime.target \
            rosy-io.service rosy-camera.service rosy-navigation.service rosy-boot-status.service \
            rosy-boot-status.timer rosy-boot-status-ready.service rosy-boot-display.service \
            rosy-config.service rosy-network.service rosy-login-code.service rosy-hw-probe.service \
            rosy-hw-probe.path rosy-hw-test.service rosy-hw-test.path rosy-auto-update.service \
            rosy-auto-update.timer; do
    install -m 0644 "$NATIVE/$unit" "/etc/systemd/system/$unit"
done
install -m 0644 "$CTX/twin/image/rosy-first-boot.service" /etc/systemd/system/rosy-first-boot.service
install -m 0644 "$NATIVE/tmpfiles-rosy-state.conf" /usr/lib/tmpfiles.d/rosy-state.conf
for unit in rosy-core rosy-io rosy-camera; do
    install -D -m 0644 "$CTX/twin/image/dropins/$unit.conf" "/etc/systemd/system/$unit.service.d/twin.conf"
done

# Device configuration.
install -d -m 0755 /etc/rosy /etc/rosy/trusted-release-keys /etc/rosy/approvals /usr/local/share/rosy
install -m 0644 "$CTX/keys/rosy-release-2026-01.pem" /etc/rosy/trusted-release-keys/rosy-release-2026-01.pem
printf '%s\n' "$PYTHON_RUNTIME" > /usr/local/share/rosy/python-runtime.sha256
cat > /etc/rosy/runtime.env <<EOF
ROS_DOMAIN_ID=42
ROSY_NAMESPACE=rosy_twin
ROSY_ROBOT_NUMBER=99
ROSY_CMD_VEL_TIMEOUT_S=0.5
ROSY_RUNTIME_MODE=core
ROSY_IO_DRIVE_ENABLED=false
ROSY_DEPLOYMENT=device
ROSY_API_PORT=$API_PORT
EOF
chmod 0600 /etc/rosy/runtime.env
install -d -m 0755 /var/lib/rosy /var/lib/rosy/provisioning /var/lib/rosy/updates
echo '{"twin": true}' > /var/lib/rosy/provisioning/complete.json
printf '{"enabled": true, "repo": "%s", "api_base": "%s"}\n' "$REPO" "$API_BASE" > /var/lib/rosy/updates/config.json
chmod 0644 /var/lib/rosy/updates/config.json

# The factory release, unpacked by the real unpack script, and current -> it.
cp "$CTX/releases/$FACTORY_RELEASE.tar.gz" /tmp/factory.tar.gz
bash /opt/rosy/native-runtime/rosy-release-unpack.sh "$FACTORY_RELEASE" /tmp/factory.tar.gz /opt/rosy/releases
ln -s "/opt/rosy/releases/$FACTORY_RELEASE" /opt/rosy/current
python3 -B /opt/rosy/native-runtime/native_release.py \
    --public-key /etc/rosy/trusted-release-keys/rosy-release-2026-01.pem verify --release-id "$FACTORY_RELEASE"

# Enabled as on the image (customize-rootfs.sh), minus hardware units. The
# auto-update timer stays disabled: scenarios start the service by hand.
systemctl enable rosy-release-recover.service rosy-runtime.target rosy-first-boot.service
# Container noise that has no robot counterpart.
# systemd-udevd stays: sync-image-layer.py runs `udevadm control --reload`. The
# container has its own network namespace, so it gets no host uevents; the
# coldplug trigger is masked so it never re-runs rules on the WSL VM's devices.
systemctl mask systemd-udev-trigger.service systemd-udev-settle.service \
    getty@tty1.service console-getty.service systemd-networkd-wait-online.service 2>/dev/null || true

# Twin tools (not part of any release or of the native runtime).
install -d -m 0755 /opt/twin
install -m 0755 "$CTX/twin/image/twin-control" /usr/local/bin/twin-control
install -m 0755 "$CTX/twin/image/sandbox_probe.py" /opt/twin/sandbox_probe.py
# The probe unit is the real rosy-auto-update.service with only ExecStart swapped.
sed 's#^ExecStart=.*#ExecStart=/usr/bin/python3 -I -B /opt/twin/sandbox_probe.py#' \
    /etc/systemd/system/rosy-auto-update.service > /etc/systemd/system/twin-sandbox-probe.service
rm -rf "$SRC"
