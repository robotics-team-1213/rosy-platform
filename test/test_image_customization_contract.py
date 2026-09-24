"""Contracts for installing native ROSY into the mounted Ubuntu Pi image."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "deploy" / "image"
CUSTOMIZER = IMAGE / "customize-rootfs.sh"
VERIFY = IMAGE / "verify-mounted-image.py"


def test_ros_apt_source_package_is_exactly_pinned():
    lock = yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text(encoding="utf-8"))
    ros = lock["ros"]
    assert ros["apt_source_version"] == "1.2.0"
    assert ros["apt_source_url"].endswith("/1.2.0/ros2-apt-source_1.2.0.noble_all.deb")
    assert ros["apt_source_sha256"] == "0804d9b13db770eb87019be414cd78378835228ad5fa801fc88758596dd8f7e5"


def test_customizer_installs_native_ros_and_never_product_docker():
    source = CUSTOMIZER.read_text(encoding="utf-8")
    build = (IMAGE / "build-image.sh").read_text(encoding="utf-8")
    payload = (IMAGE / "build-native-payload.sh").read_text(encoding="utf-8")

    assert "ros-jazzy-ros-base" in source
    assert "ros-jazzy-rmw-cyclonedds-cpp" in source
    assert "rosdep install" in source
    assert "chroot" in source
    assert "systemctl --root" in source
    assert "docker" not in source.lower()
    assert "--source-tree" in build and "--lock" in build
    assert "motion_profiles.yaml" in payload and "cyclonedds.xml" in payload


def test_customizer_materializes_all_locked_ubuntu_apt_sources_before_update():
    lock = yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text(encoding="utf-8"))
    source = CUSTOMIZER.read_text(encoding="utf-8")

    assert any("noble-updates" in item for item in lock["os"]["apt_sources"])
    assert 'lock["os"]["apt_sources"]' in source
    assert "rosy-ubuntu.list" in source
    assert source.index("rosy-ubuntu.list") < source.index('chroot "$ROOT" apt-get update')


def test_customizer_installs_only_required_product_package_dependency_closure():
    source = CUSTOMIZER.read_text(encoding="utf-8")

    assert "resolve-required-source-paths.py" in source
    assert "ROSDEP_SOURCE_PATHS" in source
    assert '--source-root "$ROOT/tmp/rosy-src"' in source
    assert "--chroot-prefix /tmp/rosy-src" in source
    assert '"$ROOT/tmp/rosy-src/src"' not in source
    assert 'rosdep install --from-paths "${ROSDEP_SOURCE_PATHS[@]}"' in source
    assert "rosdep install --from-paths /tmp/rosy-src" not in source
    assert 'chroot "$ROOT" apt-get clean' in source


def test_customizer_installs_wiringpi_runtime_from_the_verified_lock():
    source = CUSTOMIZER.read_text(encoding="utf-8")

    for fragment in (
        "hardware_dependencies", "wiringpi_url", "wiringpi_sha256",
        "sha256sum", "dpkg -i /tmp/wiringpi-arm64.deb",
    ):
        assert fragment in source
    assert source.index("sha256sum") < source.index("dpkg -i /tmp/wiringpi-arm64.deb")


def test_customizer_installs_and_enables_chrony():
    """CORE SRS §25: UTC ISO 8601 타임스탬프는 동기된 시계를 전제로 한다."""
    source = CUSTOMIZER.read_text(encoding="utf-8")
    verifier = VERIFY.read_text(encoding="utf-8")

    assert " chrony" in source  # apt install list
    assert "chrony.service" in source
    assert source.index("chrony.service") > source.index("enable")  # enabled, not just installed
    assert "chronyd" in verifier  # the mounted-image check exists too


def _valid_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    release = root / "opt/rosy/releases/2026.09.22-001"
    for path in (
        root / "opt/ros/jazzy",
        release / "install",
        root / "etc/systemd/system",
        root / "etc/rosy",
        root / "etc/rosy/trusted-release-keys",
        root / "opt/rosy/first-boot",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (root / "opt/ros/jazzy/setup.bash").write_text("# fixture\n", encoding="utf-8")
    (release / "install/setup.bash").write_text("# fixture\n", encoding="utf-8")
    (root / "opt/rosy/first-boot/rosy-first-boot.py").write_text("# fixture\n", encoding="utf-8")
    for runtime, names in (
        (root / "opt/rosy/native-runtime", ("native_release.py", "recover-release.sh", "signing.py")),
        (release / "deploy/robot/native", ("native_release.py", "signing.py")),
    ):
        runtime.mkdir(parents=True, exist_ok=True)
        for name in names:
            (runtime / name).write_text("# fixture\n", encoding="utf-8")
    (release / "required-ros-packages.txt").write_text(
        "# Mandatory product packages in every image.\ncore\ncontrol\n",
        encoding="utf-8",
    )
    (release / "rosy-packages.txt").write_text("control\ncore\n", encoding="utf-8")
    (root / "etc/rosy/motion_profiles.yaml").write_text("profiles: {}\n", encoding="utf-8")
    (root / "etc/rosy/cyclonedds.xml").write_text("<CycloneDDS/>\n", encoding="utf-8")
    (root / "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem").write_text(
        "-----BEGIN PUBLIC KEY-----\nfixture\n-----END PUBLIC KEY-----\n",
        encoding="utf-8",
    )
    for unit in (
        "rosy-first-boot.service",
        "rosy-release-recover.service",
        "rosy-sd-provision.service",
        "rosy-core.service",
        "rosy-runtime.target",
    ):
        (root / "etc/systemd/system" / unit).write_text("[Unit]\n", encoding="utf-8")
    # chrony ships enabled (CORE SRS §25 premise, verifier-checked).
    (root / "usr/sbin").mkdir(parents=True, exist_ok=True)
    (root / "usr/sbin/chronyd").write_text("# fixture\n", encoding="utf-8")
    (root / "usr/sbin/dnsmasq").write_text("# fixture\n", encoding="utf-8")
    wants = root / "etc/systemd/system/multi-user.target.wants/chrony.service"
    wants.parent.mkdir(parents=True, exist_ok=True)
    wants.write_text("[Unit]\n", encoding="utf-8")
    # D-192 US-003: the post-runtime indicator run ships enabled.
    (root / "etc/systemd/system/rosy-boot-status-ready.service").write_text("[Unit]\n", encoding="utf-8")
    (wants.parent / "rosy-boot-status-ready.service").write_text("[Unit]\n", encoding="utf-8")
    # D-192 US-004: the motor bus overlay and its alias rule.
    (root / "boot/firmware").mkdir(parents=True, exist_ok=True)
    (root / "boot/firmware/config.txt").write_text(
        "[all]\nkernel=vmlinuz\nenable_uart=1\ndtparam=i2c_arm=on\ndtparam=spi=on\n\n[all]\n# Rosy motor bus\n"
        "dtoverlay=uart4-pi5\n", encoding="utf-8")
    # The bus UARTs carry no console (configure-uart-pi5.sh edits the Ubuntu line).
    (root / "boot/firmware/cmdline.txt").write_text(
        "console=ttyAMA10,115200 multipath=off dwc_otg.lpm_enable=0 console=tty1 root=LABEL=writable "
        "rootfstype=ext4 rootwait fixrtc\n",
        encoding="utf-8")
    for tty in ("ttyAMA0", "ttyAMA4"):
        _link(root / f"etc/systemd/system/serial-getty@{tty}.service", "/dev/null")
    (root / "etc/udev/rules.d").mkdir(parents=True, exist_ok=True)
    (root / "etc/udev/rules.d/99-rosy-motor.rules").write_text(
        'KERNEL=="ttyAMA4", SYMLINK+="rosy-motor"\n', encoding="utf-8")
    # D-192 US-005: hardware units installed (not enabled) and the LiDAR driver.
    for unit in ("rosy-io.service", "rosy-navigation.service"):
        (root / "etc/systemd/system" / unit).write_text("[Unit]\n", encoding="utf-8")
    (release / "rosy-packages.txt").write_text("control\ncore\nsllidar_ros2\n", encoding="utf-8")
    for relative in ("lib/sllidar_ros2/sllidar_node", "share/sllidar_ros2/launch/sllidar_c1_launch.py"):
        (release / "install" / relative).parent.mkdir(parents=True, exist_ok=True)
        (release / "install" / relative).write_text("# fixture\n", encoding="utf-8")
    # D-190: the boot display ships enabled, with its udev rule and apt libraries.
    (root / "etc/systemd/system/rosy-boot-display.service").write_text("[Unit]\n", encoding="utf-8")
    (wants.parent / "rosy-boot-display.service").write_text("[Unit]\n", encoding="utf-8")
    (root / "etc/udev/rules.d/99-rosy-display.rules").write_text('KERNEL=="spidev0.0"\n', encoding="utf-8")
    (root / "var/lib/dpkg").mkdir(parents=True, exist_ok=True)
    (root / "var/lib/dpkg/status").write_text("".join(
        f"Package: {name}\nStatus: install ok installed\nVersion: 1\n\n"
        for name in ("python3-spidev", "python3-rpi-lgpio", "python3-numpy", "python3-pil",
                     "fonts-dejavu-core")), encoding="utf-8")
    # D-193: the login-code issuer (enabled), its banner link and command, and
    # CORE defaults without tokens.
    (root / "etc/systemd/system/rosy-login-code.service").write_text("[Unit]\n", encoding="utf-8")
    (wants.parent / "rosy-login-code.service").write_text("[Unit]\n", encoding="utf-8")
    _link(root / "etc/issue.d/60-rosy-login.issue", "/run/rosy-boot/login.issue")
    _link(root / "usr/local/sbin/rosy-login-code", "/opt/rosy/native-runtime/rosy-login-code")
    defaults = release / "install/share/core/config/rosy_default.yaml"
    defaults.parent.mkdir(parents=True, exist_ok=True)
    defaults.write_text((ROOT / "src/core/core/config/rosy_default.yaml").read_text(encoding="utf-8"),
                        encoding="utf-8")
    return root


def _link(path: Path, target: str) -> None:
    """A symlink where the host allows one; a placeholder file on Windows without the privilege."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):  # _valid_root may be built twice in one tmp_path
        path.unlink()
    try:
        path.symlink_to(target)
    except OSError:
        path.write_text("# fixture link\n", encoding="utf-8")


