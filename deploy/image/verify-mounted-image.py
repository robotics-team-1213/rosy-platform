#!/usr/bin/env python3
"""Inspect a mounted ROSY OS root without executing it."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys


REQUIRED_UNITS = (
    "rosy-first-boot.service",
    "rosy-release-recover.service",
    "rosy-sd-provision.service",
    "rosy-core.service",
    "rosy-runtime.target",
)


def package_names(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


MOTOR_OVERLAY = "dtoverlay=uart4-pi5"
MOTOR_UDEV_RULE = "etc/udev/rules.d/99-rosy-motor.rules"
# D-190: the LCD is SPI0 CE0 (/dev/spidev0.0); the base image enables SPI.
BASE_BOOT_LINES = ("enable_uart=1", "dtparam=i2c_arm=on", "dtparam=spi=on")
# D-247: customize-rootfs.sh adds the IMU bus (BNO055 on I2C0, /dev/i2c-0).
IMU_OVERLAY = "dtoverlay=i2c0-pi5,pins_0_1"
CAMERA_OVERLAY = "dtoverlay=ov5647"
# D-247: the WS2812 lamp driver customize-rootfs.sh builds for the image kernel.
LAMP_OVERLAY = "dtoverlay=rosy-ws281x"
LAMP_DTBO = "boot/firmware/overlays/rosy-ws281x.dtbo"
LAMP_KERNEL_RECORD = "usr/local/share/rosy/lamp-driver-kernel"
LAMP_UDEV_RULE = "etc/udev/rules.d/99-rosy-lamp.rules"
LAMP_MODPROBE = "etc/modprobe.d/rosy-ws281x.conf"
# GPIO19 is RP1 PWM0 channel 3; the default channel 2 is GPIO18, the LCD backlight.
LAMP_OPTIONS = "options rp1_ws281x_pwm pwm_channel=3"
# The LiDAR (UART0) and motor (UART4) buses carry no kernel console or getty.
# Ubuntu's console=serial0 is UART0 on the Pi 5 with enable_uart=1.
BUS_CONSOLE = re.compile(r"console=(serial0|ttyAMA0|ttyAMA4)(,|$)")
# The serial console that remains: the Pi 5 debug UART (3-pin JST), no robot bus.
RECOVERY_CONSOLE = re.compile(r"console=ttyAMA10(,|$)")
BUS_GETTY_MASKS = ("etc/systemd/system/serial-getty@ttyAMA0.service",
                   "etc/systemd/system/serial-getty@ttyAMA4.service")
HARDWARE_UNITS =("rosy-io.service", "rosy-navigation.service")
SLLIDAR_FILES = ("lib/sllidar_ros2/sllidar_node", "share/sllidar_ros2/launch/sllidar_c1_launch.py")
DISPLAY_UNIT = "rosy-boot-display.service"
DISPLAY_UDEV_RULE = "etc/udev/rules.d/99-rosy-display.rules"
# customize-rootfs.sh installs these for the boot display (D-190).
DISPLAY_APT_PACKAGES = ("python3-spidev", "python3-rpi-lgpio", "python3-numpy", "python3-pil",
                        "fonts-dejavu-core")
# D-193: the root login-code issuer, its console banner link and its command.
LOGIN_UNIT = "rosy-login-code.service"
LOGIN_ISSUE_LINK = "etc/issue.d/60-rosy-login.issue"
LOGIN_ISSUE_TARGET = "/run/rosy-boot/login.issue"
LOGIN_COMMAND = "usr/local/sbin/rosy-login-code"
# D-247: the read-only board device probe, its refresh watch and its command.
HW_PROBE_UNITS = ("rosy-hw-probe.service", "rosy-hw-probe.path")
HW_PROBE_COMMAND = "usr/local/sbin/rosy-hw-probe"
# D-247 6: the buzzer/lamp test: the service is started only by its path unit.
HW_TEST_SERVICE = "rosy-hw-test.service"
HW_TEST_PATH = "rosy-hw-test.path"
CORE_DEFAULTS = "install/share/core/config/rosy_default.yaml"


def default_config_tokens(text: str) -> bool | None:
    """True when CORE's packaged defaults carry any API token (D-193 7); None if unreadable."""
    try:
        import yaml
    except ImportError:  # the build host has it; a textual check otherwise
        return "rosy-dev-" in text or bool(re.search(r"(?m)^\s+-\s+(?:token|sha256)\s*:", text))
    try:
        config = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(config, dict):
        return None
    auth = config.get("auth") or {}
    tokens = auth.get("tokens") if isinstance(auth, dict) else auth
    return bool(tokens) or "rosy-dev-" in text


