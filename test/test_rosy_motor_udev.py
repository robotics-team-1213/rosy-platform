"""The native product runtime addresses the motor bus as /dev/rosy-motor.

`rosy-io.service`/`rosy-navigation.service` hardcode
`DeviceAllow=/dev/rosy-motor` and `motor_device:=/dev/rosy-motor`, but no
udev rule ever created that name on the host — the compose device mapping
was the only thing that did, and compose is development-only (D-161).
Without this rule the native I/O service cannot open the motor bus at all.

Contract (communication-protocol report 2026-09-22 §8-F / remediation plan T3):
the rule ships in-tree, the native image bakes it into /etc/udev/rules.d,
and configure-uart-pi5.sh retrofits it on existing devices (the alias is
meaningless without the UART4 overlay that script owns).
"""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT =Path(__file__).resolve().parents[1]

RULE = ROOT / "deploy" / "robot" / "udev" / "99-rosy-motor.rules"
UART_SCRIPT = ROOT / "deploy" / "robot" / "configure-uart-pi5.sh"
PAYLOAD = ROOT / "deploy" / "image" / "build-native-payload.sh"
IO_UNIT = ROOT / "deploy" / "robot" / "native" / "rosy-io.service"
NAV_UNIT = ROOT / "deploy" / "robot" / "native" / "rosy-navigation.service"
VERIFY_MOTORS = ROOT / "deploy" / "robot" / "verify" / "verify-motors.sh"


def test_rule_creates_stable_alias():
    text = RULE.read_text(encoding="utf-8")
    assert 'KERNEL=="ttyAMA4"' in text
    assert 'SYMLINK+="rosy-motor"' in text
    assert 'GROUP="dialout"' in text
    assert 'MODE="0660"' in text


def test_uart_script_installs_rule_before_idempotent_exit():
    """Both paths (already configured / adding overlay) must install the rule,
    so the call has to run before the early-exit PASS."""
    text = UART_SCRIPT.read_text(encoding="utf-8")
    assert "99-rosy-motor.rules" in text
    assert "/etc/udev/rules.d" in text
    # Find the top-level call on its own line, not the `() {` definition.
    call_site = text.find("\ninstall_motor_udev_rule\n")
    exit_pos = text.find("is already configured")
    assert 0 < call_site < exit_pos, (
        "install_motor_udev_rule must run before the already-configured "
        "early exit so re-runs on provisioned devices still get the rule")


def test_native_image_bakes_the_rule():
    text = PAYLOAD.read_text(encoding="utf-8")
    assert "udev/99-rosy-motor.rules" in text
    assert "etc/udev/rules.d" in text


def test_native_units_and_probe_agree_on_the_alias():
    for unit in (IO_UNIT, NAV_UNIT):
        text = unit.read_text(encoding="utf-8")
        assert "DeviceAllow=/dev/rosy-motor rw" in text, unit
        assert "motor_device:=/dev/rosy-motor" in text, unit
    assert "/dev/rosy-motor" in VERIFY_MOTORS.read_text(encoding="utf-8")


# --- D-192 US-004: the image enables UART4, the rule's only source ----------
#
# rosy-pinky-e4us 2026-09-24: /dev/ttyAMA4 and /dev/rosy-motor did not exist.
# config.txt had no dtoverlay=uart4-pi5; the rule was in the image, the
# overlay only in this retrofit script, which the image never ran.

CUSTOMIZER = ROOT / "deploy" / "image" / "customize-rootfs.sh"
VERIFIER = ROOT / "deploy" / "image" / "verify-mounted-image.py"
BASH = shutil.which("bash")
# The Ubuntu 24.04 raspi config.txt shape: sections, includes, comments.
UBUNTU_CONFIG = (
    "[all]\nkernel=vmlinuz\ncmdline=cmdline.txt\ninitramfs initrd.img followkernel\n\n"
    "[pi4]\nmax_framebuffers=2\narm_boost=1\n\n"
    "[all]\n# Enable the audio output, I2C and SPI interfaces on the GPIO header.\n"
    "dtparam=audio=on\ndtparam=i2c_arm=on\ndtparam=spi=on\n\n"
    "[cm4]\ndtoverlay=dwc2,dr_mode=host\n\n[all]\n"
)


