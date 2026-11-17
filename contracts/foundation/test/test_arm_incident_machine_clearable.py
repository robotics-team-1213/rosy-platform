"""D-1039: which stored arm incident facts an AI assessor may clear without a person (default deny)."""
import json
from pathlib import Path

import pytest

from core_common.protocol.arm_incidents import machine_clearable

# the shape deploy/robot/omx/omx_incident.facts() and report_for() store, with nothing the cell's own rule holds on
SAFE = {"safe_end": True, "latched": {}, "torque_after": {"11": 0, "12": 0, "13": 0, "14": 0, "15": 0, "16": 0},
        "caps_restored": True, "folded": True, "last_state": [0, 0, 0, 0, 0, 0], "windup_hits": [], "flagged": [],
        "stop_reading": None, "stops": [], "fault_records": []}
WITHOUT = lambda key: {k: v for k, v in SAFE.items() if k != key}  # noqa: E731
# 2026-11-17 the cell's own incident.json of two real park strain stops (arm_b 07:21, arm_s 12:29), folded home with
# torque OFF afterwards. Each "run park" row carries chunk_runner_run.py's exact text in error and fault; arm_s also has
# the "state" row after it with the text in fault alone. omx_incident.facts() does not shorten either.
REAL = {path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((Path(__file__).parent / "fixtures" / "arm_incidents").glob("*.json"))}
TONIGHT = REAL["20261117T122911-arm_s"]["facts"]
PARK, STATE = TONIGHT["flagged"]
PARK_ERROR = PARK["error"]


def park(**over):
    """The real "run park" row with error and fault changed together unless one is given."""
    return {**PARK, **({"error": over["text"], "fault": over["text"]} if "text" in over else {}),
            **{k: v for k, v in over.items() if k != "text"}}


def test_a_folded_safe_end_with_torque_off_caps_restored_and_nothing_else_is_machine_clearable():
    assert machine_clearable(SAFE)[0] is True


def test_tonights_real_park_strain_incidents_are_machine_clearable():
    assert sorted(REAL) == ["20261117T072127-arm_b", "20261117T122911-arm_s"]
    for name, incident in REAL.items():
        assert incident["decision"]["hold"] is True, name  # the cell held both for a person
        assert machine_clearable(incident["facts"]) == (
            True, "park strain stop, then folded safe end, torque OFF, caps restored, nothing latched, wound up or "
                  "stopped"), name
        shown = {k: v for k, v in incident["facts"].items() if k != "frames"}  # what report_for() sends Fleet
        assert machine_clearable(json.loads(json.dumps(shown)))[0] is True, name


def test_only_park_strain_stops_are_machine_clearable_flagged_rows():
    assert machine_clearable({**SAFE, "flagged": [park(text="runner: " + PARK_ERROR)]})[0]
    assert machine_clearable({**SAFE, "flagged": [park(error=None)]})[0]  # the text in fault alone
    assert machine_clearable({**SAFE, "flagged": [park(fault="")]})[0]  # the text in error alone
    no_others = "contact in park: wrist_roll lag rose to 12.0 units at PWM 300 of 300 (lags: )"
    assert machine_clearable({**SAFE, "flagged": [park(text=no_others)]})[0]