def installed_debs(root: Path) -> set[str]:
    """Packages dpkg records as installed in the mounted root."""
    status = root / "var/lib/dpkg/status"
    if not status.is_file():
        return set()
    installed = set()
    for stanza in status.read_text(encoding="utf-8", errors="replace").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in stanza.splitlines() if ": " in line and line[0] != " ")
        if fields.get("Status") == "install ok installed" and fields.get("Package"):
            installed.add(fields["Package"])
    return installed


def package_states(root: Path) -> dict[str, str]:
    """Each package's dpkg Status line in the mounted root (e.g. "hold ok installed")."""
    status = root / "var/lib/dpkg/status"
    if not status.is_file():
        return {}
    states = {}
    for stanza in status.read_text(encoding="utf-8", errors="replace").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in stanza.splitlines() if ": " in line and line[0] != " ")
        if fields.get("Package") and fields.get("Status"):
            states[fields["Package"]] = fields["Status"]
    return states


def module_vermagic(path: Path) -> str | None:
    """The kernel release a .ko was built for: the first word of its modinfo vermagic."""
    data = path.read_bytes()
    start = data.find(b"\0vermagic=")
    if start < 0:
        return None
    value = data[start + len(b"\0vermagic="):].split(b"\0", 1)[0].decode("utf-8", errors="replace")
    return value.split(" ", 1)[0] or None


def overlay_applies_to_pi5(text: str, overlay: str = MOTOR_OVERLAY) -> bool:
    """Read-only twin of configure-uart-pi5.sh's awk check: the line counts
    before any section header or under [all] / [pi5], comments stripped."""
    active = True
    for raw in text.splitlines():
        stripped = raw.strip()
        if re.fullmatch(r"\[[^]]+\]", stripped):
            active = re.sub(r"\s", "", stripped) in {"[all]", "[pi5]"}
            continue
        line = re.sub(r"\s*#.*", "", raw).strip()
        if active and line == overlay:
            return True
    return False


def camera_configured_for_pi5(text: str) -> bool:
    """The Pinky OV5647 CAM1 overlay needs auto detection disabled."""
    active = True
    disabled = False
    enabled = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if re.fullmatch(r"\[[^]]+\]", stripped):
            active = re.sub(r"\s", "", stripped) in {"[all]", "[pi5]"}
            continue
        line = re.sub(r"\s*#.*", "", raw).strip()
        if active and line == "camera_auto_detect=0":
            disabled = True
        if active and line == "camera_auto_detect=1":
            enabled = True
    return disabled and not enabled and overlay_applies_to_pi5(text, CAMERA_OVERLAY)


