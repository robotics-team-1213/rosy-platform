"""Compile actual locked vendor method bodies with communication-boundary doubles.

Opt in on a test host with ROSY_OMX_VENDOR_ROOT pointing at its locked checkout.
Neither the fixture nor executable loads ROS, an SDK or any device.
"""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIN = "3375b3d0c99c5bcdab11b2dc15c89a2923e2bca2"
SOURCE = "src/dynamixel_hardware_interface.cpp"
PATCH = ROOT / "deploy/robot/omx/patches/hardware-lifecycle-errors.patch"


def method(source, name):
    start = source.index(f"hardware_interface::CallbackReturn DynamixelHardware::{name}()")
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
