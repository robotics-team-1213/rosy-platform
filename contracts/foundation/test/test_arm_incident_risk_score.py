"""Boundary, hard-veto, and compound-deduction tests for 95+ safety-score risk evaluation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_common.protocol.arm_incident.arm_incidents import (
    AUTO_CLEAR_MIN_SCORE,
    RISK_SCHEMA,
    evaluate_clear_safety,
)

SAFE = {
    "safe_end": True,
    "latched": {},
    "torque_after": {"11": 0, "12": 0, "13": 0, "14": 0, "15": 0, "16": 0},
    "caps_restored": True,
    "folded": True,
    "last_state": [0.0, -58.0, 50.0, 50.0, -5.0, 48.8],
    "windup_hits": [],
    "flagged": [],
    "stop_reading": None,
    "stops": [],
    "fault_records": [],
}
HOME6 = [0.0, -58.0, 50.0, 50.0, -5.0, 48.8]
ZERO = {str(i): 0 for i in range(11, 17)}
FIX = Path(__file__).parent / "fixtures"
LINK_REAL = json.loads((FIX / "arm_incidents_link" / "20261118T232302-arm_s.json").read_text(encoding="utf-8"))["facts"]
PARK_REAL = json.loads((FIX / "arm_incidents" / "20261117T122911-arm_s.json").read_text(encoding="utf-8"))["facts"]
REMEASURE_PORT = json.loads((FIX / "arm_incidents_remeasure" / "20261117T171027-arm_b.json").read_text(encoding="utf-8"))["facts"]
LOST = {
    "name": REMEASURE_PORT["fault_records"][0],
    "fault_type": "SerialException",
    "fault": "device reports readiness to read but returned no data (device disconnected or multiple access on port?)",
}


BOARD_B = "7F31D1FE50323952582E3120FF061D2D"


def _remeasure(incident_id="a" * 32, **over):
    return {
        "arm": "arm_b",
        "board_serial": BOARD_B,
        "incident_id": incident_id,
        "at": 2000.0,
        "torque_after": ZERO,
        "hardware_error": ZERO,
        "folded": True,
        "max_home_err": 0.4,
        "frames": [{"role": "top", "sha256": "a" * 64}],
        "fault_records": [LOST],
        **over,
    }


def _mh(*, temp=38.0, torque=0, hw_error=0, warnings=None, status="ended", stop_reasons=None, volt=12.0, obs=2000.0):
    return {
        "status": status,
        "observed_at": obs,
        "stop_reasons": [] if stop_reasons is None else stop_reasons,
        "motors": [
            {
                "joint": "shoulder_lift",
                "id": 12,
                "temperature_c": temp,
                "temperature_limit_c": 65.0,
                "torque_enabled": torque,
                "hardware_error": hw_error,
                "voltage_v": volt,
                "min_voltage_v": 9.5,
                "max_voltage_v": 14.5,
                "warnings": warnings or [],
            }
        ],
    }


def test_min_score_floor_cannot_drop_below_95():
    assert AUTO_CLEAR_MIN_SCORE == 95
    for bad in (94, 0, -1, 101, True, False, "95"):
        with pytest.raises(ValueError, match="95"):
            evaluate_clear_safety(SAFE, min_score=bad)


def test_exact_95_vs_94_threshold_boundary():
    # LINK_REAL: KIND_BUS_LINK (-2) + POSE_RESTED_NEAR_HOME (-3) == 95 -> auto_clear
    pass_95 = evaluate_clear_safety(LINK_REAL, now=1800000000.0)
    assert pass_95["schema"] == RISK_SCHEMA
    assert pass_95["safety_score"] == 95 and pass_95["risk_score"] == 5
    assert pass_95["allowed"] is True and pass_95["decision"] == "auto_clear"

    # Adding 1 recent clear drops score to 93 -> escalate_human
    fail_93 = evaluate_clear_safety(LINK_REAL, recent_clears_24h=1, now=1800000000.0)
    assert fail_93["safety_score"] == 93 and fail_93["risk_score"] == 7
    assert fail_93["allowed"] is False and fail_93["decision"] == "escalate_human"

    # PARK_REAL: KIND_PARK_STRAIN (-2) + recent_clears_24h=2 (-4) == 94 -> exact 94 blocks!
    fail_94 = evaluate_clear_safety(PARK_REAL, recent_clears_24h=2)
    assert fail_94["safety_score"] == 94 and fail_94["risk_score"] == 6
    assert fail_94["allowed"] is False and fail_94["decision"] == "escalate_human"


def test_spotless_and_compound_deductions():
    for recent, expected in ((0, 100), (1, 98), (2, 96)):
        r = evaluate_clear_safety(SAFE, recent_clears_24h=recent)
        assert r["safety_score"] == expected and r["allowed"] is True

    # Rested high drift (> 6.5) -> -2 (link) - 6 (drift) == 92 -> escalates
    high_drift = {**LINK_REAL, "last_state": [-0.02, -58.0, 57.2, 50.33, -4.91, 49.21],
                  "last_target": [-0.02, -58.0, 57.2, 50.33, -4.91, 49.21]}
    r_drift = evaluate_clear_safety(high_drift)
    assert r_drift["safety_score"] == 92 and r_drift["allowed"] is False

    # Auto-fold near 0.5 err -> 97 (allowed), near 2.5 err -> 94 (escalates)
    stopped = {**SAFE, "folded": False, "home": HOME6, "stops": [{"command": "place", "error": "contact in place: wrist", "t": 1.0}]}
    fold_ok = {"kind": "auto_fold", "incident_id": "b" * 32, "taken_at": 1005.0,
               "folded_state": [0.0, -58.0, 50.5, 50.0, -5.0, 48.8], "home": HOME6,
               "torque_after": ZERO, "corridor_clear": True, "candidate": "park"}
    assert evaluate_clear_safety(stopped, recovery=fold_ok, incident_id="b" * 32, since=1000.0)["safety_score"] == 97
    fold_edge = {**fold_ok, "folded_state": [0.0, -58.0, 52.5, 50.0, -5.0, 48.8]}
    r_fold = evaluate_clear_safety(stopped, recovery=fold_edge, incident_id="b" * 32, since=1000.0)
    assert r_fold["safety_score"] == 94 and r_fold["allowed"] is False

    # Remeasure near fold tol (2.5) without dual-read -> -1 - 5 == 94 (escalates); with dual-read -> 99
    iid = "c" * 32
    r_no_dual = evaluate_clear_safety(
        REMEASURE_PORT, remeasured=_remeasure(iid, max_home_err=2.5), since=1000.0, now=2000.0,
        incident_id=iid, binding=("arm_b", BOARD_B),
    )
    assert r_no_dual["safety_score"] == 94 and r_no_dual["allowed"] is False

    err = dict.fromkeys(("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"), 0.5)
    r_dual = evaluate_clear_safety(
        REMEASURE_PORT,
        remeasured=_remeasure(iid, max_home_err=2.5, first_at=1990.0, first_home_err=err, home_err=err),
        since=1000.0, now=2000.0, incident_id=iid, binding=("arm_b", BOARD_B),
    )
    assert r_dual["safety_score"] == 99 and r_dual["allowed"] is True


def test_motor_health_and_camera_deductions_and_hard_vetoes():
    # Motor health temp 52 (-3) + warnings (-4) == 93 -> escalates
    r_warn = evaluate_clear_safety(SAFE, motor_health=_mh(temp=52.0, warnings=["high_pwm"]), since=1900.0, now=2000.0)
    assert r_warn["safety_score"] == 93 and r_warn["allowed"] is False

    # Motor health temp 56 (-6) == 94 -> escalates
    r_hot = evaluate_clear_safety(SAFE, motor_health=_mh(temp=56.0), since=1900.0, now=2000.0)
    assert r_hot["safety_score"] == 94 and r_hot["allowed"] is False

    # Camera check unavailable -> -6 == 94 -> escalates
    r_cam_unavail = evaluate_clear_safety(SAFE, camera_check={"unavailable": True, "error": "timeout"})
    assert r_cam_unavail["safety_score"] == 94 and r_cam_unavail["allowed"] is False

    # Hard vetoes always force safety_score=0, risk_score=100, allowed=False
    veto_cases = [
        ({**SAFE, "latched": {"13": {"hw_error": 32}}}, {}),
        ({**SAFE, "torque_after": {**ZERO, "12": 1}}, {}),
        (SAFE, {"recent_clears_24h": 3}),
        (SAFE, {"camera_check": {"verdict": {"camera_clear": False, "worries": ["arm_s_top: box on shoulder"]}}}),
        (SAFE, {"motor_health": _mh(hw_error=32)}),
        (SAFE, {"motor_health": _mh(hw_error=True)}),
        (SAFE, {"motor_health": _mh(torque=1)}),
        (SAFE, {"motor_health": _mh(temp=65.0)}),
        (SAFE, {"motor_health": _mh(temp="65")}),
        (SAFE, {"motor_health": _mh(volt=8.2)}),
        (SAFE, {"motor_health": _mh(status="fault", stop_reasons=["overtemp"])}),
        (SAFE, {"motor_health": _mh(stop_reasons="overtemp")}),
        (SAFE, {"motor_health": _mh(stop_reasons=123)}),
        (SAFE, {"remeasured": {"bad": 1}}),
        (SAFE, {"remeasured": _remeasure(hardware_error={**ZERO, "11": 32})}),
        (PARK_REAL, {"remeasured": _remeasure(torque_after={**ZERO, "12": 1})}),
        (SAFE, {"remeasured": _remeasure(folded=False, max_home_err=120.0)}),
    ]
    for facts, kw in veto_cases:
        out = evaluate_clear_safety(facts, **kw)
        assert out["safety_score"] == 0 and out["risk_score"] == 100
        assert out["allowed"] is False and out["decision"] == "escalate_human"
        assert out["hard_vetoes"]
