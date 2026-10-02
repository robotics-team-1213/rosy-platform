"""D-411 C: gripper state from readback and the last gripper goal."""

import pytest

from omx_adapter.pilot_sim_gripper import GRIPPER_TOLERANCE_RAD, gripper_state

CLOSED = 0.0


def state(position, *, ready=True, goal=None, moved=False):
    return gripper_state(position=position, ready=ready, closed=CLOSED, goal=goal, moved_recently=moved)


def test_unknown_without_fresh_readback():
    assert state(None) == "unknown" and state(0.0, ready=False) == "unknown"


@pytest.mark.parametrize("goal_state", ["LOCAL_ACCEPTED", "ROS_ACCEPTED", "RUNNING", "CANCEL_REQUESTED"])
def test_moving_while_a_goal_runs(goal_state):
    assert state(0.4, goal={"target": CLOSED, "state": goal_state}) == "moving"


def test_moving_when_readback_still_changes():
    assert state(0.4, moved=True) == "moving"


def test_closed_and_open():
    assert state(CLOSED + GRIPPER_TOLERANCE_RAD / 2) == "closed"
    assert state(1.0) == "open" and state(0.5) == "open"


def test_holding_when_a_finished_close_stops_short():
    goal = {"target": CLOSED, "state": "SUCCEEDED"}
    assert state(0.3, goal=goal) == "holding"
    assert state(CLOSED, goal=goal) == "closed"
    assert state(CLOSED + GRIPPER_TOLERANCE_RAD * 1.5, goal=goal) == "holding"


def test_a_finished_half_goal_is_open_not_holding():
    assert state(0.5, goal={"target": 0.5, "state": "SUCCEEDED"}) == "open"


def test_canceled_close_is_not_holding():
    assert state(0.3, goal={"target": CLOSED, "state": "CANCELED"}) == "open"


def test_hold_terminal_is_unknown():
    assert state(0.3, goal={"target": CLOSED, "state": "UNKNOWN_HOLD"}) == "unknown"
