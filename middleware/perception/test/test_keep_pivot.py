"""D-507 SIM round 2, root cause 1: a spin in place must not leave the keeper's flipping hold latched.
Round 4b: "spin in place" is CORE's commanded twist (cmd_vel), not measured odom."""
import ast
from types import SimpleNamespace
from pathlib import Path

import pytest

from control.sensing.perception.lane_bev import ODOM_MAX_SKEW_S, pose_if_fresh
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


def _drive(twist, keeper=None, skew_s=0.0):
    """The node's keep frame: a fresh commanded spin in place restarts the keeper, then it reads the frame."""
    keeper = keeper or LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, corner_turning=True)
    for i, frame in enumerate(SWEEP):
        image_stamp = 100.0 + 0.1 * i
        if spinning(pose_if_fresh(twist, image_stamp - skew_s, image_stamp)):
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


_KEEP = NODE.split("elif mode == 'keep':", 1)[1].split("self._lane_keeper.update(", 1)[0]
_GATE = _KEEP.split("if (self._keep_last_stamp is None", 1)[1].split("self._lane_keeper.reset()", 1)[0]
#: The node's own spin term of the keep reset gate, evaluated as written.
_SPIN_TERM = "_spinning_in_place(" + _GATE.split("or _spinning_in_place(", 1)[1].rsplit("):", 1)[0]


def _node_gate(cmd, odom, image_stamp=100.0, cmd_age_s=0.0):
    node = SimpleNamespace(_cmd_twist=cmd, _cmd_stamp=image_stamp - cmd_age_s,
                           _odom_twist=odom, _odom_stamp=image_stamp)
    return eval(_SPIN_TERM, {"_spinning_in_place": spinning, "pose_if_fresh": pose_if_fresh},
                {"self": node, "image_stamp": image_stamp})


def test_keep_mode_subscribes_the_commanded_twist_read_only():
    assert "if mode == 'keep':" in NODE and "create_subscription(Twist, 'cmd_vel', self._on_cmd_vel, 10)" in NODE
    assert "create_publisher(Twist" not in NODE
    assert "self._cmd_twist, self._cmd_stamp = (msg.linear.x, msg.angular.z)" in NODE


def test_a_slow_keep_corner_is_no_spin_although_odom_reads_still():
    # D-507 r4b: CORE commands (0.0188, 0.48); Gazebo odom reads vx ~0.001, wz 0.4.
    assert spinning((0.001, 0.4))   # the measured twist alone looks like a spin (the regression)
    assert not _node_gate(cmd=(0.0188, 0.48), odom=(0.001, 0.4))
    keeper = _drive((0.0188, 0.48))
    assert keeper.last["reason"] == "flipping"   # corner memory kept: no reset


def test_a_commanded_junction_turn_restarts_the_keeper():
    assert _node_gate(cmd=(0.0, 0.5), odom=(0.0, 0.5))
    assert _node_gate(cmd=(0.0, -0.5), odom=None)   # the command decides, not odom


def test_a_stale_command_restarts_nothing():
    assert not _node_gate(cmd=(0.0, 0.5), odom=(0.0, 0.5), cmd_age_s=ODOM_MAX_SKEW_S + 0.05)
    assert not _node_gate(cmd=None, odom=(0.0, 0.5))


def test_trade_a_weave_while_standing_still_and_turning_is_not_held_until_the_robot_moves():
    """Accepted trade (D-507 SIM r2): a low-confidence weave in place (vx ~ 0, |wz| > 0.15) restarts the
    keeper every frame, so the flipping hold does not build there; once vx > 0.01 the hold arms again."""
    keeper = _drive((0.0, 0.5))
    assert keeper.last.get("reason") != "flipping"
    _drive((0.02, 0.5), keeper)
    assert keeper.last["reason"] == "flipping"


def test_a_stale_spin_twist_restarts_nothing():
    # A command older than ODOM_MAX_SKEW_S is no motion evidence (pose_if_fresh, as the node gate uses it).
    keeper = _drive((0.0, 0.7), skew_s=ODOM_MAX_SKEW_S + 0.05)
    assert keeper.last["reason"] == "flipping"
    assert _drive((0.0, 0.7), skew_s=ODOM_MAX_SKEW_S - 0.05).last.get("reason") != "flipping"