def _verify(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFY), "--root", str(root), "--release-id", "2026.09.22-001"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_mounted_image_verifier_accepts_native_core_only_layout(tmp_path):
    root = _valid_root(tmp_path)
    if not _bus_masks_are_symlinks(root):
        pytest.skip("no symlink rights on this host; the verifier accepts only a real /dev/null mask")
    completed = _verify(root)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["ok"] is True


def test_mounted_image_verifier_rejects_tokens_in_core_defaults(tmp_path):
    # D-193 7: a payload whose packaged defaults carry any token fails the build.
    root = _valid_root(tmp_path)
    defaults = root / "opt/rosy/releases/2026.09.22-001/install/share/core/config/rosy_default.yaml"
    defaults.write_text("auth:\n  tokens:\n    - token: rosy-dev-" + "admin\n      role: administrator\n",
                        encoding="utf-8")
    completed = _verify(root)
    assert completed.returncode != 0
    assert "CORE defaults carry API tokens" in completed.stderr

    defaults.write_text("auth:\n  tokens:\n    - sha256: " + "0" * 64 + "\n      role: viewer\n",
                        encoding="utf-8")
    assert "CORE defaults carry API tokens" in _verify(root).stderr
    defaults.unlink()
    assert "missing CORE defaults" in _verify(root).stderr


def test_mounted_image_verifier_requires_the_login_code_issuer(tmp_path):
    root = _valid_root(tmp_path)
    (root / "etc/systemd/system/multi-user.target.wants/rosy-login-code.service").unlink()
    (root / "etc/issue.d/60-rosy-login.issue").unlink()
    (root / "usr/local/sbin/rosy-login-code").unlink()
    completed = _verify(root)
    assert completed.returncode != 0
    for finding in ("rosy-login-code.service is not enabled", "60-rosy-login.issue",
                    "missing login code command"):
        assert finding in completed.stderr, finding
    (root / "etc/systemd/system/rosy-login-code.service").unlink()
    assert "missing systemd unit: rosy-login-code.service" in _verify(root).stderr


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need a privilege on Windows")
def test_mounted_image_verifier_rejects_a_banner_link_to_elsewhere(tmp_path):
    root = _valid_root(tmp_path)
    link = root / "etc/issue.d/60-rosy-login.issue"
    link.unlink()
    link.symlink_to("/run/rosy/login.issue")
    assert "60-rosy-login.issue" in _verify(root).stderr