def test_image_applies_the_overlay_with_the_retrofit_script_not_a_copy():
    customizer = CUSTOMIZER.read_text(encoding="utf-8")

    assert 'UART_CONFIG="$(dirname "$0")/../robot/configure-uart-pi5.sh"' in customizer
    call = 'bash "$UART_CONFIG" --image-root "$ROOT"'
    assert call in customizer
    # After the overlay (and its udev rule) lands, before the image is accepted.
    assert customizer.index('cp -a "$PAYLOAD/image-overlay/." "$ROOT/"') < customizer.index(call)
    assert customizer.index(call) < customizer.index("verify-mounted-image.py")
    # The customizer never edits config.txt itself: the UART script and, for the
    # D-247 IMU bus and lamp driver, configure-boot-overlay-pi5.sh do.
    code_lines = [line for line in customizer.splitlines() if not line.lstrip().startswith("#")]
    assert all(line.startswith('bash "$BOOT_OVERLAY" --image-root "$ROOT" --overlay "dtoverlay=')
               for line in code_lines if "dtoverlay=" in line)
    assert "config.txt" not in "\n".join(code_lines)
    # The boot partition the script edits is the one image-workspace.sh mounted.
    assert '"$(realpath -e "$ROSY_IMAGE_BOOT")" == "$ROOT/boot/firmware"' in customizer


def test_verifier_checks_the_overlay_and_the_rule():
    verifier = VERIFIER.read_text(encoding="utf-8")
    assert 'MOTOR_OVERLAY = "dtoverlay=uart4-pi5"' in verifier
    assert 'MOTOR_UDEV_RULE = "etc/udev/rules.d/99-rosy-motor.rules"' in verifier


