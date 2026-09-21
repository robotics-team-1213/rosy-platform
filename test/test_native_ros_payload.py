"""Contracts for the offline native ROS 2 Jazzy ROSY payload."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "deploy" / "image"
REQUIRED = IMAGE / "required-ros-packages.txt"
BUILD = IMAGE / "build-native-payload.sh"
VERIFY = IMAGE / "verify-package-inventory.sh"
HARDWARE_DEPS = IMAGE / "install-pinky-hardware-deps.sh"
LOCK = IMAGE / "inputs.lock.yaml"
RESOLVE_SOURCE_PATHS = IMAGE / "resolve-required-source-paths.py"


def _bash_is_usable() -> bool:
    try:
        return subprocess.run(
            ["bash", "-c", "true"], capture_output=True, timeout=30, check=False
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


bash_only = pytest.mark.skipif(not _bash_is_usable(), reason="bash is required")


def test_native_payload_tools_exist():
    assert REQUIRED.is_file()
    assert BUILD.is_file()
    assert VERIFY.is_file()
    assert HARDWARE_DEPS.is_file()
    assert RESOLVE_SOURCE_PATHS.is_file()


def test_pinky_hardware_dependencies_are_exactly_pinned():
    lock = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    deps = lock["hardware_dependencies"]

    assert deps["wiringpi_version"] == "3.20"
    assert deps["wiringpi_url"].endswith("/v3.20/wiringpi_3.20_arm64.deb")
    assert deps["wiringpi_sha256"] == "".join(
        ("85f5965d57adb895", "b97b3f8b04083613", "d00964f930cb8682", "2459eae5a97dc804")
    )
    assert deps["rpi_ws281x_commit"] == "1396df4f35a86de0f7e5eda91d94d4539eef1727"
    assert deps["rpi_ws281x_url"].endswith(deps["rpi_ws281x_commit"])
    assert deps["rpi_ws281x_sha256"] == "".join(
        ("18896f9576848944", "a7f53834b4e329aa", "eb1961d2cadf7bf6", "7aecf1f9df91aaa6")
    )
    assert deps["verified"] is True


def test_hardware_dependency_installer_verifies_inputs_before_installing():
    script = HARDWARE_DEPS.read_text(encoding="utf-8")

    for fragment in (
        "uname -m", "aarch64", "wiringpi_url", "wiringpi_sha256",
        "rpi_ws281x_url", "rpi_ws281x_sha256", "sha256sum",
        "dpkg -i", "cmake", "BUILD_SHARED=OFF", "BUILD_TEST=OFF",
    ):
        assert fragment in script
    assert script.index("sha256sum") < script.index("dpkg -i")


def test_image_workflow_installs_pinky_hardware_dependencies_before_payload_build():
    workflow = (ROOT / ".github/workflows/build-pinky-image.yml").read_text(
        encoding="utf-8"
    )

    assert "install-pinky-hardware-deps.sh" in workflow
    assert workflow.index("install-pinky-hardware-deps.sh") < workflow.index(
        "build-image.sh"
    )


def test_required_source_resolver_includes_transitive_product_deps_not_non_product_apps():
    result = subprocess.run(
        [
            sys.executable,
            str(RESOLVE_SOURCE_PATHS),
            "--source-root",
            str(ROOT / "src"),
            "--required",
            str(REQUIRED),
            "--chroot-prefix",
            "/tmp/rosy-src/src",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    paths = set(result.stdout.splitlines())
    for suffix in (
        "/core/core", "/core/core_common", "/core/core_events",
        "/core/core_features", "/core/core_api_web", "/core/interfaces",
        "/hardware/sensor_adc", "/hardware/imu_bno055", "/hardware/lamp_control",
    ):
        assert any(path.endswith(suffix) for path in paths)
    assert not any(path.endswith("/sim/gz_sim") for path in paths)
    assert not any(path.endswith("/apps/games") for path in paths)
    assert not any(path.endswith("/site/fleet") for path in paths)


def test_required_package_file_matches_the_locked_offline_payload():
    lock = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    packages = [
        line.strip() for line in REQUIRED.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert len(packages) == len(set(packages))
    assert set(packages) == set(lock["rosy_packages"]["required"])


def test_native_builder_is_arm64_only_and_builds_a_merged_offline_install():
    script = BUILD.read_text(encoding="utf-8")

    for fragment in (
        "uname -m", "aarch64", "/opt/ros/jazzy/setup.bash",
        "rosdep install", "--from-paths", "--ignore-src",
        "colcon build", "--merge-install", "--install-base",
        "dpkg-query", "LC_ALL=C sort", "verify-package-inventory.sh",
        "deploy/robot/native", "deploy/image/first-boot", "deploy/sd",
        "--release-id", ".rosy-release",
    ):
        assert fragment in script
    assert "curl" not in script and "wget" not in script
    assert "set +u\nsource /opt/ros/jazzy/setup.bash\nset -u" in script
    assert 'set +u\nsource "$INSTALL_ROOT/setup.bash"\nset -u' in script


def test_native_builder_embeds_the_selected_release_public_key():
    script = BUILD.read_text(encoding="utf-8")
    public_key = ROOT / "deploy" / "release" / "public-keys" / "rosy-release-2026-01.pem"

    assert public_key.is_file()
    assert "BEGIN PUBLIC KEY" in public_key.read_text(encoding="utf-8")
    assert "deploy/release/public-keys/rosy-release-2026-01.pem" in script
    assert "trusted-release-keys/rosy-release-2026-01.pem" in script


def test_product_image_pipeline_invokes_the_pinned_base_and_native_payload_stages():
    script = (IMAGE / "build-image.sh").read_text(encoding="utf-8")

    assert "fetch-base-image.sh" in script
    assert "build-native-payload.sh" in script
    assert "--source-revision" in script
    assert "--release-root" in script
    assert "--release-id" in script


@bash_only
def test_inventory_verifier_accepts_sorted_packages_under_the_release_prefix(tmp_path):
    shutil.copy(VERIFY, tmp_path / "verify-package-inventory.sh")
    (tmp_path / "required.txt").write_text("bringup\ncore\n", encoding="utf-8")
    (tmp_path / "inventory.txt").write_text("bringup\ncore\ninterfaces\n", encoding="utf-8")
    (tmp_path / "release" / "install").mkdir(parents=True)
    fake = tmp_path / "ros2"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "[[ \"$1 $2\" == 'pkg prefix' ]] || exit 2\n"
        "printf '%s/release/install\\n' \"$PWD\"\n",
        encoding="utf-8",
        newline="\n",
    )
    fake.chmod(0o755)

    result = subprocess.run(
        [
            "bash", "verify-package-inventory.sh",
            "--required", "required.txt", "--inventory", "inventory.txt",
            "--install-root", "release/install", "--ros2", "./ros2",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "INVENTORY_VERIFIED" in result.stdout


@bash_only
def test_inventory_verifier_rejects_missing_or_outside_packages(tmp_path):
    shutil.copy(VERIFY, tmp_path / "verify-package-inventory.sh")
    (tmp_path / "required.txt").write_text("bringup\ncore\n", encoding="utf-8")
    (tmp_path / "inventory.txt").write_text("bringup\n", encoding="utf-8")
    (tmp_path / "release" / "install").mkdir(parents=True)
    fake = tmp_path / "ros2"
    fake.write_text(
        "#!/usr/bin/env bash\nprintf '/opt/other/install\\n'\n",
        encoding="utf-8",
        newline="\n",
    )
    fake.chmod(0o755)

    result = subprocess.run(
        [
            "bash", "verify-package-inventory.sh",
            "--required", "required.txt", "--inventory", "inventory.txt",
            "--install-root", "release/install", "--ros2", "./ros2",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode != 0
    assert "missing required package" in result.stderr.lower()
