"""D-721 Amendment (S1): does a low-battery robot have a station recovery request, and where could it go?

Pure, no I/O: Fleet gathers one robot row, the arbitrated map pose and the charge-bay plan
(``fleet.charge_bays``), and reads the answer. Nothing here commands a robot; S1 only shows the
answer and records an operator's approval (``started: false``). Bay choice reuses the charge-bay
plan's own states, so there is no second allocator.

A request exists only for an online robot whose battery evidence is fresh and whose level is
warning or lower. Stale or missing evidence is never "ok" and never a low-battery claim: it answers
``battery_evidence_missing``.
"""

from __future__ import annotations

from typing import Optional

LOW_LEVELS = ("warning", "critical", "deep")   # SAF-005 levels at or below the 20 % warning
ALL_LEVELS = ("ok", *LOW_LEVELS)
BUSY_MODES = ("NAVIGATION", "DOCKING", "MANUAL")
BUSY_NAVIGATION = ("PLANNING", "NAVIGATING")
BUSY_DOCKING = ("DOCKING", "UNDOCKING")
REASONS = ("no_station", "no_free_bay", "position_unknown", "already_stopped", "busy",
           "another_returning", "battery_evidence_missing", "state_unknown")
KNOWN_MODES = ("IDLE", *BUSY_MODES, "EMERGENCY")


def _fresh_battery(row: dict) -> Optional[dict]:
    """The row's battery block when its evidence is fresh by its own bound, else None."""
    battery = (row.get("power_health") or {}).get("battery")
    if not isinstance(battery, dict) or battery.get("evidence") != "fresh":
        return None
    age, bound = battery.get("sample_age_s"), battery.get("stale_after_s")
    if (isinstance(age, bool) or isinstance(bound, bool) or not isinstance(age, (int, float))
            or not isinstance(bound, (int, float)) or age < 0 or age > bound):
        return None
    return battery if battery.get("level") in ALL_LEVELS else None


def _busy(row: dict, state: dict) -> bool:
    if (row.get("rule_m") or {}).get("state", "idle") != "idle":   # a trip or a goal Fleet holds
        return True
    return (state.get("mode") in BUSY_MODES or state.get("navigation") in BUSY_NAVIGATION
            or (state.get("docking") or {}).get("state") in BUSY_DOCKING)


def decide(row: dict, pose, bays: Optional[dict], another_returning: bool) -> Optional[dict]:
    """The answer for one gathered robot row, or None when there is nothing to ask.

    ``pose`` is the arbitrated map pose (anything with ``.state``) or None; ``bays`` is
    ``ChargeBays.plan(...)`` or None without an active map; ``another_returning`` says whether
    another robot is already on its way to a station.

    Answer: ``{"robot_id", "request", "reason", "bay", "level", "percent", "bays_unknown"}``.
    ``request`` False means the battery cannot be judged (``reason`` is battery_evidence_missing).
    With ``request`` True, exactly one of ``bay`` and ``reason`` is set.
    """
    state = row.get("state")
    if not row.get("online") or not isinstance(state, dict):
        return None   # an offline robot is not asked; the roster already says the link is down
    answer = {"robot_id": row["robot_id"], "request": False, "reason": None, "bay": None,
              "level": None, "percent": None, "bays_unknown": 0}
    battery = _fresh_battery(row)
    if battery is None:
        return {**answer, "reason": "battery_evidence_missing"}
    if battery["level"] not in LOW_LEVELS:
        return None
    percent = battery.get("percent")
    answer.update(request=True, level=battery["level"],
                  percent=percent if isinstance(percent, (int, float)) and not isinstance(percent, bool) else None)
    rows = (bays or {}).get("bays") or []
    mine = next((b for b in rows if b.get("robot_id") == row["robot_id"]), None)
    if mine is not None and mine.get("state") != "planned":
        return None   # already in a bay: charge_bays owns what happens there
    answer["bays_unknown"] = sum(b.get("state") == "unknown" for b in rows)
    estop = (state.get("safety") or {}).get("estop")
    if estop is True or state.get("mode") == "EMERGENCY":
        reason = "already_stopped"   # recovery never releases a stop
    elif type(estop) is not bool or state.get("mode") not in KNOWN_MODES or not isinstance(row.get("rule_m"), dict):
        reason = "state_unknown"   # no stop flag, mode or motion verdict: an empty state is not "idle and clear"
    elif _busy(row, state):
        reason = "busy"
    elif not rows:
        reason = "no_station"
    elif getattr(pose, "state", None) != "LOCALIZED":
        reason = "position_unknown"
    elif another_returning:
        reason = "another_returning"
    else:
        bay = mine or next((b for b in rows if b.get("state") == "free"), None)
        if bay is None:
            reason = "no_free_bay"   # with bays_unknown > 0 a bay may be free, but nothing says so
        else:
            return {**answer, "bay": bay["bay"]}
    return {**answer, "reason": reason}
