"""Pure parts of the Fleet localization service (D-395 §8, §9; Phase 2 P2-6).

The service in `fleet.server.localization_service` polls robots and posts; this
module only decides: the reference squares and slots from `lane_rules.yaml`, the
§9 monitor (a LOCALIZED robot observed > 25 cm or > 60 degrees away for 1.5 s is
suspect), the escalation ladder timers (10 s, 25 s, 60 s in CANDIDATES), and the
peer observations a candidate report gives of LOCALIZED robots. No transport, no
asyncio; time is passed in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from core_common.protocol.localization import CandidateReport, LocState

from fleet.localization import cues
from fleet.localization.arbiter import MARGIN, Context, Weights, score

#: D-395 §9 monitor thresholds (initial values, tuned in S1).
SUSPECT_DIST_M = 0.25
SUSPECT_YAW_RAD = math.radians(60.0)
SUSPECT_HOLD_S = 1.5
SUSPECT_REASON = "fleet_monitor"
#: Contract §3 ladder: seconds in CANDIDATES before each rung.
LADDER_ROTATE_S = 10.0
LADDER_HOMING_S = 25.0
LADDER_HUMAN_S = 60.0
#: Missions each rung would request once CORE's executor lands (lane B, P2-7).
RUNG_MISSIONS = {"rotate": ("rotate_in_place",), "homing": ("to_square", "lane_to_stopline"),
                 "needs_human": ()}

Observation = tuple[float, float, Optional[float]]     # x, y, yaw (None: position only)


def parse_reference_squares(rules: Mapping) -> tuple[list[cues.Slot], list[tuple[float, float]]]:
    """`lane_rules.yaml` `reference_squares` -> (slots, square centres), map frame.

    Every square is a start slot whose heading is an axis (D-395 rev. 2)."""
    slots, squares = [], []
    for entry in rules.get("reference_squares") or []:
        x, y = (float(v) for v in entry["centre"])
        squares.append((x, y))
        slots.append(cues.Slot(x, y, math.radians(float(entry.get("heading_axis_deg", 0.0)))))
    return slots, squares


def disagrees(reported: cues.Pose, observed: Observation) -> bool:
    if math.dist(reported[:2], observed[:2]) > SUSPECT_DIST_M:
        return True
    return observed[2] is not None and abs(cues.wrap(reported[2] - observed[2])) > SUSPECT_YAW_RAD


def clear_leader(report: CandidateReport, context: Context, now: float,
                 weights: Weights = Weights(), margin: float = MARGIN) -> Optional[cues.Pose]:
    """The candidate that leads every other by `margin`, or None."""
    totals = [row["total"] for row in score(report, context, now, weights)]
    order = sorted(range(len(totals)), key=lambda i: -totals[i])
    if len(order) > 1 and totals[order[0]] - totals[order[1]] < margin:
        return None
    c = report.candidates[order[0]]
    return (c.x, c.y, c.yaw)


def peer_observations(report: CandidateReport, observer: cues.Pose,
                      peers: Mapping[str, cues.Pose]) -> dict[str, Observation]:
    """Where `report`'s unmapped objects, placed from `observer`, put each LOCALIZED peer in view.

    The nearest object to a peer's reported pose is that peer's observed position. No
    objects at all is no observation (occlusion is not modelled)."""
    placed = [cues.to_map(observer, (o.x, o.y)) for o in report.unmapped_objects]
    if not placed:
        return {}
    out = {}
    for robot_id, pose in peers.items():
        if math.dist(observer[:2], pose[:2]) > cues.PEER_VIEW_M:
            continue
        nearest = min(placed, key=lambda p: math.dist(p, pose[:2]))
        out[robot_id] = (nearest[0], nearest[1], None)
    return out


@dataclass
class Monitor:
    """§9: disagreement held for `hold_s` -> suspect, once; agreement or no evidence resets."""
    hold_s: float = SUSPECT_HOLD_S
    _since: dict = field(default_factory=dict)

    def update(self, robot_id: str, disagreeing: Optional[bool], now: float) -> bool:
        if not disagreeing:
            self._since.pop(robot_id, None)
            return False
        since = self._since.setdefault(robot_id, now)
        if now - since >= self.hold_s:
            self._since.pop(robot_id, None)
            return True
        return False

    def forget(self, robot_id: str) -> None:
        self._since.pop(robot_id, None)


@dataclass
class Ladder:
    """Contract §3 escalation timers.

    The clock starts when the robot first enters CANDIDATES after being LOCALIZED
    (or first seen) and stops only at LOCALIZED: a rejected decision sends the robot
    back through SUSPECT/CANDIDATES without restarting it, or a reject loop would
    never reach a human."""
    rotate_s: float = LADDER_ROTATE_S
    homing_s: float = LADDER_HOMING_S
    human_s: float = LADDER_HUMAN_S
    _since: dict = field(default_factory=dict)
    _rung: dict = field(default_factory=dict)

    def update(self, robot_id: str, state: Optional[LocState], now: float) -> Optional[str]:
        """Feed one observed state; returns a rung name the first time it is reached."""
        if state is None or state is LocState.LOCALIZED:
            self.forget(robot_id)
            return None
        if robot_id not in self._since and state is not LocState.CANDIDATES:
            return None
        elapsed = now - self._since.setdefault(robot_id, now)
        rung = ("needs_human" if elapsed > self.human_s else "homing" if elapsed > self.homing_s
                else "rotate" if elapsed > self.rotate_s else None)
        if rung is None or rung == self._rung.get(robot_id):
            return None
        self._rung[robot_id] = rung
        return rung

    def view(self, robot_id: str, now: float) -> dict:
        since = self._since.get(robot_id)
        rung = self._rung.get(robot_id)
        return {"rung": rung, "needs_human": rung == "needs_human",
                "candidates_for_s": None if since is None else round(now - since, 1),
                "pending_missions": list(RUNG_MISSIONS.get(rung, ()))}

    def forget(self, robot_id: str) -> None:
        self._since.pop(robot_id, None)
        self._rung.pop(robot_id, None)

    def robots(self) -> Sequence[str]:
        return list(self._since)
