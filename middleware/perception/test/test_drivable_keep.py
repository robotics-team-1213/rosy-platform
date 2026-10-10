"""keep_step republishes a committed straight corridor when the way is missing.

The steer error is unchanged while a way exists. A gap before commit, and the
frame after a crosswalk crossing, still return no steering.
"""
import pytest

from control.sensing.perception.drivable.drivable_keep import keep_step
from control.sensing.perception.drivable.drivable_steer import DrivableSteer
from test_drivable_steer import G, HALF, XO, _lane


class _Ways:
    def __init__(self, way):
        self.way = way
        self.used_crosswalk = None
        self.stamp = 0.0

    def latest_way(self, _age):
        if self.way is None:
            return None
        return self.way, self.stamp


def _pose(_stamp):
    return (0.0, 0.0, 0.0)


def _step(steer, ways, last, stamp):
    return keep_step(steer, ways, last, G, XO, HALF, _pose, stamp, None)


def _commit_centre():
    way = _lane(HALF, -HALF)
    steer, solo, ways, last = DrivableSteer(), DrivableSteer(), _Ways(way), {}
    step = None
    info = None
    for index in range(3):
        stamp = index * 0.1
        ways.stamp = stamp
        error, confidence, info = solo.update(way, stamp, G, XO, HALF, _pose(stamp), _pose(stamp))
        step, decided = _step(steer, ways, last, stamp)
    return steer, ways, last, step, decided, error, confidence, info


def test_cached_way_cannot_commit_three_frames_of_evidence():
    steer, ways, last = DrivableSteer(), _Ways(_lane(HALF, -HALF)), {}
    for stamp in (0.0, 0.1, 0.2):
        _step(steer, ways, last, stamp)
    assert last["expected_path_state"] is None
    ways.way = None
    step, decided = _step(steer, ways, last, 0.3)
    assert step is None and decided is False


def test_a_fresh_centre_way_returns_the_steer_error_and_a_live_path():
    _steer, _ways, last, step, decided, error, confidence, info = _commit_centre()
    assert info["strategy"] == "drivable_centre"
    assert decided is True
    assert step == pytest.approx((error, confidence))
    assert last["expected_path_state"] == "live"
    assert len(last["expected_path_m"]) == 2
    assert all(len(point) == 2 for point in last["expected_path_m"])


def test_a_missing_way_after_commit_holds_instead_of_the_tape_keeper():
    steer, ways, last, _step_live, _decided, _error, _confidence, _info = _commit_centre()
    ways.way = None
    step, decided = _step(steer, ways, last, 1.0)
    assert decided is True and step is not None
    assert step[1] == pytest.approx(0.90)
    assert last["strategy"] == "expected_path_held"
    assert last["expected_path_state"] == "held"
    assert len(last["expected_path_m"]) == 2
    assert last["expected_path_s_m"] == pytest.approx(0.0)
    assert last.get("reason") != "drivable_way_stale"
    # Past the steer's 1.5 s latch forget, still inside the 2.5 s path budget.
    later, later_decided = _step(steer, ways, last, 3.0)
    assert later_decided is True and later is not None
    assert last["strategy"] == "expected_path_held"


def test_a_missing_way_before_commit_stays_stale():
    way = _lane(HALF, -HALF)
    steer, ways, last = DrivableSteer(), _Ways(way), {}
    _step(steer, ways, last, 0.0)
    ways.way = None
    step, decided = _step(steer, ways, last, 0.2)
    assert step is None and decided is False
    assert last["reason"] == "drivable_way_stale"


@pytest.mark.parametrize("rejection", ["off_route", "no_source_pose"])
def test_rejected_way_drops_the_path_before_a_missing_frame(rejection):
    steer, ways, last, *_rest = _commit_centre()
    pose_at = _pose if rejection == "off_route" else lambda _stamp: None
    guide = (0.0, 0.3, True, 0.0, 0.3, 0.0) if rejection == "off_route" else None
    keep_step(steer, ways, last, G, XO, HALF, pose_at, 0.3, None, guide)
    assert last["expected_path_state"] == "dropped"
    ways.way = None
    step, decided = _step(steer, ways, last, 0.4)
    assert step is None and decided is False


def test_crosswalk_straight_then_a_missing_way_does_not_hold():
    steer, ways, last, *_rest = _commit_centre()
    ways.way = None
    last["crosswalk"] = True
    step, decided = _step(steer, ways, last, 1.0)
    assert decided is True and step == pytest.approx((0.0, 0.6))
    assert last["strategy"] == "drivable_crosswalk_straight"
    # Leaving the crossing without driving 0.35 m: that drive would also trip the 0.25 m budget.
    last.pop("crosswalk", None)
    steer._crosswalk_pose = None
    step, decided = _step(steer, ways, last, 1.2)
    assert step is None and decided is False
    assert last["reason"] == "drivable_way_stale"


def test_reset_forgets_a_committed_path():
    steer, ways, last, *_rest = _commit_centre()
    steer.reset()
    ways.way = None
    step, decided = _step(steer, ways, last, 1.0)
    assert step is None and decided is False
    assert last["reason"] == "drivable_way_stale"
