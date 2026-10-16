"""Compile actual locked vendor method bodies with communication-boundary doubles.

Opt in on a test host with ROSY_OMX_VENDOR_ROOT pointing at its locked checkout.
Neither the fixture nor executable loads ROS, an SDK or any device.
"""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
_lock = yaml.safe_load((ROOT / "deploy/robot/omx/stack.lock.yaml").read_text())
PIN = next(item["revision"] for item in _lock["vendor"]["repositories"]
           if item["name"] == "dynamixel_hardware_interface")
SOURCE = "src/dynamixel_hardware_interface.cpp"
PATCH = ROOT / "deploy/robot/omx/patches/hardware-lifecycle-errors.patch"


def method(source, name):
    return function(source, f"hardware_interface::CallbackReturn DynamixelHardware::{name}()")


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        depth += (source[index] == "{") - (source[index] == "}")
        if depth == 0:
            return source[start:index + 1]
    raise ValueError("unclosed pinned method")


@pytest.mark.skipif(not os.environ.get("ROSY_OMX_VENDOR_ROOT"), reason="requires explicit locked vendor source")
def test_actual_vendor_lifecycle_error_propagation(tmp_path):
    configured = Path(os.environ["ROSY_OMX_VENDOR_ROOT"])
    vendor = configured if configured.is_absolute() else Path.home() / configured
    assert shutil.which("g++") and shutil.which("patch")
    revision = subprocess.check_output(["git", "-C", str(vendor), "rev-parse", "HEAD"], text=True).strip()
    assert revision == PIN
    original = subprocess.check_output(["git", "-C", str(vendor), "show", f"{PIN}:{SOURCE}"], text=True)
    fixture = (ROOT / "test/fixtures/omx_driver_lifecycle.cpp").read_text()

    def execute(source, name):
        program = tmp_path / f"{name}.cpp"
        binary = tmp_path / name
        bodies = "\n".join(method(source, item) for item in ("start", "stop"))
        program.write_text(fixture.replace("// VENDOR_METHODS", bodies))
        subprocess.run(["g++", "-std=c++14", "-Wall", "-Wextra", str(program), "-o", str(binary)], check=True, timeout=60)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        print(name + "\n" + result.stdout)
        return result

    before = execute(original, "upstream")
    assert before.returncode == 5
    assert set(line for line in before.stdout.splitlines() if line.startswith("FAIL")) == {
        "FAIL initial_write_failure", "FAIL enable_retry_exhaustion",
        "FAIL first_stop_group_failure", "FAIL second_stop_group_failure",
        "FAIL failed_rollback_stays_error"}
    target = tmp_path / SOURCE
    target.parent.mkdir()
    target.write_text(original)
    subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(PATCH)], cwd=tmp_path, check=True)
    after = execute(target.read_text(), "patched")
    assert after.returncode == 0, after.stdout + after.stderr
    assert len(after.stdout.splitlines()) == 10


@pytest.mark.skipif(not os.environ.get("ROSY_OMX_VENDOR_ROOT"), reason="requires explicit locked vendor source")
def test_vendor_does_not_advertise_owner_bypass_services(tmp_path):
    configured = Path(os.environ["ROSY_OMX_VENDOR_ROOT"])
    vendor = configured if configured.is_absolute() else Path.home() / configured
    original = subprocess.check_output(["git", "-C", str(vendor), "show", f"{PIN}:{SOURCE}"], text=True)
    callbacks = ("set_dxl_data_srv_callback", "reboot_dxl_srv_callback", "set_dxl_torque_srv_callback")
    for name in callbacks:
        assert f"std::bind(&DynamixelHardware::{name}" in original
    target = tmp_path / SOURCE
    target.parent.mkdir()
    target.write_text(original)
    patch = ROOT / "deploy/robot/omx/patches/hardware-owner-command-path.patch"
    subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(patch)], cwd=tmp_path, check=True)
    changed = target.read_text()
    for name in callbacks:
        assert f"std::bind(&DynamixelHardware::{name}" not in changed
    assert "std::bind(&DynamixelHardware::get_dxl_data_srv_callback" in changed


@pytest.mark.skipif(not os.environ.get("ROSY_OMX_VENDOR_ROOT"), reason="requires explicit locked vendor source")
def test_initialization_rejects_fault_without_reboot(tmp_path):
    configured = Path(os.environ["ROSY_OMX_VENDOR_ROOT"])
    vendor = configured if configured.is_absolute() else Path.home() / configured
    assert subprocess.check_output(["git", "-C", str(vendor), "rev-parse", "HEAD"], text=True).strip() == PIN
    path = "src/dynamixel/dynamixel.cpp"
    original = subprocess.check_output(["git", "-C", str(vendor), "show", f"{PIN}:{path}"], text=True)
    fixture = (ROOT / "test/fixtures/omx_driver_init.cpp").read_text()
    def execute(source, name):
        body = function(source, "DxlError Dynamixel::InitDxlComm(")
        program, binary = tmp_path / f"{name}.cpp", tmp_path / name
        program.write_text(fixture.replace("// VENDOR_METHOD", body))
        subprocess.run(["g++", "-std=c++14", "-Wall", "-Wextra", str(program), "-o", str(binary)],
                       check=True, timeout=60)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        print(name + "\n" + result.stdout)
        return result

    before = execute(original, "upstream_init")
    assert before.returncode == 2
    assert set(line for line in before.stdout.splitlines() if line.startswith("FAIL")) == {
        "FAIL hardware_alert_no_reboot", "FAIL error_code_no_reboot"}
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text(original)
    patch = ROOT / "deploy/robot/omx/patches/hardware-init-no-reboot.patch"
    subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(patch)], cwd=tmp_path, check=True)
    after = execute(target.read_text(), "patched_init")
    assert after.returncode == 0, after.stdout + after.stderr
    assert len(after.stdout.splitlines()) == 5
