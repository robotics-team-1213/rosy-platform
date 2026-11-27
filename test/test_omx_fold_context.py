"""The automatic fold orders its candidates by the record of its own situation once it has a few tries there."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts" / "foundation"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_auto_fold as af  # noqa: E402
from cell_choices import Choices  # noqa: E402

HOME = [0.8, -62.2, 53.0, 51.9, 44.6, 48.8]
NAMES = ["park", "lift_then_park", "lift_pan+10", "lift_pan-10", "elbow_in_then_park"]


OVERLOAD_1515 = "overload: shoulder_lift Present_PWM=-885 PWM_Limit=885; arm resting on the belt"
PUSHING_1530 = "PUSHING_1530: elbow_flex pushing past its target"


def test_fold_context_buckets_by_the_hold_reason_and_lift_distance():
    assert af.fold_context([0, 10.0, 0, 0, 0], HOME, OVERLOAD_1515) == "supported/far"
    assert af.fold_context([0, -40.0, 0, 0, 0], HOME, PUSHING_1530) == "supported/near"
    assert af.fold_context([0, -40.0, 0, 0, 0], HOME, "stall on wrist_flex") == "contact/near"
    contact_1651 = "contact in policy: wrist_flex lag rose to 2.3 units at PWM -214 of 300"  # the shoulder carried the arm
    assert af.fold_context([0, 10.0, 0, 0, 0], HOME, contact_1651) == "contact/far"
    assert af.fold_context([0, 10.0, 0, 0, 0], HOME, "contact in policy: shoulder_lift lag rose to 2.2 units") == "contact/far"
    assert af.fold_context([0, 10.0, 0, 0, 0], HOME, None) == "unknown-support/far"  # 16:51 human hold, no reason
    assert af.fold_context([0, -40.0, 0, 0, 0], HOME, "") == "unknown-support/near"
    reasons = (None, OVERLOAD_1515)
    assert len({af.fold_context([0, lift, 0, 0, 0], HOME, r) for lift in range(-90, 60, 5) for r in reasons}) == 4


class _Cell:
    def __init__(self, fault=None):
        self.fault = fault

    def act(self, command):
        if command.split()[0] == "park":
            return {"ok": True, "settled": True, "state": list(HOME), "target": list(HOME)}
        state = [20.0, 10.0, 20.0, 45.0, -5.0, 48.8]
        return {"ok": True, "state": state, "target": state, "fault": self.fault,
                "health": {"pwm": [3, -600, 210, -90, 0, 0], "current_ma": [0] * 6}}


def _fold(cell, **kw):
    contexts = []
    out = af.recover(cell, HOME, 48.8, plan=lambda s: [s, HOME], look=lambda f: {"clear": True}, reserve=lambda f: {"ok": True},
                     release=lambda: None, release_and_rise=lambda c: {"result": "risen"}, low=lambda s: True,
                     order=lambda n, ctx: contexts.append(ctx) or n, sleep=lambda s: None, **kw)
    return out, contexts


def test_the_result_records_the_start_and_the_hold_reason_and_orders_by_it():
    out, contexts = _fold(_Cell(), hold_reason=OVERLOAD_1515)
    assert out["result"] == "folded" and out["context"] == contexts[0] == "supported/far"
    assert out["state_start"] == [20.0, 10.0, 20.0, 45.0, -5.0, 48.8] and out["start_pwm"] == [3, -600, 210, -90, 0, 0]
    assert out["hold_reason"] == OVERLOAD_1515
    live, contexts = _fold(_Cell(fault=PUSHING_1530))  # no reason given: the live hold's own fault
    assert live["context"] == contexts[0] == "supported/far" and live["hold_reason"] == PUSHING_1530
    bare, _ = _fold(_Cell())
    assert bare["context"] == "unknown-support/far" and bare["hold_reason"] is None


def test_an_incident_fold_reads_the_hold_reason_from_the_incident_facts(tmp_path, monkeypatch):
    import json

    import chunk_runner_recover as crr
    import omx_incident

    monkeypatch.setattr(omx_incident, "INCIDENTS", tmp_path)
    assert crr.incident_hold_reason("arm_a") is None
    (tmp_path / "20261127-151500-arm_a").mkdir()
    (tmp_path / "20261127-151500-arm_a" / "incident.json").write_text(json.dumps(
        {"facts": {"flagged": [{"fault": OVERLOAD_1515, "error": None}]}}))
    assert crr.incident_hold_reason("arm_a") == OVERLOAD_1515
    assert af.fold_context([0, 10.0, 0, 0, 0], HOME, crr.incident_hold_reason("arm_a")) == "supported/far"


def test_start_load_records_predicted_gravity_and_the_measured_ratio(monkeypatch):
    import load_predict

    monkeypatch.setattr(load_predict, "gravity_pwm", lambda arm, pose: {"shoulder_lift": -300.0, "elbow_flex": 0.4})
    rec = load_predict.start_load({}, [0] * 6, [3, -600, 210, -90, 0, 0])
    assert rec == {"gravity_pwm_expected": {"shoulder_lift": -300.0, "elbow_flex": 0.4}, "pwm_ratio": {"shoulder_lift": 2.0}}
    assert load_predict.start_load({}, [0] * 6, None)["pwm_ratio"] == {}
    for bad in ([3], [3, None, 210, -90]):  # short or broken health.pwm: a record, never an error that holds a finished fold
        assert load_predict.start_load({}, [0] * 6, bad) == {"gravity_pwm_expected": None, "pwm_ratio": None}


def test_two_contexts_learn_different_orders_and_an_unseen_one_keeps_the_global_order(tmp_path):
    path = tmp_path / "choices.json"
    seed = Choices(path)
    for name in NAMES:
        seed.offer(af.CHOICE, name, "D-1048")
    seed.save()

    def learn(context, name, ok):
        af._learn({"choices_path": str(path), "candidate": name, "result": "folded" if ok else "held", "context": context}, ok)

    for _ in range(3):  # resting low far out: lift overloads, the forearm-in fold works
        learn("supported/far", "lift_then_park", False)
        learn("supported/far", "elbow_in_then_park", True)
    for _ in range(4):  # no reason, near: lift_pan-10 works
        learn("unknown-support/near", "lift_pan-10", True)
    ch = Choices(path)
    global_order = ch.ranked(af.CHOICE, NAMES)
    low_far = ch.ranked_in_context(af.CHOICE, NAMES, "supported/far")
    high_near = ch.ranked_in_context(af.CHOICE, NAMES, "unknown-support/near")
    assert low_far[0] == "elbow_in_then_park" and low_far[-1] == "lift_then_park"
    assert high_near[0] == "lift_pan-10" and low_far != high_near
    assert ch.ranked_in_context(af.CHOICE, NAMES, "unknown-support/far") == global_order  # never seen: the global record
    assert ch.ranked_in_context(af.CHOICE, NAMES, None) == global_order
    assert sorted(low_far) == sorted(high_near) == sorted(NAMES)  # only the order changes, never the set


def test_a_context_with_too_few_tries_falls_back_to_the_global_order(tmp_path):
    ch = Choices(tmp_path / "choices.json")
    for name in NAMES:
        ch.offer(af.CHOICE, name, "D-1048")
    for _ in range(3):
        ch.outcome(af.CHOICE, "lift_pan+10", True)
    ch.offer(f"{af.CHOICE}@supported/near", "park", "D-1048")
    ch.outcome(f"{af.CHOICE}@supported/near", "park", True)  # one try is not enough to override the global record
    assert ch.ranked_in_context(af.CHOICE, NAMES, "supported/near") == ch.ranked(af.CHOICE, NAMES)
    assert ch.ranked_in_context(af.CHOICE, NAMES, "supported/near")[0] == "lift_pan+10"