def lamp_driver_findings(root: Path) -> list[str]:
    """D-247: the rp1_ws281x_pwm module for the image kernel, its overlay, udev rule and channel."""
    findings = []
    if not (root / LAMP_DTBO).is_file():
        findings.append(f"missing lamp overlay: {LAMP_DTBO}")
    record = root / LAMP_KERNEL_RECORD
    kernel = record.read_text(encoding="utf-8").strip() if record.is_file() else ""
    if not re.fullmatch(r"\d+\.\d+\.\d+-\d+-raspi", kernel):
        findings.append(f"missing lamp driver kernel record: {LAMP_KERNEL_RECORD}")
    else:
        modules = root / "lib/modules" / kernel
        if not (modules / "kernel").is_dir():
            findings.append(f"lamp driver was built for {kernel}, which the image does not carry")
        module = modules / "extra/rp1_ws281x_pwm.ko"
        if not module.is_file():
            findings.append(f"missing lamp driver module: lib/modules/{kernel}/extra/rp1_ws281x_pwm.ko")
        else:
            vermagic = module_vermagic(module)
            if vermagic is None:
                findings.append(f"lamp driver module has no vermagic (recorded kernel {kernel})")
            elif vermagic != kernel:
                findings.append(f"lamp driver module vermagic {vermagic} does not match the recorded kernel {kernel}")
        # An upgrade to another kernel would drop /dev/ws281x_pwm: the kernel is held.
        states = package_states(root)
        for package in (f"linux-image-{kernel}", f"linux-modules-{kernel}"):
            if states.get(package) != "hold ok installed":
                findings.append(f"kernel package is not held for the lamp driver: {package}")
        for package in (f"linux-headers-{kernel}", "linux-raspi", "linux-image-raspi", "linux-headers-raspi"):
            state = states.get(package, "")
            if state.endswith(" installed") and state != "hold ok installed":
                findings.append(f"kernel package is not held for the lamp driver: {package}")
        alias = modules / "modules.alias"
        if not alias.is_file() or "rp1-ws281x-pwm" not in alias.read_text(encoding="utf-8", errors="replace"):
            findings.append(f"lamp driver is not in lib/modules/{kernel}/modules.alias (depmod)")
    if not (root / LAMP_UDEV_RULE).is_file():
        findings.append(f"missing lamp udev rule: {LAMP_UDEV_RULE}")
    options = root / LAMP_MODPROBE
    lines = options.read_text(encoding="utf-8", errors="replace").splitlines() if options.is_file() else []
    if LAMP_OPTIONS not in (line.strip() for line in lines):
        findings.append(f"{LAMP_MODPROBE} does not set pwm_channel=3 (GPIO19; channel 2 is the LCD backlight)")
    return findings