def test_image_installs_enables_and_probes_the_login_code_issuer():
    source = CUSTOMIZER.read_text(encoding="utf-8")
    enable = source[source.index("systemctl --root"):source.index("mkdir -p \"$ROOT/etc/issue.d\"")]
    assert "rosy-login-code.service" in enable
    assert 'ln -sfn /run/rosy-boot/login.issue "$ROOT/etc/issue.d/60-rosy-login.issue"' in source
    assert 'ln -sfn /opt/rosy/native-runtime/rosy-login-code "$ROOT/usr/local/sbin/rosy-login-code"' in source
    loop = source[source.index("for entrypoint in rosy-boot-status.py"):]
    assert "rosy-login-code.py; do" in loop[:loop.index("done")]
    payload = (ROOT / "deploy/image/build-native-payload.sh").read_text(encoding="utf-8")
    assert 'cp "$NATIVE_RUNTIME_SOURCE/rosy-login-code.service" "$OVERLAY/etc/systemd/system/"' in payload
    wrapper = (ROOT / "deploy/robot/native/rosy-login-code").read_text(encoding="utf-8")
    assert 'exec /usr/bin/python3 -I -B "$SCRIPT_DIR/rosy-login-code.py" "$@"' in wrapper


def test_mounted_image_verifier_rejects_missing_required_package(tmp_path):
    root = _valid_root(tmp_path)
    release = root / "opt/rosy/releases/2026.09.22-001"
    (release / "rosy-packages.txt").write_text("core\n", encoding="utf-8")
    completed = _verify(root)
    assert completed.returncode != 0
    assert "control" in completed.stderr


def test_mounted_image_verifier_rejects_product_docker_or_device_secrets(tmp_path):
    root = _valid_root(tmp_path)
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/docker").write_text("fixture\n", encoding="utf-8")
    (root / "etc/rosy/runtime.env").write_text("ROSY_NAMESPACE=rosy_01\n", encoding="utf-8")
    connections = root / "etc/NetworkManager/system-connections"
    connections.mkdir(parents=True)
    (connections / "secret.nmconnection").write_text(
        "psk=" + "secret\n", encoding="utf-8"
    )
    completed = _verify(root)
    assert completed.returncode != 0
    assert "docker" in completed.stderr.lower()
    assert "device-neutral" in completed.stderr.lower()


def test_mounted_image_verifier_rejects_missing_or_disabled_chrony(tmp_path):
    """CORE SRS §25: 타임스탬프 상관의 전제인 chrony 가 빠지거나 꺼진 이미지."""
    disabled = _valid_root(tmp_path)
    (disabled / "etc/systemd/system/multi-user.target.wants/chrony.service").unlink()
    completed = _verify(disabled)
    assert completed.returncode != 0
    assert "chrony" in completed.stderr.lower()

    absent = _valid_root(tmp_path)
    (absent / "usr/sbin/chronyd").unlink()
    completed = _verify(absent)
    assert completed.returncode != 0
    assert "chrony" in completed.stderr.lower()


def test_mounted_image_verifier_rejects_a_missing_or_disabled_ready_run(tmp_path):
    # D-192 US-003: without it CORE_READY waits for the 30 s timer.
    disabled = _valid_root(tmp_path / "disabled")
    (disabled / "etc/systemd/system/multi-user.target.wants/rosy-boot-status-ready.service").unlink()
    completed = _verify(disabled)
    assert completed.returncode != 0
    assert "rosy-boot-status-ready.service is not enabled" in completed.stderr

    absent = _valid_root(tmp_path / "absent")
    (absent / "etc/systemd/system/rosy-boot-status-ready.service").unlink()
    completed = _verify(absent)
    assert completed.returncode != 0
    assert "missing systemd unit: rosy-boot-status-ready.service" in completed.stderr


def test_mounted_image_verifier_requires_the_uart4_motor_bus(tmp_path):
    # D-192 US-004: no overlay, no /dev/ttyAMA4, no /dev/rosy-motor.
    pi4_only = _valid_root(tmp_path / "pi4")
    (pi4_only / "boot/firmware/config.txt").write_text("[pi4]\ndtoverlay=uart4-pi5\n", encoding="utf-8")
    completed = _verify(pi4_only)
    assert completed.returncode != 0
    assert "does not enable dtoverlay=uart4-pi5 for the Pi 5" in completed.stderr

    no_config = _valid_root(tmp_path / "noconfig")
    (no_config / "boot/firmware/config.txt").unlink()
    completed = _verify(no_config)
    assert completed.returncode != 0
    assert "missing boot configuration: boot/firmware/config.txt" in completed.stderr

    no_rule = _valid_root(tmp_path / "norule")
    (no_rule / "etc/udev/rules.d/99-rosy-motor.rules").unlink()
    completed = _verify(no_rule)
    assert completed.returncode != 0
    assert "missing motor udev rule" in completed.stderr


def test_mounted_image_verifier_requires_the_base_uart_and_i2c_settings(tmp_path):
    # D-192 review: the LiDAR UART (enable_uart=1 -> /dev/ttyAMA0) and the ADC
    # bus (dtparam=i2c_arm=on -> /dev/i2c-1) come from the Ubuntu base image.
    for line in ("enable_uart=1", "dtparam=i2c_arm=on"):
        root = _valid_root(tmp_path / line.replace("=", "_"))
        config = root / "boot/firmware/config.txt"
        config.write_text(config.read_text(encoding="utf-8").replace(line, "#" + line), encoding="utf-8")
        completed = _verify(root)
        assert completed.returncode != 0
        assert f"boot/firmware/config.txt lost {line} for the Pi 5" in completed.stderr

    pi4_only = _valid_root(tmp_path / "pi4")
    config = pi4_only / "boot/firmware/config.txt"
    config.write_text("[pi4]\nenable_uart=1\n" + config.read_text(encoding="utf-8").replace("enable_uart=1\n", ""),
                      encoding="utf-8")
    completed = _verify(pi4_only)
    assert completed.returncode != 0
    assert "lost enable_uart=1" in completed.stderr


@pytest.mark.parametrize("console", ["console=serial0,115200", "console=ttyAMA0,115200",
                                     "console=ttyAMA4,115200", "console=ttyAMA0"])
