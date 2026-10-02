"""D-411 C: gripper state for the SIM Pilot. ROS-free and policy-only.

holding: a close goal finished but the readback stopped short of closed by more than the
tolerance -- the fingers met something. This is SIM evidence, not grip force (D-390 §5).
"""

from __future__ import annotations

#: Readback within this distance of ``closed`` counts as closed (rad).
GRIPPER_TOLERANCE_RAD = 0.05
#: Readback that changed by more than STILL_RAD within STILL_WINDOW_S is still moving.
STILL_RAD = 0.005
STILL_WINDOW_S = 0.5
_RUNNING = frozenset({"LOCAL_ACCEPTED", "ROS_ACCEPTED", "RUNNING", "CANCEL_REQUESTED"})
GRIPPER_STATES = ("open", "closed", "holding", "moving", "unknown")


def gripper_state(*, position: float | None, ready: bool, closed: float,
                  goal: dict | None, moved_recently: bool) -> str:
    """One of GRIPPER_STATES from fresh readback and the last gripper goal ``{target, state}``."""
    if not ready or position is None:
        return "unknown"
    if goal is not None and goal["state"] in _RUNNING:
        return "moving"
    if goal is not None and goal["state"] == "UNKNOWN_HOLD":
        return "unknown"
    if moved_recently:
        return "moving"
    if abs(position - closed) <= GRIPPER_TOLERANCE_RAD:
        return "closed"
    if (goal is not None and goal["state"] == "SUCCEEDED"
            and abs(goal["target"] - closed) <= GRIPPER_TOLERANCE_RAD):
        return "holding"
    return "open"
