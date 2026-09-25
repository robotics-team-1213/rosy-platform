from core_common.capability import Capability, CapabilityError
from core_common.domain.tasks import TaskKind


def test_navigate_requires_goal_navigation():
    cap = Capability({"navigation": {"goal_navigation": False}, "teleop": True, "docking": {"supported": False}})
    try:
        TaskKind.NAVIGATE.require(cap)
    except CapabilityError as exc:
        assert exc.feature == "navigation.goal_navigation"
    else:
        raise AssertionError("NAVIGATE must fail closed")


def test_move_requires_teleop():
    cap = Capability({"teleop": True, "navigation": {"goal_navigation": False}})
    TaskKind.MOVE.require(cap)