def test_mounted_image_verifier_rejects_a_console_on_a_robot_bus_uart(tmp_path, console):
    # rosy-pinky-e4us 2026-09-24: Ubuntu's console=serial0,115200 is ttyAMA0 with
    # enable_uart=1; the kernel console and agetty held the RPLIDAR C1 port.
    root = _valid_root(tmp_path)
    cmdline = root / "boot/firmware/cmdline.txt"
    cmdline.write_text(f"{console} " + cmdline.read_text(encoding="utf-8"), encoding="utf-8")
    completed = _verify(root)
    assert completed.returncode != 0
    assert f"routes a console to a robot bus UART: {console}" in completed.stderr


def _bus_masks_are_symlinks(root: Path) -> bool:
    return all((root / f"etc/systemd/system/serial-getty@{tty}.service").is_symlink()
               for tty in ("ttyAMA0", "ttyAMA4"))


def test_mounted_image_verifier_accepts_the_screen_and_debug_uart_consoles(tmp_path):
    root = _valid_root(tmp_path)
    if not _bus_masks_are_symlinks(root):
        pytest.skip("no symlink rights on this host; the verifier accepts only a real /dev/null mask")
    completed = _verify(root)
    assert "cmdline.txt" not in completed.stderr
    assert "serial getty" not in completed.stderr


def test_mounted_image_verifier_requires_the_recovery_console(tmp_path):
    root = _valid_root(tmp_path)
    cmdline = root / "boot/firmware/cmdline.txt"
    cmdline.write_text(cmdline.read_text(encoding="utf-8").replace("console=ttyAMA10,115200 ", ""),
                       encoding="utf-8")
    completed = _verify(root)
    assert completed.returncode != 0
    assert "no recovery console on the debug UART (console=ttyAMA10)" in completed.stderr


def test_mounted_image_verifier_requires_cmdline_and_masked_bus_gettys(tmp_path):
    no_cmdline = _valid_root(tmp_path / "nocmdline")
    (no_cmdline / "boot/firmware/cmdline.txt").unlink()
    assert "missing kernel command line: boot/firmware/cmdline.txt" in _verify(no_cmdline).stderr

    for tty in ("ttyAMA0", "ttyAMA4"):
        mask = f"etc/systemd/system/serial-getty@{tty}.service"
        missing = _valid_root(tmp_path / tty)
        (missing / mask).unlink()
        completed = _verify(missing)
        assert completed.returncode != 0
        assert f"serial getty is not masked: {mask}" in completed.stderr

        # A regular file is not a mask, whatever it contains.
        regular = _valid_root(tmp_path / f"{tty}-file")
        (regular / mask).unlink()
        (regular / mask).write_text("/dev/null\n", encoding="utf-8")
        assert f"serial getty is not masked: {mask}" in _verify(regular).stderr

        elsewhere = _valid_root(tmp_path / f"{tty}-link")
        (elsewhere / mask).unlink()
        try:
            (elsewhere / mask).symlink_to("/lib/systemd/system/serial-getty@.service")
        except OSError:
            continue  # no symlink rights: the two cases above still hold
        assert f"serial getty is not masked: {mask}" in _verify(elsewhere).stderr


def test_customizer_executes_native_entrypoints_inside_the_image():
    # D-174 F5: file-existence checks passed an image whose recovery gate could
    # not import its helper. The customizer must run the installed copies.
    source = CUSTOMIZER.read_text(encoding="utf-8")

    probe = "rosy-native-probe"
    assert probe in source
    for runtime in ("/opt/rosy/native-runtime/native_release.py",
                    '/opt/rosy/releases/$RELEASE_ID/deploy/robot/native/native_release.py'):
        assert f'chroot "$ROOT" python3 -B {runtime}' in source
    assert 'chroot "$ROOT" python3 -B /opt/rosy/first-boot/rosy-first-boot.py --help' in source
    assert source.index("rosy-native-probe") < source.index("verify-mounted-image.py")


def test_image_enables_and_probes_the_d176_boot_settings_and_fallback_ap():
    # D-176: the settings file and the fallback AP only exist on a device if the
    # image carries, enables and can import them where it installs them.
    source = CUSTOMIZER.read_text(encoding="utf-8")
    enable = source[source.index("systemctl --root"):source.index("mkdir -p \"$ROOT/etc/issue.d\"")]
    for unit in ("rosy-config.service", "rosy-network.service"):
        assert unit in enable, unit
    assert "rosy-config-apply.py rosy-network.py" in source
    assert 'chroot "$ROOT" python3 -B "/opt/rosy/native-runtime/$entrypoint" --help' in source

    payload = (ROOT / "deploy/image/build-native-payload.sh").read_text(encoding="utf-8")
    for line in ('cp "$NATIVE_RUNTIME_SOURCE/rosy-config.service" "$OVERLAY/etc/systemd/system/"',
                 'cp "$NATIVE_RUNTIME_SOURCE/rosy-network.service" "$OVERLAY/etc/systemd/system/"',
                 'cp "$NATIVE_RUNTIME_SOURCE/defaults.yaml" "$OVERLAY/etc/rosy/defaults.yaml"'):
        assert line in payload, line


def test_image_puts_rosy_diag_on_path():
    # D-175 L2: an operator on the console types `rosy-diag collect`.
    source = CUSTOMIZER.read_text(encoding="utf-8")
    assert 'ln -sfn /opt/rosy/native-runtime/rosy-diag "$ROOT/usr/local/bin/rosy-diag"' in source


def test_the_image_carries_dnsmasq_for_the_fallback_ap(tmp_path):
    # D-176 review: dnsmasq-base is only a Recommends of network-manager, and
    # the customizer installs with --no-install-recommends.
    assert "dnsmasq-base" in CUSTOMIZER.read_text(encoding="utf-8")
    root = _valid_root(tmp_path)
    (root / "usr/sbin/dnsmasq").unlink()

    completed = _verify(root)

    assert completed.returncode != 0
    assert "dnsmasq" in completed.stdout + completed.stderr


# --- D-189: CORE's Python runtime is a hash-locked input, imported in-image ---

