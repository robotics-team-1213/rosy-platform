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
    for name in ("load_library", "transit_path", "park_path", "chain_path", "too_fast"):
        assert getattr(runner, name) is getattr(chunks, name)
    assert teacher.too_fast is chunks.too_fast
    assert runner.NAMES is teacher.NAMES is chunks.NAMES
    assert runner.TRANSIT is chunks.TRANSIT
    assert runner.PARK_SPEED == teacher.GUARD_UNITS_PER_S == chunks.GUARD_UNITS_PER_S
    for name in ("trapezoid", "progress", "eased", "eased_progress", "flow", "blend_chunks", "smooth", "retime"):
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


def test_a_folded_park_lifts_the_elbow_before_a_large_wrist_turn():
    """2026-11-20 arm_a: folded, the long wrist camera hit the arm at roll +18..20 until the elbow was lifted first."""
    chunks = importlib.import_module("omx_adapter.chunk_library")
    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    frames = chunks.park_path([0.0, -60.0, 50.0, 45.0, 40.0, 46.6], home, 46.6, 30)
    turning = [f for f in frames if 11.0 < f[4] < 39.0]
    assert turning and all(f[2] <= 40.5 for f in turning)
    assert frames[-1] == pytest.approx(home)
    small = chunks.park_path([0.0, -60.0, 50.0, 45.0, 18.0, 46.6], home, 46.6, 30)
    assert min(f[2] for f in small) >= 49.9


def test_transit_path_opens_elbow_before_lifting_shoulder_from_folded_home():
    """2026-11-25 arm_a: simultaneous lift/elbow unfold dipped inward into the base bracket until elbow opened first."""
    import math
    chunks = importlib.import_module("omx_adapter.chunk_library")
    from omx_adapter.kinematics import OmxKinematics

    kin = OmxKinematics.load(ADAPTER / "config/omx_f_kinematics.yaml")

    def fk(frame):
        return kin.fk([math.radians(v * 1.8) for v in frame[:5]])

    home = [0.8, -62.2, 53.1, 51.6, 45.2, 49.0]
    goal = [10.5, -19.5, 13.9, 55.7, 10.5, 62.0]
    frames = chunks.transit_path(home, goal, 46.6, 30)
    assert not chunks.too_fast([home] + frames, 30)
    assert frames[-1] == pytest.approx(goal)
    idx = next(i for i, f in enumerate(frames) if f[2] <= 43.1)
    assert all(f[1] == home[1] for f in frames if f[2] > 43.0)  # shoulder_lift does not move before elbow_flex reaches the rest point
    start_fk = fk(home)
    assert all(fk(f).x >= start_fk.x - 1e-4 for f in frames[: idx + 1])
    assert fk(frames[idx]).z >= 0.080


@pytest.mark.parametrize(
    "jaws_open, no_turn, blend",
    [
        (False, False, [False, False, False, True, True, False, False]),  # close the jaws, unfold, transit, turn
        (True, False, [False, False, False, False, True, False, False]),  # jaws open: rise first, close them at transit
        (False, True, [False, False, False, True, False, False]),  # no turn: transit flows into the approach
        (True, True, [False, False, False, False, False, False]),
    ],
)
def test_folded_transit_keeps_the_reviewed_waypoints_and_blend_flags(jaws_open, no_turn, blend):
    """The unfold waypoint (passed at rest) is the only change from the reviewed path: every other corner keeps its
    blend flag in all four rise_first x skip_turn cases (independent review of 57c7848c5b, 2026-11-25)."""
    chunks = importlib.import_module("omx_adapter.chunk_library")
    flow = importlib.import_module("omx_adapter.motion_profile").flow
    home = [0.8, -62.2, 53.1, 51.6, 45.2, 56.0 if jaws_open else 49.0]
    goal = [0.8, -30.0, 13.9, 51.6, 45.2, 62.0] if no_turn else [10.5, -19.5, 13.9, 55.7, 10.5, 62.0]
    closed = home[:5] + [46.6]
    # the transit waypoint keeps the gripper of the waypoint before it: 46.6 once the jaws closed on it, else the start's
    transit = [closed[0], chunks.TRANSIT[1], chunks.TRANSIT[2], chunks.TRANSIT[3], closed[4], home[5] if jaws_open else closed[5]]
    turn = [goal[0], *transit[1:4], goal[4], 46.6]  # taken after the jaws closed at transit, in both orders
    first = home if jaws_open else closed
    waypoints = ([home] if jaws_open else [home, closed]) + [[*first[:2], chunks.FOLDED_UNFOLD_ELBOW, *first[3:]], transit]
    waypoints += [[*transit[:5], 46.6]] if jaws_open else []
    waypoints += [] if no_turn else [turn]
    waypoints += [goal[:5] + [46.6], goal[:6]]
    assert len(waypoints) == len(blend)
    for fps in (15, 30):
        assert chunks.transit_path(home, goal, 46.6, fps) == flow(
            waypoints, fps, 0.85 * chunks.PARK_SPEED, blend=blend, blend_s=0.6, rise_speed=chunks.RISE_SPEED
        )