def _verifier():
    spec = importlib.util.spec_from_file_location("verify_mounted_image_uart", VERIFIER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    return subprocess.run(
        [BASH, "-c", 'cygpath -u "$1"', "_", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


# Ubuntu's cmdline.txt ships console=serial0,115200; with enable_uart=1 that is
# /dev/ttyAMA0, the RPLIDAR C1 port (rosy-pinky-e4us, release 2026.09.24-010).
UBUNTU_CMDLINE = ("console=serial0,115200 multipath=off dwc_otg.lpm_enable=0 console=tty1 "
                  "root=LABEL=writable rootfstype=ext4 rootwait fixrtc\n")
CLEAN_CMDLINE = ("console=ttyAMA10,115200 multipath=off dwc_otg.lpm_enable=0 console=tty1 "
                 "root=LABEL=writable rootfstype=ext4 rootwait fixrtc\n")


def _image(tmp_path: Path, config: str, cmdline: str = UBUNTU_CMDLINE) -> Path:
    root = tmp_path / "image"
    (root / "boot/firmware").mkdir(parents=True)
    (root / "boot/firmware/config.txt").write_bytes(config.encode("utf-8"))
    (root / "boot/firmware/cmdline.txt").write_bytes(cmdline.encode("utf-8"))
    return root


def _configure(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, UART_SCRIPT.as_posix(), "--image-root", _bash_path(root)],
        capture_output=True, text=True, check=False,
    )


@pytest.mark.skipif(BASH is None, reason="bash runs the retrofit script")
def test_image_mode_appends_the_overlay_under_all_and_installs_the_rule(tmp_path):
    root = _image(tmp_path, UBUNTU_CONFIG)

    completed = _configure(root)

    assert completed.returncode == 0, completed.stderr
    assert "PASS UART_CONFIG added dtoverlay=uart4-pi5" in completed.stdout
    assert "REBOOT_REQUIRED" not in completed.stdout
    config = (root / "boot/firmware/config.txt").read_bytes().decode("utf-8")
    assert config == UBUNTU_CONFIG + (
        "\n[all]\n# Rosy motor bus on Raspberry Pi 5 GPIO12/GPIO13\ndtoverlay=uart4-pi5\n")
    assert _verifier().overlay_applies_to_pi5(config)
    assert (root / "etc/udev/rules.d/99-rosy-motor.rules").read_bytes() == RULE.read_bytes()
    # Nothing else is left on the boot partition of a common image.
    assert sorted(p.name for p in (root / "boot/firmware").iterdir()) == ["cmdline.txt", "config.txt"]


@pytest.mark.skipif(BASH is None, reason="bash runs the retrofit script")
def test_image_mode_is_idempotent(tmp_path):
    root = _image(tmp_path, UBUNTU_CONFIG)
    assert _configure(root).returncode == 0
    first = (root / "boot/firmware/config.txt").read_bytes()

    completed = _configure(root)

    assert completed.returncode == 0, completed.stderr
    assert "is already configured" in completed.stdout
    assert "already current" in completed.stdout
    assert (root / "boot/firmware/config.txt").read_bytes() == first


@pytest.mark.skipif(BASH is None, reason="bash runs the retrofit script")
@pytest.mark.parametrize(
    ("config", "already"),
    [
        ("[pi4]\ndtoverlay=uart4-pi5\n", False),        # a Pi 4 section does not apply
        ("[pi5]\ndtoverlay=uart4-pi5\n", True),
        ("dtoverlay=uart4-pi5\n", True),                # before any section: applies
        ("[all]\n#dtoverlay=uart4-pi5\n", False),       # commented out
        ("[cm4]\ndtoverlay=uart4-pi5\n[all]\n", False),
    ],
)
def test_the_verifier_reads_config_txt_as_the_script_does(tmp_path, config, already):
    root = _image(tmp_path, config)

    completed = _configure(root)

    assert completed.returncode == 0, completed.stderr
    assert ("is already configured" in completed.stdout) is already
    assert _verifier().overlay_applies_to_pi5(config) is already
    after = (root / "boot/firmware/config.txt").read_text(encoding="utf-8")
    assert _verifier().overlay_applies_to_pi5(after)


@pytest.mark.skipif(BASH is None, reason="bash runs the retrofit script")
def test_image_mode_refuses_the_running_system_and_relative_roots(tmp_path):
    for bad in ("/", "relative/root"):
        completed = subprocess.run(
            [BASH, UART_SCRIPT.as_posix(), "--image-root", bad],
            capture_output=True, text=True, check=False,
        )
        assert completed.returncode != 0
        assert "FAIL UART_CONFIG" in completed.stderr


def test_the_device_path_writes_vfat_safely():
    # /boot/firmware is vfat: chmod that drops the mount mask's x bits is EPERM.
    text = UART_SCRIPT.read_text(encoding="utf-8")
    edit = text[text.index("config_tmp=\"$(mktemp"):]
    assert "install -o root -g root -m 0644 \"$CONFIG_FILE\"" not in text
    assert "--preserve=mode,ownership" not in text
    assert 'mv -f "$config_tmp" "$CONFIG_FILE"' in edit


# --- LiDAR UART console isolation (rosy-pinky-e4us, release 2026.09.24-010) --
#
# serial-getty@ttyAMA0 (agetty) and the kernel console held the LiDAR port and
# sllidar_node timed out; with the console removed, health OK and 10 Hz. The
# serial console moves to the Pi 5 debug UART (ttyAMA10), not away entirely.


@pytest.mark.skipif(BASH is None, reason="bash runs the retrofit script")
def test_image_mode_moves_the_serial_console_and_masks_the_bus_gettys(tmp_path):
    root = _image(tmp_path, UBUNTU_CONFIG)

    completed = _configure(root)

    assert completed.returncode == 0, completed.stderr
    assert "PASS CONSOLE_ISOLATION moved the serial console to ttyAMA10" in completed.stdout
    assert "REBOOT_REQUIRED" not in completed.stdout
    assert (root / "boot/firmware/cmdline.txt").read_bytes().decode("utf-8") == CLEAN_CMDLINE
    masks = [root / f"etc/systemd/system/serial-getty@{tty}.service" for tty in ("ttyAMA0", "ttyAMA4")]
    if not all(mask.is_symlink() for mask in masks):
        pytest.skip("bash could not create symlinks on this host (Windows without symlink rights)")
    assert all(os.readlink(mask) == "/dev/null" for mask in masks)
    findings = _verifier().inspect(root, "none")
    assert not [f for f in findings if "cmdline" in f or "serial getty" in f]


@pytest.mark.skipif(BASH is None, reason="bash runs the retrofit script")
@pytest.mark.parametrize(
    ("cmdline", "expected"),
    [
        (UBUNTU_CMDLINE, CLEAN_CMDLINE),
        ("console=ttyAMA0,115200 console=tty1 rootwait\n", "console=ttyAMA10,115200 console=tty1 rootwait\n"),
        ("console=ttyAMA4,1000000 console=tty1 rootwait\r\n", "console=ttyAMA10,115200 console=tty1 rootwait\n"),
        # An existing debug-UART console (any baud) and the screen stay as they are.
        ("console=ttyAMA10,115200 console=tty1 rootwait\n", "console=ttyAMA10,115200 console=tty1 rootwait\n"),
        ("console=tty1 console=ttyAMA10,921600\n", "console=tty1 console=ttyAMA10,921600\n"),
        # A lookalike device name is not the bus.
        ("console=ttyAMA01 console=tty1\n", "console=ttyAMA10,115200 console=ttyAMA01 console=tty1\n"),
    ],
)
def test_image_mode_edits_only_bus_consoles_and_is_idempotent(tmp_path, cmdline, expected):
    root = _image(tmp_path, UBUNTU_CONFIG, cmdline)
    assert _configure(root).returncode == 0
    assert (root / "boot/firmware/cmdline.txt").read_bytes().decode("utf-8") == expected

    again = _configure(root)

    assert again.returncode == 0, again.stderr
    assert "no console on ttyAMA0/ttyAMA4, recovery console on ttyAMA10" in again.stdout
    assert "masked" not in again.stdout
    assert (root / "boot/firmware/cmdline.txt").read_bytes().decode("utf-8") == expected


@pytest.mark.skipif(BASH is None, reason="bash runs the retrofit script")
def test_image_mode_refuses_a_missing_cmdline_before_editing(tmp_path):
    root = _image(tmp_path, UBUNTU_CONFIG)
    (root / "boot/firmware/cmdline.txt").unlink()

    completed = _configure(root)

    assert completed.returncode != 0
    assert "cmdline.txt must be a regular non-symlink file" in completed.stderr
    assert (root / "boot/firmware/config.txt").read_bytes().decode("utf-8") == UBUNTU_CONFIG
    assert not (root / "etc").exists()


def test_the_script_cleans_both_staged_files_and_reports_reboot_once():
    text = UART_SCRIPT.read_text(encoding="utf-8")
    trap = text.index("trap 'rm -f \"${config_tmp:-}\" \"${cmdline_tmp:-}\"' EXIT")
    assert trap < text.index("\nisolate_bus_consoles\n")
    assert text.count('echo "REBOOT_REQUIRED') == 1


def test_console_isolation_runs_before_the_idempotent_exit():
    text = UART_SCRIPT.read_text(encoding="utf-8")
    assert 0 < text.find("\nisolate_bus_consoles\n") < text.find("is already configured")


def test_the_device_verifier_reports_a_console_on_the_lidar_uart():
    verify_pi = (ROOT / "deploy" / "robot" / "verify" / "verify-pi.sh").read_text(encoding="utf-8")
    assert "/proc/cmdline" in verify_pi
    assert "console=(serial0|ttyAMA0|ttyAMA4)(,|$)" in verify_pi
    assert "for tty in ttyAMA0 ttyAMA4; do" in verify_pi
    assert 'systemctl is-active --quiet "serial-getty@${tty}.service"' in verify_pi
    assert '!= "masked"' in verify_pi
    assert "configure-uart-pi5.sh and reboot" in verify_pi
