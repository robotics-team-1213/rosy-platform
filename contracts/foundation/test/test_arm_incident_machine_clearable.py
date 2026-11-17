"""D-1039: which stored arm incident facts an AI assessor may clear without a person."""
import pytest

from core_common.protocol.arm_incidents import machine_clearable

# the shape deploy/robot/omx/omx_incident.facts() stores; 2026-11-17: contact in park, then folded home torque OFF
SAFE = {"safe_end": True, "latched": {}, "torque_after": {"11": 0, "12": 0, "13": 0, "14": 0, "15": 0, "16": 0},
        "caps_restored": True, "folded": True, "last_state": [0, 0, 0, 0, 0, 0], "windup_hits": [],
        "flagged": [{"command": "park", "error": "contact in park: shoulder_lift lag rose to 2.2 units at PWM -321",
                     "fault": None, "caught": None, "t": 3.2}], "stops": [], "fault_records": [], "frames": []}


def test_a_folded_safe_end_with_torque_off_and_nothing_physical_is_machine_clearable():
    assert machine_clearable(SAFE)[0] is True
    assert machine_clearable({**SAFE, "flagged": []})[0] is True


@pytest.mark.parametrize("facts, why", [
    (None, "unreadable"), ([], "unreadable"), ({**SAFE, "truncated": True}, "truncated"),
    ({**SAFE, "folded": False}, "folded"), ({k: v for k, v in SAFE.items() if k != "folded"}, "folded"),
    ({**SAFE, "safe_end": False}, "safe end"),
    ({**SAFE, "torque_after": {}}, "torque"), ({**SAFE, "torque_after": None}, "torque"),
    ({**SAFE, "torque_after": {"11": 1}}, "torque"), ({**SAFE, "torque_after": {"11": True}}, "torque"),
    ({**SAFE, "torque_after": {"11": "error: no reply"}}, "torque"),
    ({**SAFE, "latched": {"13": {"hw_error": 32, "bits": ["overload"]}}}, "latched"),
    ({**SAFE, "windup_hits": [{"reason": "elbow wound up"}]}, "wind-up"),
    ({**SAFE, "flagged": [{"error": "jaws caught", "caught": True}]}, "caught"),
    ({**SAFE, "flagged": ["not a row"]}, "caught"),
])
def test_everything_else_stays_with_a_person(facts, why):
    ok, reason = machine_clearable(facts)
    assert ok is False and why in reason
