"""D-1040: two incident kinds a machine clears only on a fresh, quiet read of the arm taken after the incident."""
import json
from pathlib import Path

import pytest

from core_common.protocol.arm_incident.arm_incidents import (
    PORT_LOST_FAULT, STALE_EFFORT_FAULT, ArmIncidentClear, classify, machine_clearable,
)

# 2026-11-17 the cell's own incident.json (fault records as report_for sends them, frames left out): arm_b 17:10 lost
# its port writing torque OFF during a USB hub re-enumeration; arm_a 18:37 wound up holding home under an orphan session
REAL = {path.stem: json.loads(path.read_text(encoding="utf-8"))["facts"]
        for path in sorted((Path(__file__).parent / "fixtures" / "arm_incidents_remeasure").glob("*.json"))}
PORT, WINDUP = REAL["20261117T171027-arm_b"], REAL["20261117T182025-arm_a"]
SINCE, NOW = 1000.0, 1300.0  # the incident's reported_at on Fleet, and the clear
ZERO = {m: 0 for m in ("11", "12", "13", "14", "15", "16")}
INCIDENT, BOARD = "c" * 32, "7F31D1FE50323952582E3120FF061D2D"  # the incident cleared; Fleet's manifest (arm, board)
# arm_b's one fault record of that port loss, as the cell reads it again (the report sends Fleet only its name)
LOST = {"name": PORT["fault_records"][0], "fault_type": PORT_LOST_FAULT[0], "fault": PORT_LOST_FAULT[1]}
READ = {"arm": "arm_b", "board_serial": BOARD, "incident_id": INCIDENT, "at": 1200.0, "torque_after": ZERO,
        "hardware_error": ZERO, "folded": True, "max_home_err": 0.4,
        "frames": [{"role": "top", "sha256": "a" * 64}, {"role": "side", "sha256": "b" * 64}], "fault_records": [LOST]}


def clearable(facts, read=READ, since=SINCE, now=NOW, incident_id=INCIDENT, binding=("arm_b", BOARD)):
    return machine_clearable(facts, read, since=since, now=now, incident_id=incident_id, binding=binding)


def test_both_real_incidents_clear_on_a_quiet_fresh_read_and_never_without_one():
    assert sorted(REAL) == ["20261117T171027-arm_b", "20261117T182025-arm_a"]
    assert clearable(PORT) == (True, "torque OFF not confirmed (port in use), then a fresh read: every motor torque OFF "
                                     "with no hardware error, folded at home")
    assert clearable(WINDUP)[0] is True and clearable(WINDUP)[1].startswith("wind-up before the end, then")
    for facts in REAL.values():
        assert machine_clearable(facts)[0] is False  # the D-1039 path alone still refuses them
        assert clearable(facts, None)[0] is False and "no valid remeasure" in clearable(facts, None)[1]
    # the port-busy kind: the session could not confirm torque OFF; the fresh read does
    assert clearable({**PORT, "torque_after": {}})[0] is True
    assert clearable({**PORT, "torque_after": {"11": "error: port in use"}})[0] is True
    assert ArmIncidentClear.model_validate({"note": "x", "remeasured": READ}).remeasured.folded is True


