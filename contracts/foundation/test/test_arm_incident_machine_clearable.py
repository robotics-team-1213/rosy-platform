"""D-1039: which stored arm incident facts an AI assessor may clear without a person (default deny)."""
import pytest

from core_common.protocol.arm_incidents import machine_clearable

# the shape deploy/robot/omx/omx_incident.facts() and report_for() store, with nothing the cell's own rule holds on
SAFE = {"safe_end": True, "latched": {}, "torque_after": {"11": 0, "12": 0, "13": 0, "14": 0, "15": 0, "16": 0},
        "caps_restored": True, "folded": True, "last_state": [0, 0, 0, 0, 0, 0], "windup_hits": [], "flagged": [],
        "stop_reading": None, "stops": [], "fault_records": []}
WITHOUT = lambda key: {k: v for k, v in SAFE.items() if k != key}  # noqa: E731
# 2026-11-17 night, arm_s: the runner's strain stop while parking, then folded home with torque OFF. This is the row
# omx_incident.facts() keeps (command, error, fault, caught, t); the cell holds on it and reports it to Fleet.
PARK = {"command": "park", "error": "contact in park: shoulder_lift lag rose to 2.2 units at PWM -321 of 600",
        "fault": None, "caught": None, "t": 3.2}
TONIGHT = {**SAFE, "flagged": [PARK]}


def test_a_folded_safe_end_with_torque_off_caps_restored_and_nothing_else_is_machine_clearable():
    assert machine_clearable(SAFE)[0] is True
    assert machine_clearable(WITHOUT("stops"))[0] is True  # older reports have no stops list
    assert machine_clearable(WITHOUT("fault_records"))[0] is True


def test_only_park_strain_stops_are_machine_clearable_flagged_rows():
    assert machine_clearable(TONIGHT) == (
        True, "park strain stop, then folded safe end, torque OFF, caps restored, nothing latched, wound up or stopped")
    assert machine_clearable({**SAFE, "flagged": [PARK, {**PARK, "error": "runner: " + PARK["error"] + " (2nd)"}]})[0]
    assert machine_clearable({**SAFE, "flagged": [{**PARK, "error": None, "fault": PARK["error"]}]})[0]


@pytest.mark.parametrize("facts, why", [
    (None, "unreadable"), ([], "unreadable"),
    # report_for's truncated fallback keeps only safe_end, latched, torque_after and folded
    ({"safe_end": True, "latched": {}, "torque_after": {"11": 0}, "folded": True, "truncated": True}, "incomplete"),
    (WITHOUT("latched"), "incomplete"), (WITHOUT("windup_hits"), "incomplete"), (WITHOUT("flagged"), "incomplete"),
    (WITHOUT("torque_after"), "incomplete"), ({**SAFE, "latched": []}, "incomplete"),
    ({**SAFE, "flagged": {}}, "incomplete"), ({**SAFE, "windup_hits": None}, "incomplete"),
    ({**SAFE, "folded": False}, "folded"), (WITHOUT("folded"), "folded"), ({**SAFE, "safe_end": False}, "safe end"),
    ({**SAFE, "torque_after": {}}, "torque"), ({**SAFE, "torque_after": {"11": 1}}, "torque"),
    ({**SAFE, "torque_after": {"11": True}}, "torque"), ({**SAFE, "torque_after": {"11": "error: no reply"}}, "torque"),
    ({**SAFE, "caps_restored": ["ID 13 pwm_limit"]}, "caps"), ({**SAFE, "caps_restored": False}, "caps"),
    (WITHOUT("caps_restored"), "caps"),
    ({**SAFE, "latched": {"13": {"hw_error": 32, "bits": ["overload"]}}}, "latched"),
    ({**SAFE, "windup_hits": [{"reason": "elbow wound up"}]}, "wind-up"),
    ({**SAFE, "flagged": [{"error": "jaws caught", "caught": True}]}, "flagged"),
    # tonight's park strain plus anything else, or the park row itself changed, stays with a person
    ({**TONIGHT, "flagged": [PARK, {"command": "grip", "error": "jaws caught", "caught": True}]}, "flagged"),
    ({**TONIGHT, "flagged": [PARK, {"command": "lift", "error": "pushing: elbow lag 3.0 units"}]}, "flagged"),
    ({**TONIGHT, "flagged": [PARK, {"command": "park", "error": "session ended: alignment deadline exceeded"}]},
     "flagged"),
    ({**TONIGHT, "flagged": [{**PARK, "caught": True}]}, "flagged"),
    ({**TONIGHT, "flagged": [{**PARK, "fault": "pushing: wrist"}]}, "flagged"),
    ({**TONIGHT, "flagged": [{**PARK, "error": "contact in park: the jaws stopped 5.0 units short at PWM -248 of 300: "
                                               "something is in them"}]}, "flagged"),
    ({**TONIGHT, "flagged": [{**PARK, "error": "contact in place: shoulder_lift lag rose to 2.2 units at PWM -321 "
                                               "of 600"}]}, "flagged"),
    ({**TONIGHT, "flagged": [{**PARK, "error": "contact in park: shoulder_lift lag rose to 2.2 units"}]}, "flagged"),
    ({**TONIGHT, "flagged": ["not a row"]}, "flagged"),
    ({**TONIGHT, "folded": False}, "folded"), ({**TONIGHT, "torque_after": {"11": 0, "12": 1}}, "torque"),
    ({**TONIGHT, "caps_restored": None}, "caps"), ({**TONIGHT, "latched": {"12": {"hw_error": 32}}}, "latched"),
    ({**TONIGHT, "stops": [{"command": "place", "error": "contact in place: wrist lag", "t": 1.0}]}, "contact stop"),
    ({**TONIGHT, "fault_records": ["arm_s-0001.json"]}, "fault record"),
    ({**SAFE, "stops": [{"command": "place", "error": "contact in place: wrist lag", "t": 1.0}]}, "contact stop"),
    ({**SAFE, "stops": "x"}, "contact stop"),
    ({**SAFE, "fault_records": ["arm_b-0001.json"]}, "fault record"),
])
def test_everything_else_stays_with_a_person(facts, why):
    ok, reason = machine_clearable(facts)
    assert ok is False and why in reason