REQUIREMENTS = IMAGE / "device-python-requirements.txt"
PROBE = IMAGE / "probe-core-runtime.py"
# The set that was hotfixed onto the first 2026.09.23-005 card and runs on the
# WSL sim box. Changing one of these is a runtime change, not a refresh.
TOP_LEVEL_PINS = {
    "pydantic": "2.13.5", "pydantic-core": "2.46.5", "fastapi": "0.141.1",
    "starlette": "1.6.0", "uvicorn": "0.52.4", "websockets": "17.1",
}
# What fastapi 0.141.1, starlette 1.6.0, uvicorn 0.52.4 and pydantic 2.13.5
# require on CPython 3.12 (no extras), resolved 2026-09-24.
CLOSURE = {"annotated-doc", "annotated-types", "anyio", "click", "h11", "idna",
           "typing-extensions", "typing-inspection"}
# D-192: the rosy-io set in the same file (bringup's DYNAMIXEL driver), so the
# D-189 image/release runtime check covers it. pyserial is its only dependency.
IO_PINS = {"dynamixel-sdk": "3.8.4", "pyserial": "3.5"}
# Distributions with compiled wheels need one hash per platform.
PLATFORM_WHEELS = {"pydantic-core", "websockets"}


def _requirements() -> dict[str, tuple[str, list[str]]]:
    entries: dict[str, tuple[str, list[str]]] = {}
    text = REQUIREMENTS.read_text(encoding="utf-8").replace("\\\n", " ")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirement, *options = line.split()
        name, version = requirement.split("==")
        hashes = [option.split(":", 1)[1] for option in options if option.startswith("--hash=sha256:")]
        assert len(hashes) == len(options), line
        entries[name] = (version, hashes)
    return entries


def _probe_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("probe_core_runtime", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_core_python_runtime_is_pinned_and_hash_locked_for_both_platforms():
    entries = _requirements()

    assert set(entries) == set(TOP_LEVEL_PINS) | CLOSURE | set(IO_PINS)
    for name, version in {**TOP_LEVEL_PINS, **IO_PINS}.items():
        assert entries[name][0] == version, name
    for name, (version, hashes) in entries.items():
        assert version and all(c.isdigit() or c == "." for c in version), name
        assert hashes and all(len(h) == 64 and set(h) <= set("0123456789abcdef") for h in hashes), name
        assert len(set(hashes)) == len(hashes), name
        assert len(hashes) == (2 if name in PLATFORM_WHEELS else 1), name


def test_the_input_lock_pins_the_requirements_file_bytes():
    import hashlib

    lock = yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text(encoding="utf-8"))
    runtime = lock["python_runtime"]
    data = REQUIREMENTS.read_bytes()

    assert runtime["requirements"] == REQUIREMENTS.name
    assert b"\r" not in data, "the lock pins LF bytes (.gitattributes eol=lf)"
    assert hashlib.sha256(data).hexdigest() == runtime["requirements_sha256"]
    assert runtime["pydantic_major"] == 2
    assert runtime["verified"] is True
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "deploy/image/device-python-requirements.txt text eol=lf" in attributes


def test_customizer_installs_the_locked_runtime_after_rosdep():
    source = CUSTOMIZER.read_text(encoding="utf-8")

    assert "python3-pip" in source[source.index("apt-get install -y"):source.index("rosdep init")]
    assert "lock_value python_runtime requirements_sha256" in source
    assert "CORE Python requirements do not match inputs.lock.yaml" in source
    install = source.index('chroot "$ROOT" python3 -m pip install')
    command = source[install:source.index("|| fail", install)]
    for flag in ("--require-hashes", "--no-deps", "--only-binary=:all:", "--ignore-installed",
                 "--break-system-packages", "-r /tmp/rosy-core-probe/device-python-requirements.txt"):
        assert flag in command, flag
    # Debian's posix_prefix scheme would install to site-packages, off sys.path.
    assert "--prefix" not in command and "--target" not in command and "--user" not in command
    # rosdep installs apt pydantic 1.10 first; the lock must win after it.
    assert source.index("rosdep install --from-paths") < install
    # Readable by the service users whatever the builder's umask is.
    assert source[source.rindex("\n", 0, install):install].endswith("(umask 022 && ")


def test_image_and_release_record_the_same_python_runtime():
    # D-189 review: the runtime lives in the image, the release names the one it
    # needs, and native_release.py refuses a mismatch on activate and rollback.
    source = CUSTOMIZER.read_text(encoding="utf-8")
    payload = (IMAGE / "build-native-payload.sh").read_text(encoding="utf-8")

    assert '"$ROOT/usr/local/share/rosy/python-runtime.sha256"' in source
    assert 'printf \'%s\\n\' "$PYTHON_REQUIREMENTS_SHA"' in source
    assert "release python-runtime.sha256 does not match" in source
    assert 'sha256sum "$SCRIPT_DIR/device-python-requirements.txt"' in payload
    assert '"$RELEASE_ROOT/python-runtime.sha256"' in payload
    native = (ROOT / "deploy/robot/native/native_release.py").read_text(encoding="utf-8")
    assert 'PYTHON_RUNTIME_IMAGE_FILE = Path("usr/local/share/rosy/python-runtime.sha256")' in native
    assert 'PYTHON_RUNTIME_RELEASE_FILE = "python-runtime.sha256"' in native


def test_customizer_fails_the_build_when_core_does_not_import_in_the_image():
    source = CUSTOMIZER.read_text(encoding="utf-8")

    probe = source.index("probe-core-runtime.py --requirements")
    call = source[source.rindex("chroot", 0, probe):source.index("\n", source.index("|| fail", probe))]
    assert "source /opt/ros/jazzy/setup.bash" in call
    assert "source /opt/rosy/current/install/setup.bash" in call
    assert "python3 -B" in call and "PYTHONDONTWRITEBYTECODE=1" in call
    # As the unit runs it (D-189 review): the service user, its HOME, no login
    # shell, no user site, and runtime.env when the image has one.
    assert "setpriv --reuid=rosy-core --regid=rosy-core --clear-groups" in call
    assert "HOME=/var/lib/rosy/core" in call and "PYTHONNOUSERSITE=1" in call
    assert "bash --noprofile --norc -c" in call and "bash -lc" not in call
    assert "if [ -r /etc/rosy/runtime.env ]; then . /etc/rosy/runtime.env; fi" in call
    # The accounts exist before the probe switches to one.
    assert source.index("useradd --uid 960") < probe
    assert '|| fail "CORE does not import inside the image"' in call
    # After the release is linked as current, before the image is accepted.
    assert source.index('ln -s "releases/$RELEASE_ID" "$ROOT/opt/rosy/current"') < probe
    assert probe < source.index("verify-mounted-image.py")