@pytest.mark.parametrize("read, why", [
    ({**READ, "torque_after": {**ZERO, "13": 1}}, "torque ON"),
    ({**READ, "hardware_error": {**ZERO, "12": 32}}, "hardware error"),
    ({**READ, "folded": False}, "not folded"),
    ({**READ, "max_home_err": 3.5}, "not folded"),  # the cell's own fold tolerance, whatever it says
    ({**READ, "at": SINCE}, "not newer"), ({**READ, "at": SINCE - 1}, "not newer"),
    ({**READ, "at": NOW + 61}, "not newer"),  # from the future beyond clock skew
    ({**READ, "at": NOW - 901}, "not newer"),  # older than the incident here too
    (None, "no valid remeasure"), ({}, "no valid remeasure"),
    ({**READ, "torque_after": {k: v for k, v in ZERO.items() if k != "16"}}, "no valid remeasure"),
    ({**READ, "torque_after": {**ZERO, "17": 0}}, "no valid remeasure"),
    ({**READ, "torque_after": {**ZERO, "11": False}}, "no valid remeasure"),
    ({**READ, "folded": "true"}, "no valid remeasure"),
    ({**READ, "frames": []}, "no valid remeasure"),
    ({**READ, "extra": 1}, "no valid remeasure"),
    ({k: v for k, v in READ.items() if k != "hardware_error"}, "no valid remeasure"),
    ({k: v for k, v in READ.items() if k != "arm"}, "no valid remeasure"),
    # bound to the arm and board of the incident's source, and to this incident
    ({**READ, "arm": "arm_a"}, "not of this arm"),
    ({**READ, "board_serial": "2B162C9B50323952582E3120FF06202D"}, "not of this arm"),
    ({**READ, "incident_id": "d" * 32}, "not of this incident"), ({**READ, "incident_id": None}, "not of this incident"),
])
def test_a_read_that_is_not_quiet_fresh_and_whole_is_refused(read, why):
    for facts in REAL.values():
        ok, reason = clearable(facts, read)
        assert ok is False and why in reason, reason


def test_no_binding_or_incident_from_fleet_is_a_refusal():
    assert "not of this arm" in clearable(PORT, binding=None)[1]
    assert "not of this incident" in clearable(PORT, incident_id=None)[1]


@pytest.mark.parametrize("records", [
    [], [{**LOST, "fault_type": "OverloadError"}], [{**LOST, "fault": "hardware error: overload (bit 5) on id 13"}],
    [{**LOST, "fault": "overheating on id 12"}], [{**LOST, "fault": PORT_LOST_FAULT[1] + " and overload"}],
    [{**LOST, "name": "arm_b_follower-other.json"}], [{**LOST, "fault_type": "OSError"}],
])
def test_the_port_kind_clears_only_when_each_fault_record_is_the_lost_port(records):
    ok, reason = clearable(PORT, {**READ, "fault_records": records})
    assert ok is False and "not the lost port" in reason, reason
    # a second fault record beside the lost port's is held too
    two = {**PORT, "fault_records": PORT["fault_records"] + ["arm_b_follower-20261117T081100-overload.json"]}
    assert clearable(two, {**READ, "fault_records": [LOST, *records]})[0] is False


def test_a_read_too_old_at_the_clear_is_refused():
    assert clearable(PORT, {**READ, "at": 1100.0}, since=1000.0, now=2001.0) == (
        False, "torque OFF not confirmed (port in use): remeasure too old")


BUSY = ('ConnectionError("Failed to write \'Torque_Enable\' on id_=11 with \'0\' after 3 tries. [TxRxResult] Port is '
        'in use!")')


