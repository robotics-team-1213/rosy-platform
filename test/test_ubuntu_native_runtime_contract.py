"""D-161 contracts for the Ubuntu-native ROS product runtime."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "reference" / "ROSY ADR Log.md"
D161 = ROOT / "docs" / "adr" / "D-161-ubuntu-server-native-ros-runtime.md"
D22 = ROOT / "docs" / "adr" / "D-22-raspberry-pi-os-core-i-o-deadman.md"
DESIGN = ROOT / "docs" / "plans" / "2026-09-21-ubuntu-native-ros-runtime-design.md"
PLAN = ROOT / "docs" / "plans" / "2026-09-21-ubuntu-native-ros-runtime.md"
LOCK = ROOT / "deploy" / "robot" / "pinky_pro" / "image" / "inputs.lock.yaml"
BUILD = ROOT / "deploy" / "robot" / "pinky_pro" / "image" / "build-image.sh"


def test_d161_accepts_ubuntu_native_ros_and_supersedes_d22_mechanism():
    index = ADR.read_text(encoding="utf-8-sig")
    section = D161.read_text(encoding="utf-8-sig")
    d22 = D22.read_text(encoding="utf-8-sig")

    assert "| D-161 |" in index
    assert "**Status:** Accepted" in section
    assert "Ubuntu Server 24.04" in section
    assert "ROS 2 Jazzy" in section
    assert "native" in section.lower()
    assert "D-22" in section and "supersed" in section.lower()
    assert "development" in section.lower() and "CI" in section and "Docker" in section

    assert "Superseded by D-161" in d22


def test_image_lock_targets_official_ubuntu_noble_arm64_and_native_jazzy():
    lock = yaml.safe_load(LOCK.read_text(encoding="utf-8"))

    assert lock["os"] == {
        **lock["os"],
        "family": "ubuntu-server",
        "release": "24.04",
        "codename": "noble",
        "architecture": "arm64",
        "variant": "preinstalled-server-arm64+raspi",
    }
    assert lock["runtime"]["model"] == "native-systemd"
    assert lock["runtime"]["container_runtime_required"] is False
    assert lock["ros"]["distribution"] == "jazzy"
    assert lock["ros"]["installation"] == "native-deb"
    assert lock["ros"]["architecture"] == "arm64"
    assert lock["containers"]["role"] == "development-and-ci-only"


def test_pinky_packages_are_mandatory_image_payload_not_first_boot_downloads():
    lock = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    required = set(lock["rosy_packages"]["required"])

    assert {
        "interfaces", "core", "bringup", "description", "navigation",
        "control", "omx_adapter", "led", "sensor_adc", "lamp_control",
        "emotion", "imu_bno055",
    } <= required
    assert lock["rosy_packages"]["offline_first_boot"] is True
    assert lock["rosy_packages"]["inventory_required"] is True
    assert lock["rosy_packages"]["ros2_pkg_prefix_required"] is True


def test_design_and_execution_plan_keep_unbuilt_artifact_gates_on_hold():
    design = DESIGN.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")

    assert "D-161" in design and "immediate transition" in design.lower()
    assert "ARTIFACT" in design and "HOLD" in design
    assert "DEVICE" in design and "HOLD" in design
    assert "REQUIRED SUB-SKILL" in plan
    assert "test_ubuntu_native_runtime_contract.py" in plan
    assert "native ARM64" in plan


def test_product_image_builder_no_longer_targets_raspberry_pi_os():
    script = BUILD.read_text(encoding="utf-8")

    assert "Ubuntu Server 24.04" in script
    assert "rpi-image-gen" not in script