def inspect(root: Path, release_id: str) -> list[str]:
    root = root.resolve()
    findings: list[str] = []
    release = root / "opt/rosy/releases" / release_id
    required_paths = (
        root / "opt/ros/jazzy/setup.bash",
        release / "install/setup.bash",
        root / "etc/rosy/motion_profiles.yaml",
        root / "etc/rosy/cyclonedds.xml",
        root / "opt/rosy/first-boot/rosy-first-boot.py",
        root / "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem",
        root / "opt/rosy/native-runtime/native_release.py",
        root / "opt/rosy/native-runtime/recover-release.sh",
        root / "opt/rosy/native-runtime/signing.py",
        release / "deploy/robot/native/native_release.py",
        release / "deploy/robot/native/signing.py",
    )
    for path in required_paths:
        if not path.is_file():
            findings.append(f"missing required image path: {path.relative_to(root)}")
    # D-174 F1: the native runtime runs from the image and must never leave bytecode
    # behind (it would be unlisted and fail verify()). colcon's install/ tree ships
    # its own __pycache__ as part of the built payload, so it is not checked here.
    for runtime in (root / "opt/rosy/native-runtime", release / "deploy/robot/native"):
        if runtime.is_dir():
            for cache in sorted(runtime.rglob("__pycache__")):
                findings.append(f"bytecode cache in native runtime: {cache.relative_to(root).as_posix()}")
    for unit in REQUIRED_UNITS:
        if not (root / "etc/systemd/system" / unit).is_file():
            findings.append(f"missing systemd unit: {unit}")

    required_file = release / "required-ros-packages.txt"
    inventory_file = release / "rosy-packages.txt"
    required = package_names(required_file)
    inventory = package_names(inventory_file)
    for package in sorted(required - inventory):
        findings.append(f"required ROS package missing from inventory: {package}")

    if (root / "usr/bin/docker").exists() or (root / "usr/bin/dockerd").exists():
        findings.append("docker must not be installed in the product image")
    # CORE SRS §25: UTC ISO 8601 timestamps (evidence freshness, Fleet log
    # correlation) presume a synced clock — chrony ships enabled in the image.
    if not (root / "usr/sbin/chronyd").exists():
        findings.append("chrony is not installed: timestamps presume a synced clock")
    elif not (root / "etc/systemd/system/multi-user.target.wants/chrony.service").exists():
        findings.append("chrony.service is not enabled")
    # D-192 US-003: CORE_READY is shown as soon as the runtime target settles.
    # lexists: `systemctl --root` links point at the image's /usr/lib, not the host's.
    ready = "rosy-boot-status-ready.service"
    if not (root / "etc/systemd/system" / ready).is_file():
        findings.append(f"missing systemd unit: {ready}")
    elif not os.path.lexists(root / "etc/systemd/system/multi-user.target.wants" / ready):
        findings.append(f"{ready} is not enabled")
    # D-192 US-004: the motor bus (UART4) and its /dev/rosy-motor alias.
    config = root / "boot/firmware/config.txt"
    if not config.is_file():
        findings.append("missing boot configuration: boot/firmware/config.txt")
    elif not overlay_applies_to_pi5(config.read_text(encoding="utf-8", errors="replace")):
        findings.append(f"boot/firmware/config.txt does not enable {MOTOR_OVERLAY} for the Pi 5")
    if config.is_file():
        # The Ubuntu base image provides these today (LiDAR UART0 /dev/ttyAMA0,
        # ADC /dev/i2c-1, both seen on rosy-pinky-e4us); a new base must not drop them.
        text = config.read_text(encoding="utf-8", errors="replace")
        for line in BASE_BOOT_LINES:
            if not overlay_applies_to_pi5(text, line):
                findings.append(f"boot/firmware/config.txt lost {line} for the Pi 5 (base image changed?)")
        if not overlay_applies_to_pi5(text, IMU_OVERLAY):
            findings.append(f"boot/firmware/config.txt does not enable {IMU_OVERLAY} for the Pi 5 (IMU bus)")
        if not camera_configured_for_pi5(text):
            findings.append("boot/firmware/config.txt does not enable OV5647 CAM1 with camera_auto_detect=0")
        if not overlay_applies_to_pi5(text, LAMP_OVERLAY):
            findings.append(f"boot/firmware/config.txt does not enable {LAMP_OVERLAY} for the Pi 5 (lamp driver)")
    findings += lamp_driver_findings(root)
    cmdline = root / "boot/firmware/cmdline.txt"
    if not cmdline.is_file():
        findings.append("missing kernel command line: boot/firmware/cmdline.txt")
    else:
        tokens = cmdline.read_text(encoding="utf-8", errors="replace").split()
        for token in tokens:
            if BUS_CONSOLE.match(token):
                findings.append(f"boot/firmware/cmdline.txt routes a console to a robot bus UART: {token}")
        if not any(RECOVERY_CONSOLE.match(token) for token in tokens):
            findings.append("boot/firmware/cmdline.txt has no recovery console on the debug UART (console=ttyAMA10)")
    for mask in BUS_GETTY_MASKS:
        # A regular file is not a mask: only a symlink to /dev/null is.
        path = root / mask
        if not os.path.islink(path) or os.readlink(path) != "/dev/null":
            findings.append(f"serial getty is not masked: {mask} -> /dev/null")
    if not (root / MOTOR_UDEV_RULE).is_file():
        findings.append(f"missing motor udev rule: {MOTOR_UDEV_RULE}")
    # D-192 US-005: the hardware runtime ships installed, not enabled (D-161).
    for unit in HARDWARE_UNITS:
        if not (root / "etc/systemd/system" / unit).is_file():
            findings.append(f"missing systemd unit: {unit}")
        for wants in sorted((root / "etc/systemd/system").glob("*.wants")):
            if os.path.lexists(wants / unit):
                findings.append(f"{unit} must not be enabled ({wants.name})")
    if "sllidar_ros2" not in inventory:
        findings.append("sllidar_ros2 (RPLIDAR C1 driver) is missing from the release inventory")
    for relative in SLLIDAR_FILES:
        if not (release / "install" / relative).is_file():
            findings.append(f"sllidar_ros2 is not installed: install/{relative}")
    # D-190: the boot display ships enabled, with its udev rule and libraries.
    if not (root / "etc/systemd/system" / DISPLAY_UNIT).is_file():
        findings.append(f"missing systemd unit: {DISPLAY_UNIT}")
    elif not os.path.lexists(root / "etc/systemd/system/multi-user.target.wants" / DISPLAY_UNIT):
        findings.append(f"{DISPLAY_UNIT} is not enabled")
    if not (root / DISPLAY_UDEV_RULE).is_file():
        findings.append(f"missing display udev rule: {DISPLAY_UDEV_RULE}")
    # D-193: login codes come from root, not CORE; the device defaults have no login.
    if not (root / "etc/systemd/system" / LOGIN_UNIT).is_file():
        findings.append(f"missing systemd unit: {LOGIN_UNIT}")
    elif not os.path.lexists(root / "etc/systemd/system/multi-user.target.wants" / LOGIN_UNIT):
        findings.append(f"{LOGIN_UNIT} is not enabled")
    link = root / LOGIN_ISSUE_LINK
    if not os.path.lexists(link) or (os.path.islink(link) and os.readlink(link) != LOGIN_ISSUE_TARGET):
        findings.append(f"missing console login banner link: {LOGIN_ISSUE_LINK} -> {LOGIN_ISSUE_TARGET}")
    if not os.path.lexists(root / LOGIN_COMMAND):
        findings.append(f"missing login code command: {LOGIN_COMMAND}")
    # D-247: the board device card reads what this root probe writes.
    for unit in HW_PROBE_UNITS:
        if not (root / "etc/systemd/system" / unit).is_file():
            findings.append(f"missing systemd unit: {unit}")
        elif not os.path.lexists(root / "etc/systemd/system/multi-user.target.wants" / unit):
            findings.append(f"{unit} is not enabled")
    if not os.path.lexists(root / HW_PROBE_COMMAND):
        findings.append(f"missing hardware probe command: {HW_PROBE_COMMAND}")
    if not (root / "etc/systemd/system" / HW_TEST_SERVICE).is_file():
        findings.append(f"missing systemd unit: {HW_TEST_SERVICE}")
    if not (root / "etc/systemd/system" / HW_TEST_PATH).is_file():
        findings.append(f"missing systemd unit: {HW_TEST_PATH}")
    elif not os.path.lexists(root / "etc/systemd/system/multi-user.target.wants" / HW_TEST_PATH):
        findings.append(f"{HW_TEST_PATH} is not enabled")
    defaults = release / CORE_DEFAULTS
    if not defaults.is_file():
        findings.append(f"missing CORE defaults: {defaults.relative_to(root)}")
    else:
        carries = default_config_tokens(defaults.read_text(encoding="utf-8", errors="replace"))
        if carries is None:
            findings.append(f"CORE defaults are unreadable: {defaults.relative_to(root)}")
        elif carries:
            findings.append(f"CORE defaults carry API tokens (D-193 fail closed): {defaults.relative_to(root)}")
    debs = installed_debs(root)
    for package in DISPLAY_APT_PACKAGES:
        if package not in debs:
            findings.append(f"boot display package is not installed: {package}")
    # D-176: the fallback AP is NetworkManager shared mode, which runs dnsmasq.
    if not (root / "usr/sbin/dnsmasq").exists():
        findings.append("dnsmasq is not installed: the fallback AP (NM shared mode) cannot start")
    runtime = root / "etc/rosy/runtime.env"
    if runtime.exists():
        content = runtime.read_text(encoding="utf-8", errors="replace")
        if re.search(r"(?m)^(ROSY_NAMESPACE|ROSY_ROBOT_NUMBER|ROS_DOMAIN_ID)=.+$", content):
            findings.append("common image is not device-neutral: runtime identity is populated")
    # D-225 2.2: the factory release is sealed in the image and unsigned; first
    # boot installs the offline signature the SD bundle carries.
    for name in ("manifest.json", "SHA256SUMS"):
        if not (release / name).is_file():
            findings.append(f"factory release is not sealed: missing {(release / name).relative_to(root)}")
    if os.path.lexists(release / "SHA256SUMS.sig"):
        findings.append("factory release must be unsigned in the image (first boot installs the signature)")
    complete = root / "var/lib/rosy/provisioning/complete.json"
    if complete.exists():
        findings.append(f"common image contains device-specific state: {complete.relative_to(root)}")
    connections = root / "etc/NetworkManager/system-connections"
    if connections.is_dir() and any(connections.iterdir()):
        findings.append(f"common image contains device-specific state: {connections.relative_to(root)}")
    return findings


