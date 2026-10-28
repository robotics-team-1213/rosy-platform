"""Installed pure chunk planning remains usable by the native script callers."""

import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
ADAPTER = ROOT / "middleware/devices/omx/adapter"
OMX = ROOT / "deploy/robot/omx"


def library():
    return {
        "schema": "rosy.omx-chunk-library.v1",
        "names": ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos",
                  "wrist_roll.pos", "gripper.pos"],
        "fps": 30,
        "gripper_closed": 46.6,
        "chunks": {"home": [[0.0, -60.0, 50.0, 45.0, 10.0, 46.6]]},
        "transit": {"1": -26.0, "2": 17.0, "3": 47.0},
        "source": {"revision": "retained-teaching"},
    }


def test_installed_library_keeps_taught_metadata(tmp_path):
    chunks = importlib.import_module("omx_adapter.chunk_library")
    document = library()
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps(document))
    assert chunks.load_library(path) == document


@pytest.mark.parametrize("field,value,message", [
    ("schema", "wrong", "schema"),
    ("fps", 0, "fps"),
    ("chunks", {}, "no chunks"),
    ("chunks", {"home": [[0, 0, 0, 0, 0, float("nan")]]}, "six finite values"),
    ("chunks", {"home": [[0] * 6, [1] * 6]}, "faster than the guard"),
    ("gripper_closed", None, "gripper_closed"),
])
def test_installed_library_preserves_validation_errors(tmp_path, field, value, message):
    chunks = importlib.import_module("omx_adapter.chunk_library")
    document = {**library(), field: value}
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps(document))
    with pytest.raises(SystemExit, match=message):
        chunks.load_library(path)


def test_legacy_callers_use_the_installed_functions(monkeypatch):
    chunks = importlib.import_module("omx_adapter.chunk_library")
    profile = importlib.import_module("omx_adapter.motion_profile")
    monkeypatch.syspath_prepend(str(OMX))
    runner = importlib.import_module("chunk_runner")
    teacher = importlib.import_module("teach_trajectory")
    legacy_profile = importlib.import_module("motion_profile")
    for name in ("load_library", "transit_path", "park_path", "too_fast"):
        assert getattr(runner, name) is getattr(chunks, name)
    assert teacher.too_fast is chunks.too_fast
    assert runner.NAMES is teacher.NAMES is chunks.NAMES
    assert runner.TRANSIT is chunks.TRANSIT
    assert runner.PARK_SPEED == teacher.GUARD_UNITS_PER_S == chunks.GUARD_UNITS_PER_S
    for name in ("trapezoid", "progress", "smooth", "retime"):
        assert getattr(legacy_profile, name) is getattr(profile, name)


def test_installed_planning_imports_without_deploy_or_hardware_modules(tmp_path):
    script = """
import importlib.abc
import sys
sys.path.insert(0, sys.argv[1])
class NoHardware(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'serial', 'dynamixel_sdk', 'lerobot', 'rclpy', 'chunk_runner',
                                      'teach_trajectory', 'guarded_native', 'motion_profile'}:
            raise AssertionError('unexpected import: ' + fullname)
sys.meta_path.insert(0, NoHardware())
before = list(sys.path)
from omx_adapter.chunk_library import transit_path, park_path, too_fast
from omx_adapter.motion_profile import retime
assert sys.path == before
start = [0., -60., 50., 45., 10., 46.6]
goal = [-3., -16., 9., 48., 5., 55.]
saved = list(start)
path = transit_path(start, goal, 46.6, 30, {1: -27., 2: 18., 3: 46.})
assert start == saved and path[-1] == goal and not too_fast([start] + path, 30)
assert park_path(goal, start, 46.6, 30)[-1] == start
assert retime([start, goal], 30, 4.)[-1] == goal
"""
    result = subprocess.run([sys.executable, "-I", "-c", script, str(ADAPTER)], cwd=tmp_path,
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_export_contains_the_script_import_closure(tmp_path):
    config = json.loads((OMX / "omx-devices-autoupdate.json.example").read_text())
    stage = tmp_path / "native-release"
    stage.mkdir()
    for relative in config["paths"]:
        source, target = ROOT / relative, stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source, target)
    script = """
import importlib.abc
import os
from pathlib import Path
import sys
root = Path.cwd()
assert not any(str(Path(sys.argv[1])) in entry for entry in sys.path)
sys.path[:0] = os.environ['PYTHONPATH'].split(os.pathsep)
class NoHardware(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'serial', 'dynamixel_sdk', 'lerobot', 'rclpy', 'guarded_native'}:
            raise AssertionError('unexpected hardware import: ' + fullname)
sys.meta_path.insert(0, NoHardware())
exec(sys.argv[2])
import chunk_runner, teach_trajectory, motion_profile
from omx_adapter import chunk_library
from omx_adapter import motion_profile as installed_profile
assert chunk_runner.load_library is chunk_library.load_library
assert teach_trajectory.too_fast is chunk_library.too_fast
assert motion_profile.smooth is installed_profile.smooth
assert Path(chunk_library.__file__).is_relative_to(root)
assert Path(installed_profile.__file__).is_relative_to(root)
"""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(stage / path) for path in (
        "deploy/robot/omx", "contracts/foundation", "operations/overhead", "middleware/devices/omx/adapter"))}
    result = subprocess.run([sys.executable, "-I", "-c", script, str(ROOT), config["smoke"]],
                            cwd=stage, env=env, text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