def test_ci_tests_against_the_runtime_the_device_runs():
    for workflow in ("ci.yml", "arm64-rehearsal.yml"):
        text = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
        lock = "--require-hashes --no-deps --only-binary=:all: -r deploy/image/device-python-requirements.txt"
        assert lock in text
        # Test tools come after the lock, constrained to its versions, so their
        # dependencies (anyio, h11, idna, typing-extensions) are not a second copy.
        constraints = "grep -o '^[A-Za-z0-9._-]*==[^ ]*' deploy/image/device-python-requirements.txt"
        assert constraints in text
        assert text.index(lock) < text.index(constraints) < text.index("-c /tmp/rosy-runtime-constraints.txt")
        for line in text.splitlines():
            if "pip" in line and " install" in line and "-r deploy/image" not in line:
                words = set(line.split())
                assert not words & {"pydantic", "fastapi", "starlette", "uvicorn", "websockets"}, (workflow, line)


def test_probe_reads_every_pin():
    pins = _probe_module().read_pins(REQUIREMENTS)
    assert pins == {name: version for name, (version, _hashes) in _requirements().items()}


def test_probe_follows_lazy_imports_of_the_core_entrypoints():
    probe = _probe_module()
    node = (ROOT / "src/core/core/core/node.py").read_text(encoding="utf-8")
    main = (ROOT / "src/core/core/core/main.py").read_text(encoding="utf-8")

    modules = set(probe.lazy_imports(node)) | set(probe.lazy_imports(main))
    # Function-level imports a flag-only --help never reaches.
    for name in ("uvicorn", "core_api_web.api.app", "core.bridge.ros_bridge",
                 "core_common.profile", "core.node", "core_common.config", "rclpy"):
        assert name in modules, name
    assert "__future__" not in modules


def test_probe_skips_imports_guarded_by_try():
    source = (
        "import json\n"
        "def f():\n"
        "    import uvicorn\n"
        "    try:\n"
        "        from slam_toolbox.srv import SaveMap\n"
        "    except ImportError:\n"
        "        import fallback_only\n"
    )
    modules = _probe_module().lazy_imports(source)
    assert "uvicorn" in modules and "json" in modules
    assert "slam_toolbox.srv" not in modules and "slam_toolbox.srv.SaveMap" not in modules


def test_probe_fails_on_a_missing_or_wrong_pin(tmp_path, capsys):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "rosy-no-such-distribution==1.0 --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8")

    assert _probe_module().main(["--requirements", str(requirements)]) == 1
    assert "rosy-no-such-distribution: not installed" in capsys.readouterr().err


# --- D-192 US-005: the hardware runtime is part of the image ----------------
#
# rosy-pinky-e4us 2026-09-24 (release 005): sllidar_ros2 not installed,
# `import dynamixel_sdk` and `import rosylib` failed, rosy-io/rosy-navigation
# not in the image overlay.

PAYLOAD = IMAGE / "build-native-payload.sh"
IO_PROBE = IMAGE / "probe-io-runtime.py"
SLLIDAR_COMMIT = "34300099fadfc772965962dec837bf436706188f"


def test_sllidar_source_is_pinned_like_the_other_hardware_sources():
    lock = yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text(encoding="utf-8"))
    deps = lock["hardware_dependencies"]

    # The commit the Docker io image built (deploy/robot/Dockerfile SLLIDAR_COMMIT).
    assert deps["sllidar_ros2_commit"] == SLLIDAR_COMMIT
    assert f"SLLIDAR_COMMIT={SLLIDAR_COMMIT}" in (ROOT / "deploy/robot/Dockerfile").read_text(encoding="utf-8")
    assert deps["sllidar_ros2_url"] == (
        f"https://codeload.github.com/Slamtec/sllidar_ros2/tar.gz/{SLLIDAR_COMMIT}")
    assert deps["sllidar_ros2_sha256"] == "".join(
        ("6a57c289a235a37d", "ce0b07ef6fdc3ee0", "03e646140d3fdc98", "2988e7bf652367a7"))
    assert deps["verified"] is True


def test_sllidar_is_fetched_like_rpi_ws281x_and_rechecked_at_build_time():
    deps = (IMAGE / "install-pinky-hardware-deps.sh").read_text(encoding="utf-8")
    payload = PAYLOAD.read_text(encoding="utf-8")
    build = (IMAGE / "build-image.sh").read_text(encoding="utf-8")

    # The hardware-deps step fetches and checks the archive and keeps it as is.
    for fragment in ("lock_value hardware_dependencies sllidar_ros2_url",
                     "lock_value hardware_dependencies sllidar_ros2_sha256",
                     '"$VENDOR_ARCHIVES/sllidar_ros2-$SLLIDAR_COMMIT.tar.gz"'):
        assert fragment in deps, fragment
    fetch = deps.index('--output "$SLLIDAR_ARCHIVE"')
    check = deps.index('"$SLLIDAR_SHA256" "$SLLIDAR_ARCHIVE" | sha256sum --check --strict')
    assert fetch < check < deps.index('install -m 0644 "$SLLIDAR_ARCHIVE"')
    assert "tar -x" not in deps[fetch:]

    # The payload builder stays offline, re-checks and extracts into a fresh
    # directory, and builds exactly that package.
    assert "curl" not in payload
    assert 'VENDOR_WORK="$(mktemp -d)"' in payload
    assert '"$SCRIPT_DIR/prepare-vendor-source.sh" --lock "$LOCK"' in payload
    assert payload.index("prepare-vendor-source.sh") < payload.index("rosdep install")
    assert 'rosdep install --from-paths "$WORKSPACE/src" "$SLLIDAR_SRC" --ignore-src' in payload
    assert 'colcon build --base-paths src "$SLLIDAR_SRC" --merge-install' in payload
    assert 'colcon list --base-paths src "$SLLIDAR_SRC" --names-only' in payload
    assert "rosy-vendor\" --" not in payload and '--base-paths src "$VENDOR' not in payload
    # The release proves it resolves sllidar_ros2 inside its own prefix.
    assert '--required "$SCRIPT_DIR/vendor-ros-packages.txt"' in payload
    vendor = (IMAGE / "vendor-ros-packages.txt").read_text(encoding="utf-8").split()
    assert "sllidar_ros2" in vendor
    assert '--lock "$LOCK"' in build[build.index("build-native-payload.sh"):]


