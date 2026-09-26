"""D-288 camera image inputs and mounted-root acceptance checks."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "deploy/image"


def _verifier():
    spec = importlib.util.spec_from_file_location("camera_image_verifier", IMAGE / "verify-mounted-image.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_camera_inputs_are_pinned_and_installed_before_image_verification():
    lock = yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text(encoding="utf-8"))["camera_runtime"]
    sources = IMAGE / lock["sources"]
    requirements = IMAGE / lock["python_requirements"]
    assert _sha(sources) == lock["sources_sha256"]
    assert _sha(requirements) == lock["python_requirements_sha256"]
    pins = json.loads(sources.read_text(encoding="utf-8"))["sources"]
    assert [pin["name"] for pin in pins] == ["libpisp", "libcamera", "rpicam-apps", "picamera2"]
    assert all(re.fullmatch(r"[0-9a-f]{40}", pin["commit"]) for pin in pins)
    assert all(re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) for pin in pins)
    customizer = (IMAGE / "customize-rootfs.sh").read_text(encoding="utf-8")
    assert (IMAGE / "customize-rootfs.sh").read_bytes().startswith(b"#!/usr/bin/env bash")
    assert customizer.index('bash "$CAMERA_INSTALLER"') < customizer.index('verify-mounted-image.py" --root')
    installer = (IMAGE / "install-camera-stack.sh").read_text(encoding="utf-8")
    assert (IMAGE / "install-camera-stack.sh").read_bytes().startswith(b"#!/usr/bin/env bash")
    assert customizer.index('chroot "$ROOT" apt-get clean') < customizer.index('bash "$CAMERA_INSTALLER"')
    assert yaml.safe_load((IMAGE / "inputs.lock.yaml").read_text(encoding="utf-8"))["product_artifact"]["rootfs_expansion_mib"] >= 8192
    assert "https://codeload.github.com/raspberrypi/$name/tar.gz/$commit" in installer
    assert installer.index('meson_build libpisp') < installer.index('meson_build libcamera')
    assert installer.index('meson_build libcamera') < installer.index('meson_build rpicam-apps')
    assert "-Dpipelines=rpi/pisp,rpi/vc4" in installer
    assert "--require-hashes" in installer


def test_camera_capture_and_preview_start_on_first_boot_without_motor_access():
    unit = (ROOT / "deploy/robot/native/rosy-camera.service").read_text(encoding="utf-8")
    target = (ROOT / "deploy/robot/native/rosy-runtime.target").read_text(encoding="utf-8")
    payload = (IMAGE / "build-native-payload.sh").read_text(encoding="utf-8")
    launch = (ROOT / "src/runtime/sensing/launch/camera_preview.launch.py").read_text(encoding="utf-8")
    assert "Wants=rosy-io.service rosy-camera.service" in target
    assert 'cp "$NATIVE_RUNTIME_SOURCE/rosy-camera.service"' in payload
    assert "User=rosy-camera" in unit
    assert "SupplementaryGroups=video" in unit
    assert "DevicePolicy=closed" in unit
    assert "DeviceAllow=char-video4linux rw" in unit
    assert "DeviceAllow=char-media rw" in unit
    assert "DeviceAllow=char-dma_heap rw" in unit
    assert "dialout" not in unit and "rosy-motor" not in unit and "cmd_vel" not in launch
    assert "camera_backend': 'picamera2'" in launch
    assert "camera_detect_node" in launch and "road_observer_node" in launch
    assert "line_observer_node" not in launch and "ir_adc_node" not in launch


def test_camera_stack_verifier_rejects_missing_payload_and_changed_provenance(tmp_path):
    verify = _verifier()
    findings = verify.camera_stack_findings(tmp_path)
    assert any("source record" in finding for finding in findings)
    assert any("rpicam-still" in finding for finding in findings)
    assert any("ipa_rpi_pisp" in finding for finding in findings)

    files = (
        "usr/local/bin/rpicam-hello",
        "usr/local/bin/rpicam-still",
        "usr/local/lib/aarch64-linux-gnu/libpisp.so.1",
        "usr/local/lib/aarch64-linux-gnu/libcamera.so.0.3",
        "usr/local/lib/aarch64-linux-gnu/libcamera/ipa_rpi_pisp.so",
        "usr/local/lib/aarch64-linux-gnu/python3.12/site-packages/libcamera/__init__.py",
        "usr/local/lib/python3.12/dist-packages/picamera2/__init__.py",
    )
    for relative in files:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    record = tmp_path / verify.CAMERA_SOURCE_RECORD
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_bytes(verify.CAMERA_SOURCE_LOCK.read_bytes())
    python_record = tmp_path / verify.CAMERA_PYTHON_RECORD
    python_record.parent.mkdir(parents=True, exist_ok=True)
    python_record.write_text(_sha(IMAGE / "camera-python-requirements.txt") + "\n", encoding="utf-8")
    assert verify.camera_stack_findings(tmp_path) == []
    record.write_text("{}", encoding="utf-8")
    assert any("source record" in finding for finding in verify.camera_stack_findings(tmp_path))
