"""D-1047: a session that ended on the bus link alone, the runner standing still near home with torque confirmed OFF,
is machine-clearable; the rule recomputes the rest from the reported numbers and every other kind stays as before."""
import json
from pathlib import Path

from core_common.protocol.arm_incidents import machine_clearable

REAL = json.loads((Path(__file__).parent / "fixtures" / "arm_incidents_link" / "20261118T232302-arm_s.json")
                  .read_text(encoding="utf-8"))["facts"]
ROW = REAL["flagged"][0]
TEXT = ROW["fault"]


def test_the_real_link_failure_on_a_resting_torque_off_arm_is_machine_clearable():
    ok, why = machine_clearable(REAL)
    assert ok is True and why.startswith("bus link failure, then rested near home")


def test_a_boolean_from_the_cell_is_not_trusted():
    assert machine_clearable({**REAL, "rested": True, "last_state": [30.0, -20.0, 20.0, 50.0, -5.0, 49.0],
                              "last_target": [30.0, -20.0, 20.0, 50.0, -5.0, 49.0]})[0] is False


def test_the_arm_must_have_stood_still_near_home_with_torque_off():
    moving = {**REAL, "last_target": [10.0, -40.0, 40.0, 50.0, -5.0, 49.0]}  # link went mid-move: last_state is stale
    assert machine_clearable(moving)[0] is False
    assert machine_clearable({**REAL, "last_command": "run descend_pick"})[0] is False
    assert machine_clearable({**REAL, "last_command": "goto above_pick"})[0] is False
    assert machine_clearable({**REAL, "last_command": "something new"})[0] is False  # unknown labels fail closed
    mid_move = {**REAL, "flagged": [{**ROW, "command": "run descend_pick"}]}  # the link went during a chunk
    assert machine_clearable(mid_move)[0] is False
    assert machine_clearable({**REAL, "home": [0.0, -58.0, 40.0, 50.0, -5.0, 48.8]})[0] is False  # 15.9 from home
    assert machine_clearable({**REAL, "torque_after": {**REAL["torque_after"], "13": 1}})[0] is False
    assert machine_clearable({k: v for k, v in REAL.items() if k != "home"})[0] is False


def test_only_the_exact_runner_text_counts_as_a_link_failure():
    for text in ("collision detected Input/output error", "stalled at wrist, jammed; Input/output error",
                 "object blocked gripper, Port is in use", "Present_Temperature 90 overheating; Port is in use",
                 TEXT + " contact", "note: " + TEXT, TEXT.replace("Port is in use!", "Overload!"),
                 TEXT.replace("id_=11", "id_=21")):
        assert machine_clearable({**REAL, "flagged": [{**ROW, "fault": text}]})[0] is False, text
    assert machine_clearable({**REAL, "flagged": [{**ROW, "caught": True}]})[0] is False
    assert machine_clearable({**REAL, "flagged": [{**ROW, "person_needed": True}]})[0] is False


def test_fault_records_must_be_exactly_the_link_failure_and_complete():
    for kind in ({"fault": "Present_Temperature high Input/output error", "stop_reasons": []},
                 {"fault": "(5, 'Input/output error')", "stop_reasons": ["overload"]},
                 {"fault": "overheating", "stop_reasons": []}):
        assert machine_clearable({**REAL, "fault_record_kinds": [kind]})[0] is False, kind
    assert machine_clearable({**REAL, "fault_record_kinds": []})[0] is False
    assert machine_clearable({**REAL, "fault_records_total": 4})[0] is False  # the report sent only the last ones
    assert machine_clearable({**REAL, "flagged_total": 6})[0] is False


def test_rest_is_for_link_failures_only():
    park = {"command": "run park", "fault": "contact in park: shoulder_lift lag rose to 2.2 units at PWM -321 of 600 "
                                            "(lags: shoulder_pan 0.1)", "error": None, "caught": None}
    assert machine_clearable({**REAL, "flagged": [park], "fault_records": [], "fault_record_kinds": [],
                              "fault_records_total": 0})[0] is False  # park strain still needs folded (HOME_TOL)
    assert machine_clearable({**REAL, "flagged": [], "flagged_total": 0, "fault_records": [],
                              "fault_record_kinds": [], "fault_records_total": 0})[0] is False
    assert machine_clearable({**REAL, "flagged": [ROW, park], "flagged_total": 2})[0] is False
    assert machine_clearable({**REAL, "latched": {"13": {"hw_error": 32}}})[0] is False
    assert machine_clearable({**REAL, "stops": [{"command": "place", "error": "contact in place", "t": 1.0}]})[0] is False