# prepare-vendor-source.sh is run for real (bash, tar, sha256sum).
PREPARE = IMAGE / "prepare-vendor-source.sh"
_BASH = shutil.which("bash")
_needs_bash = pytest.mark.skipif(_BASH is None, reason="bash runs the vendor preparation")
_PACKAGE_XML = "<package format=\"3\"><name>{name}</name></package>\n"


def _posix(path: Path) -> str:
    import os

    if os.name != "nt":
        return str(path)
    return subprocess.run([_BASH, "-c", 'cygpath -u "$1"', "_", str(path)],
                          capture_output=True, text=True, check=True).stdout.strip()


def _vendor_archive(tmp_path: Path, files: dict[str, str]) -> tuple[Path, Path]:
    """A codeload-shaped archive (one top directory) and a lock naming its hash."""
    import hashlib
    import io
    import tarfile

    archives = tmp_path / "archives"
    archives.mkdir()
    archive = archives / f"sllidar_ros2-{SLLIDAR_COMMIT}.tar.gz"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(f"sllidar_ros2-{SLLIDAR_COMMIT}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    archive.write_bytes(buffer.getvalue())
    lock = tmp_path / "inputs.lock.yaml"
    lock.write_text(
        "hardware_dependencies:\n"
        f"  sllidar_ros2_commit: {SLLIDAR_COMMIT}\n"
        f"  sllidar_ros2_sha256: {hashlib.sha256(archive.read_bytes()).hexdigest()}\n"
        "  verified: true\n", encoding="utf-8")
    return archives, lock


def _prepare(tmp_path: Path, archives: Path, lock: Path):
    dest = tmp_path / "work"
    dest.mkdir(exist_ok=True)
    completed = subprocess.run(
        [_BASH, PREPARE.as_posix(), "--lock", _posix(lock), "--archive-dir", _posix(archives),
         "--dest", _posix(dest)],
        capture_output=True, text=True, check=False)
    return completed, dest


@_needs_bash
def test_vendor_preparation_extracts_exactly_the_locked_package(tmp_path):
    archives, lock = _vendor_archive(tmp_path, {
        "package.xml": _PACKAGE_XML.format(name="sllidar_ros2"), "src/sllidar_node.cpp": "int main(){}\n"})

    completed, dest = _prepare(tmp_path, archives, lock)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == _posix(dest / "sllidar_ros2")
    assert (dest / "sllidar_ros2/src/sllidar_node.cpp").is_file()


@_needs_bash
def test_vendor_preparation_rejects_a_modified_archive(tmp_path):
    archives, lock = _vendor_archive(tmp_path, {"package.xml": _PACKAGE_XML.format(name="sllidar_ros2")})
    archive = next(archives.iterdir())
    archive.write_bytes(archive.read_bytes() + b"\0")

    completed, dest = _prepare(tmp_path, archives, lock)

    assert completed.returncode != 0
    assert "is not the one inputs.lock.yaml names" in completed.stderr
    assert not any(dest.iterdir())


@_needs_bash
def test_vendor_preparation_rejects_an_extra_package(tmp_path):
    archives, lock = _vendor_archive(tmp_path, {
        "package.xml": _PACKAGE_XML.format(name="sllidar_ros2"),
        "extra/package.xml": _PACKAGE_XML.format(name="rosy_no_such_extra")})

    completed, _dest = _prepare(tmp_path, archives, lock)

    assert completed.returncode != 0
    assert "exactly one ROS package" in completed.stderr


@_needs_bash
def test_vendor_preparation_rejects_another_package_name(tmp_path):
    archives, lock = _vendor_archive(tmp_path, {"package.xml": _PACKAGE_XML.format(name="rplidar_ros")})

    completed, _dest = _prepare(tmp_path, archives, lock)

    assert completed.returncode != 0
    assert "holds another package" in completed.stderr


@_needs_bash
def test_vendor_preparation_refuses_a_used_destination(tmp_path):
    archives, lock = _vendor_archive(tmp_path, {"package.xml": _PACKAGE_XML.format(name="sllidar_ros2")})
    (tmp_path / "work").mkdir()
    (tmp_path / "work/leftover").write_text("x", encoding="utf-8")

    completed, _dest = _prepare(tmp_path, archives, lock)

    assert completed.returncode != 0
    assert "destination is not empty" in completed.stderr


def test_the_bringup_launch_includes_the_driver_the_image_builds():
    launch = (ROOT / "src/hardware/bringup/launch/bringup_robot.launch.py").read_text(encoding="utf-8")
    package = (ROOT / "src/hardware/bringup/package.xml").read_text(encoding="utf-8")
    assert "get_package_share_directory('sllidar_ros2')" in launch
    assert "'sllidar_c1_launch.py'" in launch
    assert "<exec_depend>sllidar_ros2</exec_depend>" in package


def test_hardware_units_ship_in_the_overlay_and_are_not_enabled():
    payload = PAYLOAD.read_text(encoding="utf-8")
    customizer = CUSTOMIZER.read_text(encoding="utf-8")

    for unit in ("rosy-io.service", "rosy-navigation.service"):
        assert f'cp "$NATIVE_RUNTIME_SOURCE/{unit}" "$OVERLAY/etc/systemd/system/"' in payload
        assert unit not in customizer.split("systemctl --root")[1].split("\n\n")[0]


def test_mounted_image_verifier_requires_the_hardware_runtime(tmp_path):
    enabled = _valid_root(tmp_path / "enabled")
    (enabled / "etc/systemd/system/multi-user.target.wants/rosy-io.service").write_text("[Unit]\n", encoding="utf-8")
    completed = _verify(enabled)
    assert completed.returncode != 0
    assert "rosy-io.service must not be enabled" in completed.stderr

    absent = _valid_root(tmp_path / "absent")
    (absent / "etc/systemd/system/rosy-navigation.service").unlink()
    completed = _verify(absent)
    assert completed.returncode != 0
    assert "missing systemd unit: rosy-navigation.service" in completed.stderr

    no_lidar = _valid_root(tmp_path / "nolidar")
    release = no_lidar / "opt/rosy/releases/2026.09.22-001"
    (release / "rosy-packages.txt").write_text("control\ncore\n", encoding="utf-8")
    (release / "install/lib/sllidar_ros2/sllidar_node").unlink()
    completed = _verify(no_lidar)
    assert completed.returncode != 0
    assert "sllidar_ros2 (RPLIDAR C1 driver) is missing" in completed.stderr
    assert "sllidar_ros2 is not installed: install/lib/sllidar_ros2/sllidar_node" in completed.stderr


def test_mounted_image_verifier_requires_the_boot_display(tmp_path):
    disabled = _valid_root(tmp_path / "disabled")
    (disabled / "etc/systemd/system/multi-user.target.wants/rosy-boot-display.service").unlink()
    completed = _verify(disabled)
    assert completed.returncode != 0
    assert "rosy-boot-display.service is not enabled" in completed.stderr

    bare = _valid_root(tmp_path / "bare")
    (bare / "etc/systemd/system/rosy-boot-display.service").unlink()
    (bare / "etc/udev/rules.d/99-rosy-display.rules").unlink()
    status = bare / "var/lib/dpkg/status"
    status.write_text(status.read_text(encoding="utf-8").replace(
        "Package: python3-rpi-lgpio\nStatus: install ok installed",
        "Package: python3-rpi-lgpio\nStatus: deinstall ok config-files"), encoding="utf-8")
    config = bare / "boot/firmware/config.txt"
    config.write_text(config.read_text(encoding="utf-8").replace("dtparam=spi=on\n", ""), encoding="utf-8")
    completed = _verify(bare)
    assert completed.returncode != 0
    assert "missing systemd unit: rosy-boot-display.service" in completed.stderr
    assert "missing display udev rule: etc/udev/rules.d/99-rosy-display.rules" in completed.stderr
    assert "boot display package is not installed: python3-rpi-lgpio" in completed.stderr
    assert "boot display package is not installed: python3-spidev" not in completed.stderr
    assert "lost dtparam=spi=on for the Pi 5" in completed.stderr


def test_customizer_fails_the_build_when_the_hardware_runtime_does_not_import():
    source = CUSTOMIZER.read_text(encoding="utf-8")

    probe = source.index("probe-io-runtime.py'")
    call = source[source.rindex("chroot", 0, probe):source.index("\n", source.index("|| fail", probe))]
    # As rosy-io.service runs: its user and HOME, no login shell, no user site.
    assert "setpriv --reuid=rosy-io --regid=rosy-io --clear-groups" in call
    assert "HOME=/var/lib/rosy/io" in call and "PYTHONNOUSERSITE=1" in call
    assert "bash --noprofile --norc -c" in call and "python3 -B" in call
    assert "source /opt/rosy/current/install/setup.bash" in call
    assert '|| fail "the hardware runtime does not import inside the image"' in call
    assert 'cp "$IO_PROBE" "$ROOT/tmp/rosy-core-probe/probe-io-runtime.py"' in source
    # After the CORE probe and the overlay, before the image is accepted.
    assert source.index("probe-core-runtime.py --requirements") < probe
    assert probe < source.index("verify-mounted-image.py")
    assert source.index("useradd --uid 961") < probe


def _io_probe():
    import importlib.util

    spec = importlib.util.spec_from_file_location("probe_io_runtime", IO_PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_io_probe_names_what_the_005_card_lacked():
    probe = _io_probe()
    for module in ("dynamixel_sdk", "rosylib", "bringup.bringup", "bringup.battery_publisher"):
        assert module in probe.HARDWARE_MODULES, module
    assert probe.PACKAGE_FILES["sllidar_ros2"] == (
        "lib/sllidar_ros2/sllidar_node", "share/sllidar_ros2/launch/sllidar_c1_launch.py")
    assert set(probe.UNITS) == {"rosy-io.service", "rosy-navigation.service"}


def test_io_probe_checks_units_against_the_d189_rules(tmp_path):
    probe = _io_probe()
    systemd = tmp_path / "etc/systemd/system"
    systemd.mkdir(parents=True)
    native = ROOT / "deploy/robot/native"
    for unit in probe.UNITS:
        (systemd / unit).write_bytes((native / unit).read_bytes())
    rule = tmp_path / probe.UDEV_RULE
    rule.parent.mkdir(parents=True)
    rule.write_text("rule\n", encoding="utf-8")

    assert probe.check_units(tmp_path) == []

    (systemd / "multi-user.target.wants").mkdir()
    (systemd / "multi-user.target.wants/rosy-io.service").write_text("", encoding="utf-8")
    (systemd / "rosy-navigation.service").write_text("[Service]\n", encoding="utf-8")
    rule.unlink()
    failures = probe.check_units(tmp_path)
    assert any("rosy-io.service is enabled" in f for f in failures)
    assert any("rosy-navigation.service: missing Environment=PYTHONNOUSERSITE=1" in f for f in failures)
    assert any("missing motor udev rule" in f for f in failures)


def test_io_probe_reports_missing_modules_without_touching_a_device(monkeypatch):
    probe = _io_probe()
    monkeypatch.setattr(probe, "HARDWARE_MODULES", ("rosy_no_such_module",))
    failures = probe.check_modules("/usr/local")
    assert any("import rosy_no_such_module" in f for f in failures)


@_needs_bash
def test_chroot_rosdep_skips_the_vendor_keys_the_release_builds_itself():
    # D-192 review: bringup exec_depends on sllidar_ros2, which is not in the
    # chroot's source paths; rosdep must never be asked to resolve it.
    source = CUSTOMIZER.read_text(encoding="utf-8")
    start = source.index("mapfile -t VENDOR_ROS_PACKAGES")
    end = source.index("--skip-keys", start)
    end = source.index("\n", end) + 1
    snippet = source[start:end]
    script = ('fail() { echo "FAIL $*" >&2; exit 1; }\n'
              'chroot() { shift; printf "%s\n" "$@"; }\n'
              'ROOT=/image; ROSDEP_SOURCE_PATHS=(/tmp/rosy-src/src/hardware/bringup)\n' + snippet)

    completed = subprocess.run([_BASH, "-c", script, _posix(CUSTOMIZER)],
                               capture_output=True, text=True, check=False)

    assert completed.returncode == 0, completed.stderr
    args = completed.stdout.splitlines()
    assert args[:3] == ["rosdep", "install", "--from-paths"]
    assert "-r" in args and "--ignore-src" in args
    assert args[args.index("--skip-keys") + 1].split() == ["sllidar_ros2"]
    bringup = (ROOT / "src/hardware/bringup/package.xml").read_text(encoding="utf-8")
    assert "<exec_depend>sllidar_ros2</exec_depend>" in bringup
