"""Contracts for installing native ROSY into the mounted Ubuntu Pi image."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

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
    wants = root / "etc/systemd/system/multi-user.target.wants/chrony.service"
    wants.parent.mkdir(parents=True, exist_ok=True)
    wants.write_text("[Unit]\n", encoding="utf-8")
    return root


def _verify(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFY), "--root", str(root), "--release-id", "2026.09.22-001"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_mounted_image_verifier_accepts_native_core_only_layout(tmp_path):
    root = _valid_root(tmp_path)
    completed = _verify(root)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["ok"] is True


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
