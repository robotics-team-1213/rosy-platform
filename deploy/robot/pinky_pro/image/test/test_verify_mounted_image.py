import hashlib
import pytest
import importlib.util
import sys
from pathlib import Path

# Load verify-mounted-image.py dynamically
spec = importlib.util.spec_from_file_location(
    "verify_mounted_image",
    Path(__file__).resolve().parents[1] / "verify-mounted-image.py"
)
verify_mounted_image = importlib.util.module_from_spec(spec)
sys.modules["verify_mounted_image"] = verify_mounted_image
spec.loader.exec_module(verify_mounted_image)

def test_package_names(tmp_path):
    f = tmp_path / "pkgs.txt"
    f.write_text("pkg_a\n\n# comment\n  pkg_b  \n", encoding="utf-8")
    names = verify_mounted_image.package_names(f)
    assert names == {"pkg_a", "pkg_b"}

def test_inspect_passes_with_valid_image(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    release_id = "2026.01.01-001"
    release_dir = root / "opt/rosy/releases" / release_id
    release_dir.mkdir(parents=True)
    
    # Required paths
    paths = [
        "opt/ros/jazzy/setup.bash",
        f"opt/rosy/releases/{release_id}/install/setup.bash",
        "etc/rosy/motion_profiles.yaml",
        "etc/rosy/cyclonedds.xml",
        "opt/rosy/first-boot/rosy-first-boot.py",
        "opt/rosy/first-boot/rosy-new-device-setup.py",
        "opt/rosy/first-boot/rosy-rebind-board.py",
        "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem",
        "opt/rosy/native-runtime/native_release.py",
        "opt/rosy/native-runtime/recover-release.sh",
        "opt/rosy/native-runtime/signing.py",
        f"opt/rosy/releases/{release_id}/deploy/robot/native/native_release.py",
        f"opt/rosy/releases/{release_id}/deploy/robot/native/signing.py",
    ]
    for p in paths:
        path = root / p
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock", encoding="utf-8")
        
    # Required units
    for unit in verify_mounted_image.REQUIRED_UNITS:
        path = root / "etc/systemd/system" / unit
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock", encoding="utf-8")
        
    # Inventory
    (release_dir / "required-ros-packages.txt").write_text("pkg_a", encoding="utf-8")
    (release_dir / "rosy-packages.txt").write_text("pkg_a\npkg_b", encoding="utf-8")
    # D-225 2.2: the factory release is sealed in the image, not signed.
    (release_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (release_dir / "SHA256SUMS").write_text("mock", encoding="utf-8")

    # chrony ships enabled (CORE SRS §25 premise, verifier-checked).
    (root / "usr/sbin").mkdir(parents=True, exist_ok=True)
    (root / "usr/sbin/chronyd").write_text("mock", encoding="utf-8")
    # D-176: the fallback AP (NM shared mode) needs dnsmasq in the image.
    (root / "usr/sbin/dnsmasq").write_text("mock", encoding="utf-8")
    wants = root / "etc/systemd/system/multi-user.target.wants/chrony.service"
    wants.parent.mkdir(parents=True, exist_ok=True)
    wants.write_text("mock", encoding="utf-8")
    # D-192 US-003: the post-runtime indicator run ships enabled.
    (root / "etc/systemd/system/rosy-boot-status-ready.service").write_text("mock", encoding="utf-8")
    (wants.parent / "rosy-boot-status-ready.service").write_text("mock", encoding="utf-8")
    # D-192 US-004: the motor bus overlay and its alias rule.
    (root / "boot/firmware").mkdir(parents=True)
    (root / "boot/firmware/config.txt").write_text(
        "[all]\nenable_uart=1\ndtparam=i2c_arm=on\ndtparam=spi=on\ndtoverlay=uart4-pi5\n"
        # D-247 IMU bus and lamp overlay, D-288 OV5647 CAM1.
        "dtoverlay=i2c0-pi5,pins_0_1\ncamera_auto_detect=0\ndtoverlay=ov5647\ndtoverlay=rosy-ws281x\n",
        encoding="utf-8")
    # The LiDAR/motor UARTs carry no console; their gettys are masked.
    (root / "boot/firmware/cmdline.txt").write_text("console=ttyAMA10,115200 console=tty1 rootwait\n",
                                                    encoding="utf-8")
    for mask in verify_mounted_image.BUS_GETTY_MASKS:
        try:
            (root / mask).symlink_to("/dev/null")
        except OSError:
            pytest.skip("no symlink rights on this host; a getty mask must be a /dev/null symlink")
    (root / "etc/udev/rules.d").mkdir(parents=True)
    (root / "etc/udev/rules.d/99-rosy-motor.rules").write_text("mock", encoding="utf-8")
    # D-192 US-005: hardware units installed (not enabled) and the LiDAR driver.
    for unit in verify_mounted_image.HARDWARE_UNITS:
        (root / "etc/systemd/system" / unit).write_text("mock", encoding="utf-8")
    (release_dir / "rosy-packages.txt").write_text("pkg_a\npkg_b\nsllidar_ros2", encoding="utf-8")
    for relative in verify_mounted_image.SLLIDAR_FILES:
        (release_dir / "install" / relative).parent.mkdir(parents=True, exist_ok=True)
        (release_dir / "install" / relative).write_text("mock", encoding="utf-8")
    # D-190: the boot display ships enabled, with its udev rule and apt libraries.
    (root / "etc/systemd/system" / verify_mounted_image.DISPLAY_UNIT).write_text("mock", encoding="utf-8")
    (wants.parent / verify_mounted_image.DISPLAY_UNIT).write_text("mock", encoding="utf-8")
    (root / verify_mounted_image.DISPLAY_UDEV_RULE).write_text("mock", encoding="utf-8")
    (root / "var/lib/dpkg").mkdir(parents=True)
    (root / "var/lib/dpkg/status").write_text("".join(
        f"Package: {name}\nStatus: install ok installed\n\n"
        for name in verify_mounted_image.DISPLAY_APT_PACKAGES), encoding="utf-8")
    _add_lamp_and_camera(root)
    _add_login_probe_and_defaults(root, release_dir)

    findings = verify_mounted_image.inspect(root, release_id)
    assert not findings, findings


def _add_login_probe_and_defaults(root, release_dir):
    """D-193 login code, D-247 hardware probe/test units and token-free CORE defaults."""
    system = root / "etc/systemd/system"
    wants = system / "multi-user.target.wants"
    for unit in (verify_mounted_image.LOGIN_UNIT, *verify_mounted_image.HW_PROBE_UNITS,
                 verify_mounted_image.HW_TEST_SERVICE, verify_mounted_image.HW_TEST_PATH):
        (system / unit).write_text("mock", encoding="utf-8")
    for unit in (verify_mounted_image.LOGIN_UNIT, *verify_mounted_image.HW_PROBE_UNITS,
                 verify_mounted_image.HW_TEST_PATH):
        (wants / unit).write_text("mock", encoding="utf-8")
    for relative in (verify_mounted_image.LOGIN_ISSUE_LINK, verify_mounted_image.LOGIN_COMMAND,
                     verify_mounted_image.HW_PROBE_COMMAND):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("mock", encoding="utf-8")
    defaults = release_dir / verify_mounted_image.CORE_DEFAULTS
    defaults.parent.mkdir(parents=True, exist_ok=True)
    defaults.write_text("auth: {}\n", encoding="utf-8")


def _add_lamp_and_camera(root):
    """D-247 lamp driver and D-288 camera payload, as customize-rootfs.sh installs them."""
    kernel = "6.8.0-1010-raspi"
    (root / verify_mounted_image.LAMP_DTBO).parent.mkdir(parents=True, exist_ok=True)
    (root / verify_mounted_image.LAMP_DTBO).write_bytes(b"dtbo")
    record = root / verify_mounted_image.LAMP_KERNEL_RECORD
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(kernel + "\n", encoding="utf-8")
    modules = root / "lib/modules" / kernel
    (modules / "kernel").mkdir(parents=True)
    (modules / "extra").mkdir(parents=True)
    (modules / "extra/rp1_ws281x_pwm.ko").write_bytes(b"ELF\0vermagic=" + kernel.encode() + b" SMP preempt\0")
    (modules / "modules.alias").write_text("alias of:N*T*Craspberrypi,rp1-ws281x-pwm rp1_ws281x_pwm\n",
                                           encoding="utf-8")
    (root / verify_mounted_image.LAMP_UDEV_RULE).write_text("mock", encoding="utf-8")
    modprobe = root / verify_mounted_image.LAMP_MODPROBE
    modprobe.parent.mkdir(parents=True, exist_ok=True)
    modprobe.write_text(verify_mounted_image.LAMP_OPTIONS + "\n", encoding="utf-8")
    status = root / "var/lib/dpkg/status"
    status.write_text(status.read_text(encoding="utf-8") + "".join(
        f"Package: {name}\nStatus: hold ok installed\n\n"
        for name in (f"linux-image-{kernel}", f"linux-modules-{kernel}")), encoding="utf-8")
    source = root / verify_mounted_image.CAMERA_SOURCE_RECORD
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(verify_mounted_image.CAMERA_SOURCE_LOCK.read_bytes())
    python_lock = verify_mounted_image.CAMERA_SOURCE_LOCK.with_name("camera-python-requirements.txt")
    (root / verify_mounted_image.CAMERA_PYTHON_RECORD).write_text(
        hashlib.sha256(python_lock.read_bytes()).hexdigest(), encoding="utf-8")
    (root / "usr/local/bin").mkdir(parents=True, exist_ok=True)
    for command in ("rpicam-hello", "rpicam-still"):
        (root / "usr/local/bin" / command).write_text("mock", encoding="utf-8")
    lib = root / "usr/local/lib/aarch64-linux-gnu"
    (lib / "libcamera").mkdir(parents=True)
    for name in ("libpisp.so.1", "libcamera.so.0.4", "libcamera/ipa_rpi_pisp.so"):
        (lib / name).write_text("mock", encoding="utf-8")
    for package in ("libcamera", "picamera2"):
        (root / "usr/local/lib/python3.12/dist-packages" / package).mkdir(parents=True)

def test_inspect_fails_if_docker_present(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    release_id = "2026.01.01-001"
    release_dir = root / "opt/rosy/releases" / release_id
    release_dir.mkdir(parents=True)
    
    # Required paths
    paths = [
        "opt/ros/jazzy/setup.bash",
        f"opt/rosy/releases/{release_id}/install/setup.bash",
        "etc/rosy/motion_profiles.yaml",
        "etc/rosy/cyclonedds.xml",
        "opt/rosy/first-boot/rosy-first-boot.py",
        "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem",
        "opt/rosy/native-runtime/native_release.py",
        "opt/rosy/native-runtime/recover-release.sh",
        "opt/rosy/native-runtime/signing.py",
        f"opt/rosy/releases/{release_id}/deploy/robot/native/native_release.py",
        f"opt/rosy/releases/{release_id}/deploy/robot/native/signing.py",
    ]
    for p in paths:
        path = root / p
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock", encoding="utf-8")
        
    for unit in verify_mounted_image.REQUIRED_UNITS:
        path = root / "etc/systemd/system" / unit
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock", encoding="utf-8")
        
    (release_dir / "required-ros-packages.txt").write_text("", encoding="utf-8")
    (release_dir / "rosy-packages.txt").write_text("", encoding="utf-8")
    
    docker = root / "usr/bin/docker"
    docker.parent.mkdir(parents=True, exist_ok=True)
    docker.write_text("bin", encoding="utf-8")
    
    findings = verify_mounted_image.inspect(root, release_id)
    assert any("docker must not be installed" in f for f in findings)


def test_inspect_requires_both_installed_native_runtime_copies(tmp_path):
    # D-174 F1/F5: an image without the runtime (or without its helper) must not pass.
    root = tmp_path / "root"
    release_id = "2026.01.01-001"
    (root / "opt/rosy/releases" / release_id).mkdir(parents=True)

    findings = verify_mounted_image.inspect(root, release_id)
    assert any("rosy-new-device-setup.py" in finding for finding in findings)
    assert any("rosy-new-device-setup.service" in finding for finding in findings)

    missing = {Path(f.split(": ", 1)[1]).as_posix() for f in findings
               if f.startswith("missing required image path")}
    assert {
        "opt/rosy/native-runtime/native_release.py",
        "opt/rosy/native-runtime/recover-release.sh",
        "opt/rosy/native-runtime/signing.py",
        f"opt/rosy/releases/{release_id}/deploy/robot/native/native_release.py",
        f"opt/rosy/releases/{release_id}/deploy/robot/native/signing.py",
    } <= missing


def test_inspect_rejects_bytecode_inside_the_signed_release(tmp_path):
    root = tmp_path / "root"
    release_id = "2026.01.01-001"
    cache = root / "opt/rosy/releases" / release_id / "deploy/robot/native/__pycache__"
    cache.mkdir(parents=True)

    findings = verify_mounted_image.inspect(root, release_id)

    assert (f"bytecode cache in native runtime: opt/rosy/releases/{release_id}"
            "/deploy/robot/native/__pycache__") in findings


def test_colcon_install_bytecode_is_part_of_the_payload(tmp_path):
    # Release 003 build: colcon installs site-packages/*/__pycache__ with the payload.
    root = tmp_path / "root"
    release_id = "2026.01.01-001"
    (root / "opt/rosy/releases" / release_id / "install/lib/python3.12/site-packages/core/__pycache__").mkdir(parents=True)

    findings = verify_mounted_image.inspect(root, release_id)

    assert not [f for f in findings if "bytecode" in f]