@pytest.mark.parametrize("facts, why", [
    # the port-busy kind: only that exact text, nothing else on the arm's record
    ({**PORT, "flagged": [{**PORT["flagged"][0], "fault": PORT["flagged"][0]["fault"].replace("Port is in use",
                                                                                         "There is no status packet")}]},
     "flagged"),
    ({**PORT, "flagged": [{**PORT["flagged"][0], "fault": PORT["flagged"][0]["fault"] + "; a hand"}]}, "flagged"),
    ({**PORT, "flagged": [{**PORT["flagged"][0], "caught": True}]}, "flagged"),
    ({**PORT, "flagged": [{**PORT["flagged"][0], "person_needed": True}]}, "flagged"),
    ({**PORT, "flagged": [PORT["flagged"][0], {"command": "grip", "error": "jaws caught", "caught": True}]}, "flagged"),
    ({**PORT, "flagged": [{**PORT["flagged"][0], "fault": f"session ended: RuntimeError: torque OFF not confirmed: "
                                                          f"[{BUSY}, ValueError('x')]"}]}, "flagged"),
    ({**PORT, "windup_hits": WINDUP["windup_hits"]}, "wind-up"),  # both kinds at once: a person
    ({**PORT, "latched": {"13": {"hw_error": 32, "bits": ["overload"]}}}, "latched"),
    ({**PORT, "stops": [{"command": "place", "error": "contact in place: wrist lag", "t": 1.0}]}, "contact stop"),
    ({**PORT, "folded": False}, "folded"), ({**PORT, "safe_end": False}, "safe end"),
    ({**PORT, "caps_restored": None}, "caps"),
    # the wind-up kind: the body joint text only, nothing else
    ({**WINDUP, "windup_hits": [{"reason": "the jaws stopped 5.0 units short at PWM -248 of 300: something is in them"
                                 }]}, "wind-up"),
    ({**WINDUP, "windup_hits": [{"reason": WINDUP["windup_hits"][0]["reason"] + "; and a cable"}]}, "wind-up"),
    ({**WINDUP, "windup_hits": [WINDUP["windup_hits"][0], {"reason": "elbow wound up"}]}, "wind-up"),
    ({**WINDUP, "windup_hits": ["elbow_flex still 0.8 units short"]}, "wind-up"),
    ({**WINDUP, "flagged": PORT["flagged"]}, "wind-up"),
    ({**WINDUP, "fault_records": ["arm_a-0001.json"]}, "fault record"),
    ({**WINDUP, "torque_after": {"11": 0, "12": 1}}, "torque"),
    ({**WINDUP, "torque_after": {}}, "torque"),
    ({**WINDUP, "latched": {"12": {"hw_error": 1}}}, "latched"),
    ({**WINDUP, "caps_restored": False}, "caps"),
    ({k: v for k, v in WINDUP.items() if k != "stops"}, "incomplete"),
])
def test_other_kinds_and_any_other_sign_stay_with_a_person_even_with_a_quiet_read(facts, why):
    ok, reason = clearable(facts)
    assert ok is False and why in reason, reason


# D-1040 amendment 2026-11-18: the torque-OFF rest sag envelope, judged by the contract from per-joint errors
HOME0 = {"shoulder_pan": 0.0, "shoulder_lift": 0.0, "elbow_flex": 0.0, "wrist_flex": 0.0, "wrist_roll": 0.0}


def sag(**err):
    """A read whose two reads (10 s apart) both show `err` over HOME0; max_home_err and folded as the cell reports."""
    e = {**HOME0, **err}
    top = max(abs(v) for v in e.values())
    return {**READ, "home_err": e, "first_home_err": dict(e), "first_at": READ["at"] - 10, "stable": True,
            "folded": top <= 3.0, "max_home_err": top}


@pytest.mark.parametrize("name, read, want", [
    ("arm_a 1.04 folded", sag(wrist_flex=1.04), "machine_clearable"),
    ("arm_b 4.1 stable", sag(wrist_flex=4.1, wrist_roll=2.93), "sag_only"),
    ("arm_s 5.65 stable", sag(elbow_flex=-5.65), "sag_only"),
    ("past SAG_MAX", sag(elbow_flex=6.6), "needs_person"),
    ("pan 4.0", sag(shoulder_pan=4.0), "needs_person"),
    ("roll 3.1", sag(wrist_roll=3.1), "needs_person"),
    ("unstable", {**sag(wrist_flex=4.1), "first_home_err": {**HOME0, "wrist_flex": 3.5}}, "needs_person"),
    ("reads too close", {**sag(wrist_flex=4.1), "first_at": READ["at"] - 1}, "needs_person"),
    ("torque on", {**sag(wrist_flex=4.1), "torque_after": {**ZERO, "14": 1}}, "needs_person"),
    ("hardware error", {**sag(wrist_flex=4.1), "hardware_error": {**ZERO, "14": 32}}, "needs_person"),
    ("no per-joint data", {**READ, "folded": False, "max_home_err": 4.1}, "needs_person"),
])
def test_classify_with_tonights_numbers(name, read, want):
    assert classify(read, None) == want, name
    assert classify(read, {"latched": {"11": {}}}) == "needs_person" if want != "needs_person" else True


