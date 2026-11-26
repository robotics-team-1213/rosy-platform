"""Classify a disconnected session for reporting; motion and clearance use their own gates."""
import math

from .arm_incidents import REMEASURE_HOME_TOL

HOME_RECOVERY_REASON = "USB connection lost; guarded home recovery required"


def guarded_home_decision(facts):
    decision = {"actions": [], "hold": True, "offered": [], "reason": "torque off with arm extended; guarded fold required"}
    if is_home_recovery(facts):
        decision.update(reason=HOME_RECOVERY_REASON, event_kind="home_recovery")
    return decision


def is_home_recovery(facts):
    if not isinstance(facts, dict) or facts.get("truncated"):
        return False
    if (facts.get("safe_end") is not True or facts.get("caps_restored") is not True
            or facts.get("folded") is not False or facts.get("latched") != {}
            or facts.get("windup_hits") != [] or facts.get("stops") != [] or facts.get("stop_reading")):
        return False
    torque = facts.get("torque_after")
    if not isinstance(torque, dict) or len(torque) != 6 or set(map(str, torque)) != {str(i) for i in range(11, 17)}:
        return False
    if any(type(v) is not int or v != 0 for v in torque.values()):
        return False
    home, position = facts.get("home"), facts.get("last_state")
    if not all(isinstance(p, list) and len(p) == 6 and all(type(v) in (int, float) and math.isfinite(v)
                                                           for v in p) for p in (home, position)):
        return False
    if max(abs(a - b) for a, b in zip(home[:5], position[:5])) <= REMEASURE_HOME_TOL:
        return False
    records, kinds, flags = (facts.get(k) for k in ("fault_records", "fault_record_kinds", "flagged"))
    if not all(isinstance(rows, list) for rows in (records, kinds, flags)):
        return False
    if not flags or len(flags) != facts.get("flagged_total") or not records or len(records) != len(kinds):
        return False
    if len(records) != facts.get("fault_records_total") or any(
        not isinstance(k, dict) or k.get("fault") != "(5, 'Input/output error')" or k.get("stop_reasons") != []
        for k in kinds
    ):
        return False
    for row in flags:
        if not isinstance(row, dict) or row.get("caught"):
            return False
        texts = [row[k] for k in ("fault", "error") if row.get(k)]
        if not texts or any(not isinstance(t, str) or "DeviceNotConnectedError" not in t
                            or not t.startswith(("session ended: RuntimeError: torque OFF not confirmed:",
                                                 "interrupt: guard stopped, torque reads",
                                                 "HOLD: guard stopped, torque reads")) for t in texts):
            return False
    return True
