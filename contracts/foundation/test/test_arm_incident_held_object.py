"""Held object: a box stuck in the jaws is machine clearable only with a fresh steady jaw read and a bound verdict."""
import json
from pathlib import Path

import pytest

from core_common.protocol.arm_incident.arm_incidents import ArmHeldVerdict, ArmIncidentClear, machine_clearable

INCIDENT = json.loads((Path(__file__).parent / "fixtures" / "held_object" / "20261119T163401-arm_a.json")
                      .read_text(encoding="utf-8"))
FACTS = INCIDENT["facts"]
ID, SINCE, NOW = "a" * 32, 1000.0, 1100.0
TOP, WRIST = "1" * 64, "2" * 64
BINDING = ("arm_a", "AB" * 8)
MOTORS = {m: 0 for m in ("11", "12", "13", "14", "15", "16")}
HOME = {j: 0.2 for j in ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")}


def read(**over):
    return {"arm": "arm_a", "board_serial": "AB" * 8, "incident_id": ID, "at": 1050.0, "first_at": 1044.0,
            "torque_after": MOTORS, "hardware_error": MOTORS, "folded": True, "max_home_err": 0.5,
            "home_err": HOME, "first_home_err": HOME, "gripper_pos": 54.07, "first_gripper_pos": 54.0,
            "frames": [{"role": "top", "sha256": TOP}, {"role": "wrist", "sha256": WRIST}], **over}


def verdict(**over):
    return {"incident_id": ID, "evaluated_at": 1060.0, "frame_sha256": {"top": TOP, "wrist": WRIST},
            "in_jaws": "one_box", "single_object": "yes", "box_cells": 3, "person_in_view": "no",
            "foreign_in_jaws": "no", "arm_body_clear": "yes", "model": "qwen3-vl", **over}


def ask(facts=FACTS, remeasured=None, v=None, stills=frozenset({TOP, WRIST}), **over):
    args = {"since": SINCE, "now": NOW, "incident_id": ID, "binding": BINDING, "verdict": v, "stills": stills, **over}
    return machine_clearable(facts, remeasured, **args)


def test_the_real_incident_passes_the_pregate_but_not_without_fresh_evidence():
    ok, why = ask()
    assert ok is False and why.startswith("box in the jaws: no valid remeasure")
    assert ask(remeasured=read())[1] == "box in the jaws: no valid picture verdict"
    assert ask(v=verdict())[1] == "box in the jaws: no valid remeasure"
    assert machine_clearable(FACTS) == (False, "box in the jaws: no valid remeasure")  # the default call too


def test_the_real_incident_clears_with_a_fresh_read_and_a_bound_verdict():
    ok, why = ask(remeasured=read(), v=verdict())
    assert ok is True and "one catalogue box" in why
    ArmIncidentClear(note="x", remeasured=read(), verdict=verdict())  # the wire models take it


@pytest.mark.parametrize("over, why", [
    ({"remeasured": read(incident_id="b" * 32)}, "not of this incident"),
    ({"remeasured": read(arm="arm_b")}, "not of this arm"),
    ({"remeasured": read(at=999.0)}, "not newer"),
    ({"remeasured": read(at=1050.0), "now": 2000.0}, "too old"),
    ({"remeasured": read(torque_after={**MOTORS, "16": 1})}, "torque ON"),
    ({"remeasured": read(folded=False)}, "not folded"),
    ({"remeasured": read(max_home_err=4.0)}, "not folded"),
    ({"remeasured": read(gripper_pos=48.8, first_gripper_pos=48.8)}, "jaw gap"),  # empty jaws
    ({"remeasured": read(gripper_pos=60.0, first_gripper_pos=60.0)}, "jaw gap"),
    ({"remeasured": read(first_gripper_pos=53.0)}, "jaw gap"),                     # still moving
    ({"remeasured": read(gripper_pos=None)}, "jaw gap"),
    ({"remeasured": read(frames=[{"role": "top", "sha256": TOP}])}, "top and one wrist"),
    ({"v": verdict(incident_id="b" * 32)}, "not of the stored stills"),
    ({"v": verdict(frame_sha256={"top": TOP, "wrist": "3" * 64})}, "not of the stored stills"),  # swapped still
    ({"stills": frozenset({TOP})}, "not of the stored stills"),                      # never uploaded
    ({"stills": None}, "not of the stored stills"),
    ({"v": verdict(evaluated_at=1040.0)}, "not fresh"),                              # before the read
    ({"v": verdict(evaluated_at=5000.0)}, "not fresh"),
    ({"v": verdict(in_jaws="other")}, "no valid picture verdict"),
    ({"v": verdict(person_in_view="unclear")}, "no valid picture verdict"),
    ({"v": verdict(arm_body_clear="no")}, "no valid picture verdict"),
    ({"v": verdict(foreign_in_jaws="yes")}, "no valid picture verdict"),
    ({"v": verdict(single_object="unclear")}, "no valid picture verdict"),
    ({"v": verdict(box_cells=0)}, "no valid picture verdict"),
    ({"v": {**verdict(), "extra": 1}}, "no valid picture verdict"),
])
def test_stale_unbound_or_unclear_evidence_is_refused(over, why):
    args = {"remeasured": read(), "v": verdict(), **over}
    ok, reason = ask(**args)
    assert ok is False and why in reason, reason


PARK = FACTS["flagged"][-1]
GRIP = FACTS["flagged"][0]


@pytest.mark.parametrize("flagged", [
    [GRIP, GRIP],                                                              # no park row
    [PARK, GRIP],                                                              # park is not last
    [GRIP, {**PARK, "command": "park"}],
    [GRIP, {**PARK, "person_needed": True}],                                   # a person_needed row
    [GRIP, {**PARK, "error": PARK["error"].replace("something is in them; held", "body; held"),
            "fault": PARK["error"].replace("something is in them; held", "body; held")}],
    [GRIP, {**PARK, "error": "contact in park: elbow_flex lag rose to 4.0 units at PWM 300 of 300 (lags: )",
            "fault": "contact in park: elbow_flex lag rose to 4.0 units at PWM 300 of 300 (lags: )"}],  # body contact
    [{**GRIP, "caught": False}, PARK], [{**GRIP, "fault": "overload"}, PARK], [{**GRIP, "person_needed": True}, PARK],
    [{**GRIP, "error": GRIP["error"] + "; a hand"}, PARK], [GRIP, {**PARK, "fault": "something else"}],  # mixed
    [GRIP, PARK, {"command": "lift", "error": "pushing: elbow lag 3.0 units"}],
    [GRIP, "not a row"],
])
def test_other_flagged_rows_stay_with_a_person(flagged):
    ok, reason = ask({**FACTS, "flagged": flagged}, read(), verdict())
    assert ok is False and "box in the jaws" not in reason


@pytest.mark.parametrize("key, value", [("stops", [{"command": "place", "error": "contact", "t": 1.0}]),
                                        ("windup_hits", [{"reason": "x"}]), ("latched", {"13": {"hw_error": 32}}),
                                        ("fault_records", ["arm_a-1.json"]), ("folded", False),
                                        ("caps_restored", False), ("safe_end", False)])
def test_any_other_fact_denies_even_with_good_evidence(key, value):
    assert ask({**FACTS, key: value}, read(), verdict())[0] is False


def test_the_verdict_model_rejects_unknown_roles():
    with pytest.raises(ValueError):
        ArmHeldVerdict.model_validate(verdict(frame_sha256={"top": TOP, "side": WRIST}))
