"""D-556 candidate: fresh odometry vetoes a carried one-sided boundary; off, the D-364 keeper is untouched."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from control.keep_odom_veto import OdomVetoLaneKeeper
from control.sensing.perception.lane import LaneObservation, line_observation_payload
from control.sensing.perception.lane_keep import LaneKeeper
from test_lane_keep import GROUND, HALF, X_OFFSET, _render

NODE = Path(__file__).parents[1] / "sensors/line_observation/line_observer_node.py"
#: A left (sign 1) boundary sliding across under the robot while odometry moves the robot over it.
CROSSING_Y = (0.04, 0.03, 0.02, 0.01, 0.0, -0.01, -0.02)


def _veto():
    return OdomVetoLaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0)


@pytest.mark.parametrize("sign", (1, -1))
def test_fresh_odom_crossing_vetoes_a_carried_one_sided_boundary(sign):
    keeper = _veto()
    held = False
    for step, y in enumerate(CROSSING_Y):
        obs = keeper.update(_render([(sign * y, 0.0)]), GROUND, pose=(0.0, sign * step * 0.01, 0.0))
        if obs is None:
            held = True
            break
    assert held and keeper.side_conflict_hold
    assert keeper.last["reason"] == "odom_side_conflict" and keeper.last["strategy"] == "none"
    assert keeper.last["target_m"] is None and "error" not in keeper.last
    assert not any(record["selected"] for record in keeper.last["boundaries"] + keeper.last["candidates"])
    keeper.reset()  # camera gap or commanded spin cannot silently release the stop
    assert keeper.update(_render([(sign * y, 0.0)]), GROUND, pose=(0.0, sign * step * 0.01, 0.0)) is None
    assert keeper.last["reason"] == "odom_side_conflict"
    assert keeper.update(_render([(HALF, 0.0), (-HALF, 0.0)]), GROUND,
                         pose=(0.0, sign * step * 0.01, 0.0)) is None
    assert keeper.last["reason"] == "odom_side_conflict"  # a wall can make a false BOTH
    assert keeper.update(_render([(HALF, 0.0), (-HALF, 0.0)]), GROUND) is None  # nor does losing odometry


def test_image_side_jitter_with_stationary_odom_preserves_existing_follow():
    keeper = _veto()
    for y in (0.04, 0.02, 0.0, -0.02):
        assert keeper.update(_render([(y, 0.0)]), GROUND, pose=(0.0, 0.0, 0.0)) is not None
    assert keeper.last["strategy"] == "left_only"


def test_odom_veto_does_not_use_an_unselected_line_from_a_prior_pair():
    keeper = _veto()
    assert keeper.update(_render([(0.04, 0.0), (-0.145, 0.0)]), GROUND, pose=(0.0, 0.0, 0.0)) is not None
    assert keeper.last["strategy"] == "both"
    assert keeper.update(_render([(-0.01, 0.0)]), GROUND, pose=(0.0, 0.05, 0.0)) is not None
    assert keeper.last.get("reason") != "odom_side_conflict"


@pytest.mark.parametrize("pose", [None, (1.0, 0.05, 0.0), (0.0, float("nan"), 0.0), "bad"])
def test_missing_jumped_or_invalid_odom_cannot_start_a_new_conflict_hold(pose):
    keeper = _veto()
    assert keeper.update(_render([(0.04, 0.0)]), GROUND, pose=(0.0, 0.0, 0.0)) is not None
    assert keeper.update(_render([(-0.01, 0.0)]), GROUND, pose=pose) is not None
    assert keeper.last.get("reason") != "odom_side_conflict" and not keeper.side_conflict_hold


def _run(keeper, poses):
    rows = []
    for index, y in enumerate(CROSSING_Y):
        obs = keeper.update(_render([(y, 0.0)]), GROUND, lane_half_width_m=HALF, pose=poses[index])
        rows.append((None if obs is None else (obs.error, obs.confidence),
                     json.dumps(keeper.last, sort_keys=True, default=float)))
    return rows


def test_flag_off_keeper_ignores_odometry_and_the_veto_without_odometry_is_the_same_keeper():
    """The node hands every keeper the pose: LaneKeeper (flag off) must not read it, and the
    veto keeper without odometry (D-556 rule 4) must judge exactly as LaneKeeper does."""
    crossing = [(0.0, step * 0.01, 0.0) for step in range(len(CROSSING_Y))]
    silent = [None] * len(CROSSING_Y)
    baseline = _run(LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0), silent)
    assert all(row[0] is not None for row in baseline)
    assert _run(LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0), crossing) == baseline
    assert _run(_veto(), silent) == baseline
    assert _run(_veto(), crossing) != baseline  # the same frames do hold once the flag builds the veto


def test_node_builds_the_plain_keeper_unless_the_flag_is_set():
    source = NODE.read_text(encoding="utf-8")
    assert "self.declare_parameter('lane_odom_veto_enabled', False, _READ_ONLY)" in source
    assert ("self._lane_keeper = (OdomVetoLaneKeeper if self.get_parameter('lane_odom_veto_enabled').value"
            " else LaneKeeper)(") in source
    assert source.count("OdomVetoLaneKeeper") == 2 and source.count("side_conflict_hold") == 1


@pytest.mark.parametrize("held, quality, expected", [
    (False, None, None),
    (True, None, dict(valid=False, reason="odom_side_conflict")),
    (True, dict(valid=False, reason="low_light"), dict(valid=False, reason="low_light")),
])
def test_publish_turns_a_latched_hold_into_invisible_camera_evidence(held, quality, expected):
    tree = ast.parse(NODE.read_text(encoding="utf-8"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_publish")
    namespace = dict(json=json, String=lambda **kw: SimpleNamespace(**kw),
                     line_observation_payload=line_observation_payload)
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<publish>", "exec"), namespace)
    sent = []
    keeper = SimpleNamespace(side_conflict_hold=True) if held else SimpleNamespace()  # LaneKeeper has no latch
    node = SimpleNamespace(_lane_keeper=keeper, _ground_label=lambda: None, _camera_mode_uses_ground=lambda: False,
                           _ir_calibration=None, _ir_calibration_revision=None, _stamp=lambda: 1.0,
                           observation_pub=SimpleNamespace(publish=lambda msg: sent.append(json.loads(msg.data))))
    seen = LaneObservation(error=0.1, confidence=0.9)  # e.g. the D-597 drivable law still steering
    namespace["_publish"](node, "CAMERA_LINE", None if quality else seen, stamp=1.0, quality=quality,
                          containment=None if quality else {"v": 1})
    namespace["_publish"](node, "IR_LINE", seen, stamp=1.0)
    camera, ir = sent
    assert camera.get("quality") == expected
    assert camera["visible"] is (not held and quality is None) and ("containment" in camera) is (not held)
    assert ir["visible"] is True and "quality" not in ir