@pytest.mark.parametrize("facts, why", [
    (None, "unreadable"), ([], "unreadable"),
    # report_for's truncated fallback keeps only safe_end, latched, torque_after and folded
    ({"safe_end": True, "latched": {}, "torque_after": {"11": 0}, "folded": True, "truncated": True}, "incomplete"),
    (WITHOUT("latched"), "incomplete"), (WITHOUT("windup_hits"), "incomplete"), (WITHOUT("flagged"), "incomplete"),
    (WITHOUT("torque_after"), "incomplete"), (WITHOUT("stops"), "incomplete"),
    (WITHOUT("fault_records"), "incomplete"), ({**SAFE, "stops": None}, "incomplete"),
    ({**SAFE, "latched": []}, "incomplete"),
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
    ({**TONIGHT, "flagged": [{**PARK, "fault": "overload latched"}]}, "flagged"),
    ({**TONIGHT, "flagged": [{**PARK, "person_needed": True}]}, "flagged"),
    ({**TONIGHT, "flagged": [park(error=None, fault=None)]}, "flagged"),
    ({**TONIGHT, "flagged": [park(fault=PARK_ERROR.replace("2.2 units", "2.3 units"))]}, "flagged"),
    ({**TONIGHT, "flagged": [park(command="park")]}, "flagged"), ({**TONIGHT, "flagged": [park(command="grip")]},
                                                                  "flagged"),
    ({**TONIGHT, "flagged": [PARK, {**STATE, "command": "fault"}]}, "flagged"),
    ({**TONIGHT, "flagged": [PARK, {**STATE, "fault": PARK_ERROR + "; a hand is in the jaws"}]}, "flagged"),
    ({**TONIGHT, "flagged": [PARK, {**STATE, "fault": "guard overload during human hold; person needed"}]},
     "flagged"),
    # the whole error is the runner's text: nothing before or after it, no other wording, ASCII only
    ({**TONIGHT, "flagged": [park(text=PARK_ERROR + "; a hand is in the jaws")]}, "flagged"),
    ({**TONIGHT, "flagged": [park(text=PARK_ERROR + "\nCAUGHT")]}, "flagged"),
    ({**TONIGHT, "flagged": [park(text=PARK_ERROR + " Caught")]}, "flagged"),
    ({**TONIGHT, "flagged": [park(text="note: " + PARK_ERROR)]}, "flagged"),
    ({**TONIGHT, "flagged": [park(text=PARK_ERROR.replace("(lags: shoulder_pan", "(lags: a hand"))]}, "flagged"),
    ({**TONIGHT, "flagged": [park(text=PARK_ERROR[:-30])]}, "flagged"),  # a cut tail is not the runner's text
    ({**TONIGHT, "flagged": [park(text=PARK_ERROR.replace("2.2", chr(0x662) + ".2"))]}, "flagged"),
    ({**TONIGHT, "flagged": [park(text=PARK_ERROR.replace("PWM -321", "PWM None"))]}, "flagged"),
    ({**TONIGHT, "flagged": [park(text="contact in park: the jaws stopped 5.0 units short at PWM -248 of 300: "
                                       "something is in them")]}, "flagged"),
    ({**TONIGHT, "flagged": [park(text=PARK_ERROR.replace("in park", "in place"))]}, "flagged"),
    ({**TONIGHT, "flagged": [park(text="contact in park: shoulder_lift lag rose to 2.2 units")]}, "flagged"),
    ({**TONIGHT, "flagged": [park(text="contact in park: shoulder_lift lag rose to 2.2 units at PWM -321 of 600")]},
     "flagged"),
    ({**TONIGHT, "flagged": ["not a row"]}, "flagged"),
    ({**TONIGHT, "folded": False}, "folded"), ({**TONIGHT, "torque_after": {"11": 0, "12": 1}}, "torque"),
    ({**TONIGHT, "caps_restored": None}, "caps"), ({**TONIGHT, "latched": {"12": {"hw_error": 32}}}, "latched"),
    ({**TONIGHT, "stops": [{"command": "place", "error": "contact in place: wrist lag", "t": 1.0}]}, "contact stop"),
    ({**TONIGHT, "fault_records": ["arm_s-0001.json"]}, "fault record"),
    ({**SAFE, "stops": [{"command": "place", "error": "contact in place: wrist lag", "t": 1.0}]}, "contact stop"),
    ({**SAFE, "stops": "x"}, "incomplete"),
    ({**SAFE, "fault_records": ["arm_b-0001.json"]}, "fault record"),
])
def test_everything_else_stays_with_a_person(facts, why):
    ok, reason = machine_clearable(facts)
    assert ok is False and why in reason
