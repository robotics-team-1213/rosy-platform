"""D-507 SIM round 2, root cause 1: a spin in place must not leave the keeper's flipping hold latched."""
import ast
from pathlib import Path

import pytest

from control.sensing.perception.lane_keep import LaneKeeper
from test_lane_keep import GROUND, HALF, X_OFFSET, _render

NODE = (Path(__file__).resolve().parents[1] / "control" / "line_observer_node.py").read_text(encoding="utf-8")
_tree = ast.parse(NODE)
_namespace = {}
exec(compile(ast.Module(body=[n for n in _tree.body if isinstance(n, ast.FunctionDef)
                              and n.name == "_spinning_in_place"], type_ignores=[]), "<node>", "exec"), _namespace)
spinning = _namespace["_spinning_in_place"]
#: The view sweeping past a lone line during the turn: hard left, hard right, ...
SWEEP = [_render([(0.035, 0.0)]), _render([(-0.035, 0.0)])] * 2
#: After the turn, on the ring: one line in view.
RING = _render([(HALF, 0.0)])


def _drive(twist):
    """The node's keep frame: a spin in place restarts the keeper, then it reads the frame."""
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, corner_turning=True)
    for frame in SWEEP:
        if spinning(twist):
            keeper.reset()
        keeper.update(frame, GROUND, lane_half_width_m=HALF)
    return keeper


@pytest.mark.parametrize("wz", [0.7, -0.3])
def test_a_spin_in_place_does_not_latch_the_flipping_hold(wz):
    keeper = _drive((0.0, wz))
    assert keeper.last.get("reason") != "flipping"
    assert keeper.update(RING, GROUND, lane_half_width_m=HALF) is not None   # turn over: the line is kept


@pytest.mark.parametrize("twist", [(0.03, 0.5), (0.0, 0.1), None])
def test_weaving_while_driving_or_without_fresh_odometry_still_holds(twist):
    # Keep steering always moves forward (vx > 0); a slow wz is no spin; no fresh odom is the old keeper.
    keeper = _drive(twist)
    assert keeper.last["reason"] == "flipping"
    assert keeper.update(RING, GROUND, lane_half_width_m=HALF) is None


def test_a_hold_latched_before_odometry_shows_the_spin_is_released_by_it():
    keeper = _drive(None)   # the sweep began before odom wz crossed the spin threshold
    assert keeper.last["reason"] == "flipping" and spinning((0.0, 0.7))
    keeper.reset()
    assert keeper.update(RING, GROUND, lane_half_width_m=HALF) is not None


def test_keep_mode_subscribes_odometry_and_a_fresh_spin_restarts_the_keeper():
    assert "mode in ('lane', 'edge_left', 'centre', 'keep', 'route_a', 'route_b', 'route_ab')" in NODE
    assert "self._odom_twist = (float(msg.twist.twist.linear.x), self._odom_wz)" in NODE
    keep = NODE.split("elif mode == 'keep':", 1)[1].split("self._lane_keeper.update(", 1)[0]
    gate = keep.split("if (self._keep_last_stamp is None", 1)[1].split("self._lane_keeper.reset()", 1)[0]
    assert "or _spinning_in_place(pose_if_fresh(self._odom_twist, self._odom_stamp, image_stamp))):" in gate