def verify_factory_release(root: Path, release_id: str, dist: Path, public_key: Path) -> list[str]:
    """Would first boot's signature make native_release verify() accept the factory release?

    The image is left untouched: its factory release is copied to a scratch
    root, the offline signature from the signed dist
    (``factory-release/<id>/SHA256SUMS.sig``) is added there, and the
    checkout's native_release.py verifies it exactly as the robot will.
    """
    import shutil
    import tempfile

    repo = Path(__file__).resolve().parents[2]
    for tools in (repo / "deploy/robot/native", repo / "deploy/release"):
        if str(tools) not in sys.path:
            sys.path.append(str(tools))
    from native_release import NativeReleaseManager

    release = root.resolve() / "opt/rosy/releases" / release_id
    exported = dist / "factory-release" / release_id
    signature = exported / "SHA256SUMS.sig"
    if not signature.is_file():
        return [f"signed dist has no factory release signature: {signature}"]
    if not (release / "SHA256SUMS").is_file():
        return [f"factory release is not sealed: {release / 'SHA256SUMS'}"]
    findings = []
    for name in ("SHA256SUMS", "manifest.json"):
        if not (exported / name).is_file() or (exported / name).read_bytes() != (release / name).read_bytes():
            findings.append(f"dist factory-release/{release_id}/{name} is not the image's")
    if findings:
        return findings
    with tempfile.TemporaryDirectory(prefix="rosy-factory-verify-") as scratch:
        copy = Path(scratch) / "opt/rosy/releases" / release_id
        shutil.copytree(release, copy, symlinks=True)
        shutil.copyfile(signature, copy / "SHA256SUMS.sig")
        try:
            NativeReleaseManager(root=Path(scratch), public_key=public_key).verify(release_id)
        except (OSError, ValueError, RuntimeError) as exc:
            return [f"factory release would not verify after first boot: {exc}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    # D-225 2.2 (BUILD_GO): the signed dist and the trusted key, to prove the
    # factory release verifies once first boot adds the dist's signature.
    parser.add_argument("--factory-dist", type=Path)
    parser.add_argument("--public-key", type=Path)
    args = parser.parse_args()
    if (args.factory_dist is None) != (args.public_key is None):
        parser.error("--factory-dist and --public-key go together")
    findings = inspect(args.root, args.release_id)
    if args.factory_dist is not None:
        findings += verify_factory_release(args.root, args.release_id, args.factory_dist, args.public_key)
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "release_id": args.release_id}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
