"""D-507 SIM round 2, root cause 1: a spin in place must not leave the keeper's flipping hold latched."""
from pathlib import Path

import pytest

from control.sensing.perception.keep_pivot import release_flip_on_pivot
from control.sensing.perception.lane_keep import LaneKeeper
from test_lane_keep import GROUND, HALF, X_OFFSET, _render

PKG = Path(__file__).resolve().parents[1]
#: The view sweeping past a lone line during the turn: hard left, hard right, ...
SWEEP = [_render([(0.035, 0.0)]), _render([(-0.035, 0.0)])] * 2
#: After the turn, on the ring: one line in view.
RING = _render([(HALF, 0.0)])


def _drive(twist):
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, corner_turning=True)
    for frame in SWEEP:
        release_flip_on_pivot(keeper, twist)
        keeper.update(frame, GROUND, lane_half_width_m=HALF)
    return keeper


@pytest.mark.parametrize("wz", [0.7, -0.3])
def test_a_spin_in_place_does_not_latch_the_flipping_hold(wz):
    keeper = _drive((0.0, wz))
    assert keeper.last.get("reason") != "flipping"
    release_flip_on_pivot(keeper, (0.0, 0.0))   # the turn has ended; CORE wants the line
    assert keeper.update(RING, GROUND, lane_half_width_m=HALF) is not None


@pytest.mark.parametrize("twist", [(0.03, 0.5), (0.0, 0.1), None])
def test_weaving_while_driving_or_without_fresh_odometry_still_holds(twist):
    # Hard steering always moves forward (vx > 0); a slow wz is no spin; no odom is the old keeper.
    keeper = _drive(twist)
    assert keeper.last["reason"] == "flipping"
    assert keeper.update(RING, GROUND, lane_half_width_m=HALF) is None


def test_keep_mode_subscribes_odometry_and_releases_before_the_keeper_update():
    source = (PKG / "control" / "line_observer_node.py").read_text(encoding="utf-8")
    assert "mode in ('lane', 'edge_left', 'centre', 'keep', 'route_a', 'route_b', 'route_ab')" in source
    assert "self._odom_twist = (float(msg.twist.twist.linear.x), self._odom_wz)" in source
    keep = source.split("elif mode == 'keep':", 1)[1]
    release = keep.index("release_flip_on_pivot(self._lane_keeper, pose_if_fresh(self._odom_twist, self._odom_stamp, image_stamp))")
    assert release < keep.index("self._lane_keeper.update(")


def test_a_hold_latched_before_odometry_shows_the_spin_is_released_by_it():
    keeper = _drive(None)   # the sweep began before odom wz crossed PIVOT_MIN_WZ
    assert keeper.last["reason"] == "flipping"
    assert release_flip_on_pivot(keeper, (0.0, 0.7)) is True
    assert keeper.update(RING, GROUND, lane_half_width_m=HALF) is not None
