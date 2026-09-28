"""D-164 contracts for the Pinky Pro flashable product image."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ADR_LOG = ROOT / "docs/reference/ROSY ADR Log.md"
D164 = ROOT / "docs/adr/D-164-pinky-pro-flashable-image.md"
DESIGN = ROOT / "docs/plans/2026-09-22-pinky-pro-flashable-image-design.md"
PLAN = ROOT / "docs/plans/2026-09-22-pinky-pro-flashable-image.md"
LOCK = ROOT / "deploy/robot/pinky_pro/image/inputs.lock.yaml"
IMAGE_GUIDE = ROOT / "deploy/robot/pinky_pro/image/AGENTS.md"


def test_d164_accepts_a_pi_disk_image_and_rejects_an_installer_iso():
    log = ADR_LOG.read_text(encoding="utf-8-sig")
    adr = D164.read_text(encoding="utf-8-sig")

    assert "| D-164 |" in log
    assert "**Status:** Accepted" in adr
    assert "rosy-os-pinky-pro-<release-id>-arm64.img.xz" in adr
    assert "`.iso`" in adr and "만들거나 제품 파일로 홍보하지 않는다" in adr
    assert "preinstalled-server-arm64+raspi.img.xz" in adr


def test_lock_names_the_exact_flashable_artifact_contract():
    lock = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    artifact = lock["product_artifact"]

    assert artifact["format"] == "raw-disk-image"
    assert artifact["compression"] == "xz"
    assert artifact["filename_template"] == (
        "rosy-os-pinky-pro-{release_id}-arm64.img.xz"
    )
    assert artifact["intermediate_suffix"] == ".img"
    assert artifact["rootfs_expansion_mib"] >= 4096
    assert artifact["raspberry_pi_imager_compatible"] is True
    assert artifact["contains_partition_table"] is True
    assert artifact["device_neutral"] is True
    assert artifact["forbidden_formats"] == ["iso"]


def test_release_requires_image_identity_security_and_provenance_sidecars():
    lock = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    required = set(lock["product_artifact"]["required_files"])

    assert {
        "manifest.json",
        "SHA256SUMS",
        "SHA256SUMS.sig",
        "sbom.spdx.json",
        "deb-packages.txt",
        "rosy-packages.txt",
        "required-ros-packages.txt",
        "source-revision.txt",
        "base-image-provenance.json",
        "build-provenance.json",
        "artifact-report.md",
    } == required


def test_common_image_excludes_per_device_identity_and_runtime_secrets():
    lock = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    excluded = set(lock["product_artifact"]["excluded_device_fields"])

    assert {
        "hostname",
        "device_uid",
        "robot_number",
        "wifi_credentials",
        "fleet_pairing_credential",
        "ssh_private_key",
    } == excluded
    assert lock["runtime"]["container_runtime_required"] is False


def test_design_and_plan_keep_artifact_media_and_device_as_separate_gates():
    design = DESIGN.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    guide = IMAGE_GUIDE.read_text(encoding="utf-8")

    for gate in ("ARTIFACT", "MEDIA", "BOOT", "DEVICE", "FLEET"):
        assert gate in design
    assert "Task 8" in plan and "Task 9" in plan and "Task 10" in plan
    assert "generic installer ISO is not" in guide
    assert "signature file's presence is not verification" in guide
