"""A closed dispatch latch alone is DISPATCH_REARM_REQUIRED, not HUMAN_HOLD; real hazards stay HUMAN_HOLD."""
import pytest

from fleet.server.trip_ports import TripError
from fleet.server.trip_runner import TripRunner


def _runner(state):
    r = object.__new__(TripRunner)
    r.human_hold_fn = lambda: state() is not None
    r.hold_state_fn = state
    return r


def test_restart_latch_reports_rearm_required():
    ctrl = {"dispatch_enabled": False, "reason": "PROCESS_RESTARTED", "rearm_available": True,
            "queued_tasks": 0, "unresolved_actions": 0}
    r = _runner(lambda: ("DISPATCH_REARM_REQUIRED", ctrl))
    with pytest.raises(TripError) as e:
        r._check_human_hold()
    assert e.value.code == "DISPATCH_REARM_REQUIRED" and e.value.detail["rearm_available"] is True


def test_real_hazard_stays_human_hold():
    r = _runner(lambda: ("HUMAN_HOLD", {}))
    with pytest.raises(TripError) as e:
        r._check_human_hold()
    assert e.value.code == "HUMAN_HOLD"