def test_the_sag_clear_never_trusts_a_client_flag_and_keeps_every_other_refusal():
    assert clearable(PORT, sag(wrist_flex=4.1))[0] is True and clearable(WINDUP, sag(elbow_flex=-5.65))[0] is True
    lie = {**sag(shoulder_pan=4.0), "stable": True, "folded": True}  # folded lies, max_home_err does not
    assert clearable(PORT, lie)[0] is False
    flag_only = {**sag(wrist_flex=4.1), "first_home_err": {**HOME0, "wrist_flex": 3.0}, "stable": True}
    assert "not folded" in clearable(PORT, flag_only)[1]
    for bad in ({**sag(wrist_flex=4.1), "torque_after": {**ZERO, "11": 1}}, {**sag(wrist_flex=4.1), "at": SINCE},
                {**sag(wrist_flex=4.1), "arm": "arm_a"}):
        assert clearable(PORT, bad)[0] is False


def test_truncated_flagged_or_fault_records_stay_with_a_person():
    for bad in ({**PORT, "fault_records_total": 4}, {**PORT, "flagged_total": 6},
                {**PORT, "fault_records_total": True}, {**PORT, "truncated": True},
                {**WINDUP, "flagged_total": 1}):
        ok, reason = clearable(bad)
        assert ok is False and "truncated" in reason, (bad, ok, reason)
    complete = {**PORT, "flagged_total": len(PORT["flagged"]), "fault_records_total": len(PORT["fault_records"])}
    assert clearable(complete)[0] is True


STALE_REC = "omx_follower_arm-20261123T052904-126e8b.json"
STALE_TEXT = "session ended: ValueError: stale effort sample (>0.5 seconds)"
STALE = {
    "safe_end": True, "latched": {}, "folded": True, "caps_restored": True,
    "torque_after": dict(ZERO), "last_state": [0.76, -62.25, 52.97, 51.65, 44.96, 49.3],
    "windup_hits": [], "stop_reading": None, "stops": [],
    "flagged": [{"command": "run goto above_pick", "error": None, "fault": STALE_TEXT, "caught": None,
                 "person_needed": None, "t": 1795411744.754}],
    "flagged_total": 1,
    "fault_records": [STALE_REC],
    "fault_records_total": 1,
    "fault_record_kinds": [{"fault": "stale effort sample (>0.5 seconds)", "stop_reasons": []}],
}
STALE_FAULT = {"name": STALE_REC, "fault_type": STALE_EFFORT_FAULT[0], "fault": STALE_EFFORT_FAULT[1]}


