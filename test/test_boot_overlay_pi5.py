"""D-247: the image enables the IMU bus (I2C0) and the WS2812 lamp overlay in config.txt.

rosy_18 2026-09-26: /dev/i2c-0 appears only with `dtoverlay=i2c0-pi5,pins_0_1`
in config.txt and a reboot; a runtime `dtoverlay` does not work on the Ubuntu
6.8 raspi kernel. configure-boot-overlay-pi5.sh makes the edit, with the same
Pi 5 section rule the UART script and verify-mounted-image.py use.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "robot" / "configure-boot-overlay-pi5.sh"
CUSTOMIZER = ROOT / "deploy" / "image" / "customize-rootfs.sh"
VERIFIER = ROOT / "deploy" / "image" / "verify-mounted-image.py"
BASH = shutil.which("bash")
IMU = "dtoverlay=i2c0-pi5,pins_0_1"
CAMERA = "dtoverlay=ov5647"
UBUNTU_CONFIG = (
    "[all]\nkernel=vmlinuz\ncmdline=cmdline.txt\n\n[pi4]\nmax_framebuffers=2\n\n"
    "[all]\ndtparam=i2c_arm=on\ndtparam=spi=on\n\n[cm4]\ndtoverlay=dwc2,dr_mode=host\n\n[all]\n"
    "# Rosy motor bus on Raspberry Pi 5 GPIO12/GPIO13\ndtoverlay=uart4-pi5\n"
)


def _verifier():
    spec = importlib.util.spec_from_file_location("verify_mounted_image_overlay", VERIFIER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    return subprocess.run([BASH, "-c", 'cygpath -u "$1"', "_", str(path)],
                          capture_output=True, text=True, check=True).stdout.strip()


def _image(tmp_path: Path, config: str) -> Path:
    root = tmp_path / "image"
    (root / "boot/firmware").mkdir(parents=True)
    (root / "boot/firmware/config.txt").write_bytes(config.encode("utf-8"))
    return root


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([BASH, SCRIPT.as_posix(), "--image-root", _bash_path(root), *extra],
                          capture_output=True, text=True, check=False)


def test_the_image_enables_the_imu_bus_through_the_script():
    source = CUSTOMIZER.read_text(encoding="utf-8")
    call = f'bash "$BOOT_OVERLAY" --image-root "$ROOT" --overlay "{IMU}"'
    assert 'BOOT_OVERLAY="$(dirname "$0")/../robot/configure-boot-overlay-pi5.sh"' in source
    assert call in source
    # After the UART edit and before the image is accepted.
    assert source.index('bash "$UART_CONFIG" --image-root "$ROOT"') < source.index(call)
    assert source.index(call) < source.index("verify-mounted-image.py")
    assert f'IMU_OVERLAY = "{IMU}"' in VERIFIER.read_text(encoding="utf-8")


def test_the_probe_names_the_line_the_image_adds():
    probe = (ROOT / "deploy/robot/native/rosy-hw-probe.py").read_text(encoding="utf-8")
    assert f"config.txt {IMU}" in probe


@pytest.mark.skipif(BASH is None, reason="bash runs the overlay script")
def test_image_configures_ov5647_on_cam1_instead_of_auto_detection(tmp_path):
    root = _image(tmp_path, UBUNTU_CONFIG.replace(
        "dtparam=i2c_arm=on", "camera_auto_detect=1\ndtparam=i2c_arm=on"))

    completed = _run(root, "--overlay", CAMERA, "--disable-camera-auto-detect")
    assert completed.returncode == 0, completed.stderr
    config = (root / "boot/firmware/config.txt").read_text(encoding="utf-8")
    assert "camera_auto_detect=0" in config
    assert "camera_auto_detect=1" not in config
    assert _verifier().overlay_applies_to_pi5(config, CAMERA)
    assert _verifier().camera_configured_for_pi5(config)

    again = _run(root, "--overlay", CAMERA, "--disable-camera-auto-detect")
    assert again.returncode == 0, again.stderr
    assert (root / "boot/firmware/config.txt").read_text(encoding="utf-8") == config


def test_native_image_builder_requests_the_verified_camera_configuration():
    source = CUSTOMIZER.read_text(encoding="utf-8")
    assert 'bash "$BOOT_OVERLAY" --image-root "$ROOT" --overlay "dtoverlay=ov5647" \\' in source
    assert '--disable-camera-auto-detect' in source


@pytest.mark.skipif(BASH is None, reason="bash runs the overlay script")
def test_image_mode_appends_once_under_all(tmp_path):
    root = _image(tmp_path, UBUNTU_CONFIG)

    first = _run(root, "--overlay", IMU, "--comment", "Rosy IMU bus")
    assert first.returncode == 0, first.stderr
    assert f"PASS BOOT_OVERLAY added {IMU}" in first.stdout
    assert "REBOOT_REQUIRED" not in first.stdout
    config = (root / "boot/firmware/config.txt").read_bytes().decode("utf-8")
    assert config == UBUNTU_CONFIG + f"\n[all]\n# Rosy IMU bus\n{IMU}\n"
    assert _verifier().overlay_applies_to_pi5(config, IMU)

    again = _run(root, "--overlay", IMU)
    assert again.returncode == 0, again.stderr
    assert "is already configured" in again.stdout
    assert (root / "boot/firmware/config.txt").read_bytes().decode("utf-8") == config
    assert sorted(p.name for p in (root / "boot/firmware").iterdir()) == ["config.txt"]


@pytest.mark.skipif(BASH is None, reason="bash runs the overlay script")
@pytest.mark.parametrize(("config", "already"), [
    (f"[pi4]\n{IMU}\n", False),
    (f"[pi5]\n{IMU}\n", True),
    (f"{IMU}\n", True),
    (f"[all]\n#{IMU}\n", False),
    (f"[all]\r\n{IMU}\r\n", True),
])
def test_the_script_and_the_verifier_read_sections_alike(tmp_path, config, already):
    root = _image(tmp_path, config)
    completed = _run(root, "--overlay", IMU)
    assert completed.returncode == 0, completed.stderr
    assert ("is already configured" in completed.stdout) is already
    after = (root / "boot/firmware/config.txt").read_text(encoding="utf-8")
    assert _verifier().overlay_applies_to_pi5(after, IMU)


@pytest.mark.skipif(BASH is None, reason="bash runs the overlay script")
@pytest.mark.parametrize("overlay", ["", "dtoverlay=a b", "[all]", "gpio=4=op", "dtoverlay=x\n[pi4]"])
def test_the_script_refuses_anything_but_one_overlay_line(tmp_path, overlay):
    root = _image(tmp_path, UBUNTU_CONFIG)
    completed = _run(root, "--overlay", overlay)
    assert completed.returncode != 0
    assert (root / "boot/firmware/config.txt").read_bytes().decode("utf-8") == UBUNTU_CONFIG


@pytest.mark.skipif(BASH is None, reason="bash runs the overlay script")
def test_image_mode_refuses_the_running_system(tmp_path):
    completed = subprocess.run([BASH, SCRIPT.as_posix(), "--image-root", "/", "--overlay", IMU],
                               capture_output=True, text=True, check=False)
    assert completed.returncode != 0
    assert "must not be the running system" in completed.stderr
