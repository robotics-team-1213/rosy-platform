"""D-940 bucket ④: pin angle and quaternion-yaw wrap boundary conventions."""

from __future__ import annotations

import ast
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]

TEST_ANGLES = (
    0.0,
    0.5,
    -0.5,
    math.pi / 2,
    -math.pi / 2,
    math.pi,
    -math.pi,
    2 * math.pi,
    -2 * math.pi,
    3 * math.pi,
    -3 * math.pi,
    3.5 * math.pi,
    -3.5 * math.pi,
)

GROUPS = (
    (
        "_angle",
        (
            "middleware/drive/behaviors/line_follow/recovery/lane_return.py",
            "tools/sim/native_gazebo_map_pose.py",
        ),
    ),
    (
        "_wrap",
        (
            "middleware/drive/behaviors/line_follow/arc/lane_arc.py",
            "middleware/drive/behaviors/line_follow/recovery/junction/turn.py",
            "operations/overhead/rosy_vision/station_observation.py",
        ),
    ),
    (
        "_wrap",
        (
            "middleware/drive/behaviors/localization/mission.py",
            "middleware/perception/front_camera/perception/route_camera.py",
            "tools/calibration/ceiling_marker_yaw.py",
        ),
    ),
    (
        "_yaw",
        (
            "learning/curation/perception/autolabel.py",
            "middleware/perception/observers/road_state_node.py",
        ),
    ),
    (
        "wrap",
        (
            "middleware/perception/sensors/sensing/odometry_fit.py",
            "tools/device_test/tether.py",
            "tools/sim/gazebo/driver.py",
        ),
    ),
    (
        "wrap",
        (
            "integrations/simulation/gazebo/scripts/map_v2_runner.py",
            "middleware/drive/behaviors/docking/parking.py",
            "operations/fleet/fleet/localization/cues.py",
            "tools/sim/d395_truth.py",
        ),
    ),
)


def _load_ast_function(rel_path: str, func_name: str):
    source = (ROOT / rel_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=rel_path)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            mod = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(mod)
            ns = {"math": math}
            exec(compile(mod, filename=rel_path, mode="exec"), ns)
            return ns[func_name]
    raise AssertionError(f"{rel_path}: top-level function {func_name!r} not found")


def _eval_angle(fn, func_name: str, angle: float) -> float:
    if func_name == "_yaw":
        half = angle / 2.0
        q = SimpleNamespace(w=math.cos(half), x=0.0, y=0.0, z=math.sin(half))
        return fn(q)
    return fn(angle)


@pytest.mark.parametrize("func_name, paths", GROUPS)
def test_group_members_agree_and_pin_pi_boundary(func_name: str, paths: tuple[str, ...]):
    funcs = {path: _load_ast_function(path, func_name) for path in paths}
    first_path = paths[0]
    first_fn = funcs[first_path]

    for angle in TEST_ANGLES:
        ref = _eval_angle(first_fn, func_name, angle)
        assert isinstance(ref, float)
        assert -math.pi <= ref <= math.pi
        for other_path in paths[1:]:
            val = _eval_angle(funcs[other_path], func_name, angle)
            assert val == ref, f"{other_path} disagreed with {first_path} at {angle!r}"

    # Interior values lie strictly inside (-pi, +pi).
    for interior in (0.0, 0.5, -0.5, math.pi / 2, -math.pi / 2, 2 * math.pi, -2 * math.pi, 3.5 * math.pi, -3.5 * math.pi):
        val = _eval_angle(first_fn, func_name, interior)
        assert -math.pi < val < math.pi

    # Pin the atan2 discontinuity convention on (-pi, +pi]:
    # +pi wraps to exact +pi; IEEE-754 float -pi has sin(-pi) < 0 so wraps to exact -pi.
    assert _eval_angle(first_fn, func_name, math.pi) == math.pi
    assert _eval_angle(first_fn, func_name, -math.pi) == -math.pi
    assert _eval_angle(first_fn, func_name, 3 * math.pi) == pytest.approx(math.pi, abs=1e-15)
    assert _eval_angle(first_fn, func_name, -3 * math.pi) == pytest.approx(-math.pi, abs=1e-15)

    if func_name == "_yaw":
        # Quaternion double-cover (q and -q) at exact half-turn both land on +pi in (-pi, +pi].
        q_pos = SimpleNamespace(w=0.0, x=0.0, y=0.0, z=1.0)
        q_neg = SimpleNamespace(w=0.0, x=0.0, y=0.0, z=-1.0)
        for path, fn in funcs.items():
            assert fn(q_pos) == math.pi, f"{path}: +180 deg quaternion must wrap to +pi"
            assert fn(q_neg) == math.pi, f"{path}: antipodal -q half-turn quaternion must also wrap to +pi"