def test_clean_stale_effort_clears_only_with_matching_quiet_fresh_remeasure():
    assert clearable(STALE, None) == (False, "stale effort sample: no valid remeasure")
    read_a = {**READ, "arm": "arm_a", "board_serial": "2B162C9B50323952582E3120FF06202D", "fault_records": [STALE_FAULT]}
    ok, msg = clearable(STALE, read_a, binding=("arm_a", "2B162C9B50323952582E3120FF06202D"))
    assert ok is True and msg.startswith("stale effort sample, then a fresh read")
    for bad_read in (
        {**read_a, "folded": False},
        {**read_a, "torque_after": {**ZERO, "12": 1}},
        {**read_a, "hardware_error": {**ZERO, "13": 32}},
        {**read_a, "fault_records": [{**STALE_FAULT, "fault_type": "OverloadError"}]},
        {**read_a, "fault_records": [{**STALE_FAULT, "fault": "hardware error: overload"}]},
        {**read_a, "fault_records": []},
    ):
        assert clearable(STALE, bad_read, binding=("arm_a", "2B162C9B50323952582E3120FF06202D"))[0] is False
    for bad_facts in (
        {**STALE, "folded": False},
        {**STALE, "safe_end": False},
        {**STALE, "torque_after": {**ZERO, "11": 1}},
        {**STALE, "caps_restored": False},
        {**STALE, "latched": {"13": {"hw_error": 32}}},
        {**STALE, "stops": [{"command": "place", "error": "contact in place: wrist lag", "t": 1.0}]},
        {**STALE, "fault_record_kinds": [{"fault": "stale effort sample (>0.5 seconds)", "stop_reasons": ["overload"]}]},
        {**STALE, "fault_record_kinds": [{"fault": "overheating on id 12", "stop_reasons": []}]},
        {**STALE, "fault_record_kinds": []},
        {**STALE, "fault_records": [], "fault_records_total": 0, "fault_record_kinds": [{"fault": "stale effort sample (>0.5 seconds)", "stop_reasons": ["overload"]}]},
        {**STALE, "flagged": [{**STALE["flagged"][0], "fault": STALE_TEXT + "; contact"}]},
        {**STALE, "flagged": [{**STALE["flagged"][0], "caught": True}]},
        {**STALE, "flagged": [{**STALE["flagged"][0], "person_needed": True}]},
        {**STALE, "flagged_total": 2},
    ):
        assert clearable(bad_facts, read_a, binding=("arm_a", "2B162C9B50323952582E3120FF06202D"))[0] is False
    # Current guarded_native_effort.py format includes tick_ms/last_tick_ms/last_effort_ms/pwm_ms/monitor_ms telemetry.
    diag = "stale effort sample (>0.5 seconds): tick_ms=12.3 last_tick_ms=612.4 last_effort_ms=n/a pwm_ms=4.5 monitor_ms=0.2"
    stale_diag = {
        **STALE,
        "flagged": [{**STALE["flagged"][0], "fault": f"runner: session ended: ValueError: {diag}"}],
        "fault_record_kinds": [{"fault": diag, "stop_reasons": []}],
    }
    read_diag = {**read_a, "fault_records": [{**STALE_FAULT, "fault": diag}]}
    assert clearable(stale_diag, read_diag, binding=("arm_a", "2B162C9B50323952582E3120FF06202D"))[0] is True


def test_park_body_windup_clears_only_with_clean_remeasure_and_refuses_jaw_or_other_commands():
    park_windup = {
        "safe_end": True, "latched": {}, "caps_restored": True, "folded": True,
        "torque_after": dict(ZERO), "stops": [], "fault_records": [], "fault_record_kinds": [],
        "windup_hits": [{"reason": "elbow_flex still 1.8 units short, PWM winding up 151 -> 249 of 600: pushing against something"}],
        "flagged": [
            {"command": "run park", "error": "contact in park: elbow_flex still 1.0 units short, PWM winding up 156 -> 243 of 600: pushing against something",
             "fault": "contact in park: elbow_flex still 1.0 units short, PWM winding up 156 -> 243 of 600: pushing against something", "caught": None, "person_needed": None},
        ],
        "flagged_total": 1, "fault_records_total": 0,
    }
    clean_read = {**READ, "fault_records": []}
    assert clearable(park_windup, None)[0] is False
    assert clearable(park_windup, clean_read)[0] is True
    for bad in (
        {**park_windup, "flagged": [{**park_windup["flagged"][0], "person_needed": True}]},
        {**park_windup, "flagged": [{**park_windup["flagged"][0], "caught": True}]},
        {**park_windup, "flagged": [{**park_windup["flagged"][0], "command": "run descend_pick"}]},
        {**park_windup, "flagged": [{"command": "run park", "error": "contact in park: the jaws stopped 5.0 units short at PWM -248 of 300: something is in them", "fault": "contact in park: the jaws stopped 5.0 units short at PWM -248 of 300: something is in them"}]},
        {**park_windup, "latched": {"13": {"hw_error": 32}}},
    ):
        assert clearable(bad, clean_read)[0] is False
