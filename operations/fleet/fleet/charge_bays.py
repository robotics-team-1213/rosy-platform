"""D-941 5/7: the site map's charge bays - which robot should go to which bay, and when it may leave.

Pure: Fleet feeds one observation per period and reads the plan. Fleet shows the plan
(``GET /api/fleet/charge-bays``); it does not dispatch from it yet: CORE's reverse-in docking and
its charge-return exception come first (D-941 6).

A bay charger is a magnetic USB with no reporting device, so "connected" is a rise of the filtered
pack voltage. While connected, CORE's percent reads the charger's voltage, not the pack: the
percent the robot arrived with plus connected time is the only charge estimate, and it needs a
measured rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional

GO_PERCENT = 15.0     # CORE critical 10 % + 5 % (user decision 2026-11-01)
LEAVE_PERCENT = 80.0
AT_BAY_M = 0.08       # a robot this close to a charge place is in that bay
RISE_V = 0.05         # filtered pack voltage rise that says the USB is connected
RISE_WINDOW_S = 20.0
SETTLE_S = 30.0       # in a bay this long without a rise: the USB did not connect


@dataclass(frozen=True)
class Bay:
    id: str
    x: float
    y: float


@dataclass(frozen=True)
class RobotView:
    robot_id: str
    online: bool
    percent: Optional[float]
    voltage: Optional[float]
    pose: Optional[tuple[float, float]]   # map x, y; None when not localized
    on_trip: bool


def bays_from_map(site_map) -> list[Bay]:
    return sorted((Bay(p.id, p.x, p.y) for p in site_map.places if p.kind == "charge"), key=lambda b: b.id)


@dataclass
class _Visit:
    bay: str
    since: float
    arrived_percent: Optional[float]
    volts: list[tuple[float, float]]
    connected_at: Optional[float] = None
    #: Since when nothing confirms where the robot is (offline, or no LOCALIZED pose); None while confirmed.
    lost_at: Optional[float] = None
    blind_s: float = 0.0   # unobserved time, never counted as charging


class ChargeBays:
    """Bay visits and the plan. ``rate_pct_per_min`` stays None until a charge is measured.

    A visit ends only when the robot is seen outside every bay with a trusted pose (or in another bay).
    Losing the pose or the link keeps the visit and shows the bay ``unknown``, never ``free``: a dead
    robot may still be in it. Fleet has no operator clear for a stale visit yet (follow-up).
    """

    def __init__(self, rate_pct_per_min: Optional[float] = None) -> None:
        self.rate = rate_pct_per_min
        self._visits: dict[str, _Visit] = {}
        self._now = 0.0

    def observe(self, now: float, robots: Iterable[RobotView], bays: list[Bay]) -> None:
        self._now = now
        robots = list(robots)
        for robot_id, visit in self._visits.items():   # a robot Fleet no longer lists is unseen, not gone
            if visit.lost_at is None and robot_id not in {r.robot_id for r in robots}:
                visit.lost_at = now
        for r in robots:
            visit = self._visits.get(r.robot_id)
            if not r.online or r.pose is None:   # no evidence of where it is: keep the visit, mark it unknown
                if visit is not None and visit.lost_at is None:
                    visit.lost_at = now
                continue
            bay = _bay_at(r.pose, bays)
            if bay is None:
                self._visits.pop(r.robot_id, None)   # seen elsewhere with a trusted pose
                continue
            if visit is None or visit.bay != bay.id:
                visit = self._visits[r.robot_id] = _Visit(bay.id, now, r.percent, [])
            if visit.lost_at is not None:
                visit.blind_s += now - visit.lost_at
                visit.lost_at = None
            if r.voltage is not None and math.isfinite(r.voltage):
                visit.volts = [(t, v) for t, v in visit.volts if now - t <= RISE_WINDOW_S] + [(now, r.voltage)]
                if visit.connected_at is None and r.voltage - min(v for _, v in visit.volts) >= RISE_V:
                    visit.connected_at = now

    def plan(self, robots: Iterable[RobotView], bays: list[Bay]) -> dict:
        robots = sorted(robots, key=lambda r: (r.percent is None, r.percent or 0.0, r.robot_id))
        held = {v.bay: rid for rid, v in self._visits.items()}
        rows, actions = [], []
        for r in robots:
            visit = self._visits.get(r.robot_id)
            if visit is not None:
                actions.append(self._in_bay(r.robot_id, visit))
            elif not r.online:
                continue
            elif r.percent is None:
                actions.append({"robot_id": r.robot_id, "action": "wait", "reason": "battery_unknown"})
            elif r.percent <= GO_PERCENT:
                free = next((b.id for b in bays if b.id not in held), None)
                if r.on_trip:
                    actions.append({"robot_id": r.robot_id, "action": "after_trip", "reason": "low_battery"})
                elif free is None:
                    actions.append({"robot_id": r.robot_id, "action": "wait", "reason": "no_free_bay"})
                else:
                    held[free] = r.robot_id
                    actions.append({"robot_id": r.robot_id, "action": "go", "bay": free, "reason": "low_battery"})
        for b in bays:
            rid = held.get(b.id)
            visit = self._visits.get(rid) if rid else None
            state = "free" if rid is None else ("planned" if visit is None else
                                                 "unknown" if visit.lost_at is not None else
                                                 "charging" if visit.connected_at is not None else "arrived")
            rows.append({"bay": b.id, "x": b.x, "y": b.y, "state": state, "robot_id": rid})
        return {"thresholds": {"go_percent": GO_PERCENT, "leave_percent": LEAVE_PERCENT,
                               "rate_pct_per_min": self.rate}, "bays": rows, "actions": actions,
                "dispatch": False}

    def _in_bay(self, robot_id: str, visit: _Visit) -> dict:
        row = {"robot_id": robot_id, "bay": visit.bay, "arrived_percent": visit.arrived_percent,
               "in_bay_s": round(self._now - visit.since, 1)}
        if visit.lost_at is not None:
            return {**row, "action": "stay", "reason": "pose_unknown"}
        if visit.connected_at is None:
            reseat = self._now - visit.since >= SETTLE_S
            return {**row, "action": "reseat" if reseat else "stay",
                    "reason": "usb_not_connected" if reseat else "connecting"}
        connected_s = max(0.0, self._now - visit.connected_at - visit.blind_s)
        row["connected_s"] = round(connected_s, 1)
        if self.rate is None or visit.arrived_percent is None:
            return {**row, "action": "stay", "reason": "charge_rate_not_measured"}
        estimate = min(100.0, visit.arrived_percent + self.rate * connected_s / 60.0)
        row["estimated_percent"] = round(estimate, 1)
        return {**row, "action": "leave" if estimate >= LEAVE_PERCENT else "stay",
                "reason": "charged" if estimate >= LEAVE_PERCENT else "charging"}


def _bay_at(pose, bays: list[Bay]) -> Optional[Bay]:
    if pose is None:
        return None
    near = min(bays, key=lambda b: math.dist(pose, (b.x, b.y)), default=None)
    return near if near is not None and math.dist(pose, (near.x, near.y)) <= AT_BAY_M else None
