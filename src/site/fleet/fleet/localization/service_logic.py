"""Pure parts of the Fleet localization service (D-395 §8, §9; Phase 2 P2-6).

The service in `fleet.server.localization_service` polls robots and posts; this
module only decides: the reference squares and slots from `lane_rules.yaml`, the
§9 monitor (a LOCALIZED robot observed > 25 cm or > 60 degrees away in 2 distinct
reports within 15 s, none agreeing between them, is suspect), the escalation ladder timers (10 s, 25 s, 60 s in CANDIDATES), and the
peer observations a candidate report gives of LOCALIZED robots. No transport, no
asyncio; time is passed in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Hashable, Mapping, Optional, Sequence

from core_common.protocol.localization import CandidateReport, LocState

from fleet.localization import cues
from fleet.localization.arbiter import MARGIN, Context, Weights, score

#: D-395 §9 monitor thresholds (initial values, tuned in S1).
SUSPECT_DIST_M = 0.25
SUSPECT_YAW_RAD = math.radians(60.0)
#: S1 finding 7: SUSPECT after this many distinct fresh disagreeing reports, with no
#: agreeing report between them, inside this window (replaces the 1.5 s hold).
SUSPECT_REPORTS = 2
SUSPECT_WINDOW_S = 15.0
SUSPECT_REASON = "fleet_monitor"
#: Anchor provenance (S1 finding 3): a LOCALIZED pose that moves more than
#: JUMP_M + JUMP_SPEED_MPS * dt, or turns more than JUMP_YAW_RAD + JUMP_RATE_RADPS * dt,
#: between two polls was re-set, not driven (0.5 m / 86 degrees at the 0.5 s poll).
JUMP_M = 0.25
JUMP_SPEED_MPS = 0.5
JUMP_YAW_RAD = 0.5
JUMP_RATE_RADPS = 2.0
#: Cues from the world itself; `peers` anchors only because Context.peers holds anchors.
WORLD_CUES = ("paint", "slot", "square")
#: A peer observation is an object this close to the peer's reported pose or its mirror.
PEER_EVIDENCE_M = 0.25
#: A candidate report is evidence for this long after Fleet first saw it (Fleet's clock).
REPORT_FRESH_S = 1.0
#: Seconds in CANDIDATES before each rung. Contract §3 said 10/25/60 s; P2-7 moved homing
#: after the rotate's limit (10 + 30 s) and needs_human after the lane mission's (45 + 40 s),
#: so each mission can finish before the next rung (review of P2-7).
LADDER_ROTATE_S = 10.0
LADDER_HOMING_S = 45.0
LADDER_HUMAN_S = 120.0
#: A rung CORE refused as `busy` is asked again this often until CORE takes it.
BUSY_RETRY_S = 2.0
#: Missions each rung asks CORE for, in order (P2-7): `to_square` first when a square is
#: known, `lane_to_stopline` when CORE refuses it as `unsupported` or no square is known.
RUNG_MISSIONS = {"rotate": ("rotate_in_place",), "homing": ("to_square", "lane_to_stopline"),
                 "needs_human": ()}
#: (max_distance_m, max_time_s) per mission; within CORE's caps (1.0 m, 120 s, nudge 0.10 m).
MISSION_LIMITS = {"rotate_in_place": (0.0, 30.0), "lane_to_stopline": (0.6, 40.0),
                  "to_square": (1.0, 60.0)}

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


def square_target(report: Optional[CandidateReport],
                  squares: Sequence[tuple[float, float]]) -> Optional[dict]:
    """`to_square` target: the square nearest the robot's first candidate (map frame), or None
    without a report or squares. CORE drives toward it; arrival and the camera decide (rev. 1)."""
    if report is None or not report.candidates or not squares:
        return None
    first = report.candidates[0]
    square = min(squares, key=lambda s: math.dist(s, (first.x, first.y)))
    return {"square": [square[0], square[1]], "candidate_index": 0,
            "request_id": report.request_id}


def disagrees(reported: cues.Pose, observed: Observation) -> bool:
    if math.dist(reported[:2], observed[:2]) > SUSPECT_DIST_M:
        return True
    return observed[2] is not None and abs(cues.wrap(reported[2] - observed[2])) > SUSPECT_YAW_RAD


def jumped(before: cues.Pose, after: cues.Pose, dt: float) -> bool:
    """A LOCALIZED pose moved further between two polls than a Pinky can drive: the
    signature of a pose injected while LOCALIZED (S1 forced mirror), not motion."""
    dt = max(dt, 0.0)
    return (math.dist(before[:2], after[:2]) > JUMP_M + JUMP_SPEED_MPS * dt
            or abs(cues.wrap(after[2] - before[2])) > JUMP_YAW_RAD + JUMP_RATE_RADPS * dt)


def clear_leader(report: CandidateReport, context: Context, now: float,
                 weights: Weights = Weights(), margin: float = MARGIN) -> Optional[cues.Pose]:
    """The candidate that leads every other by `margin`, or None."""
    totals = [row["total"] for row in score(report, context, now, weights)]
    order = sorted(range(len(totals)), key=lambda i: -totals[i])
    if len(order) > 1 and totals[order[0]] - totals[order[1]] < margin:
        return None
    c = report.candidates[order[0]]
    return (c.x, c.y, c.yaw)


def mirror(pose: cues.Pose) -> cues.Pose:
    """The 180-degree twin of a pose on the symmetric track (about the map origin)."""
    return (-pose[0], -pose[1], cues.wrap(pose[2] + math.pi))


def peer_observations(report: CandidateReport, observer: cues.Pose,
                      peers: Mapping[str, cues.Pose]) -> dict[str, Observation]:
    """Unambiguous evidence `report` gives about each LOCALIZED peer, objects placed from `observer`.

    Seen: an object within `PEER_EVIDENCE_M` of the peer's reported pose (observed there).
    Seen elsewhere (the mirror-lock signature): no object near the reported pose and exactly
    one within `PEER_EVIDENCE_M` of its 180-degree mirror (observed at that object). Anything
    else (no objects, objects elsewhere, a hidden peer) is no evidence (review of lane C)."""
    placed = [cues.to_map(observer, (o.x, o.y)) for o in report.unmapped_objects]
    out = {}
    for robot_id, pose in peers.items():
        near = [p for p in placed if math.dist(p, pose[:2]) <= PEER_EVIDENCE_M]
        if near:
            nearest = min(near, key=lambda p: math.dist(p, pose[:2]))
            out[robot_id] = (nearest[0], nearest[1], None)
            continue
        twin = mirror(pose)
        at_mirror = [p for p in placed if math.dist(p, twin[:2]) <= PEER_EVIDENCE_M]
        if len(at_mirror) == 1:
            out[robot_id] = (at_mirror[0][0], at_mirror[0][1], None)
    return out


@dataclass
class Monitor:
    """§9: `reports` distinct disagreeing reports within `window_s`, no agreeing one between.

    S1 finding 7: reports arrive 4-7 s apart under load, so wall-time continuity never
    held. Evidence is keyed by its report (or sighting); a key counts once however often
    it is re-read while fresh. Within one poll a disagreement wins over an agreement
    (a missed mirror lock is worse than a needless SUSPECT). Firing resets the count."""
    reports: int = SUSPECT_REPORTS
    window_s: float = SUSPECT_WINDOW_S
    _streak: dict = field(default_factory=dict)      # robot -> times of counted disagreements
    _counted: dict = field(default_factory=dict)     # robot -> {evidence key: time counted}

    def update(self, robot_id: str, evidence: Sequence[tuple[Hashable, bool]], now: float) -> bool:
        counted = self._counted.setdefault(robot_id, {})
        for key in [k for k, t in counted.items() if now - t > self.window_s]:
            del counted[key]
        streak = [t for t in self._streak.get(robot_id, ()) if now - t <= self.window_s]
        for key, disagreeing in sorted(evidence, key=lambda e: e[1]):     # agreements first
            if key in counted:
                continue
            counted[key] = now
            streak = streak + [now] if disagreeing else []
        if len(streak) >= self.reports:
            self._streak[robot_id] = []
            return True
        self._streak[robot_id] = streak
        return False

    def forget(self, robot_id: str) -> None:
        self._streak.pop(robot_id, None)
        self._counted.pop(robot_id, None)


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
                "rung_missions": list(RUNG_MISSIONS.get(rung, ()))}

    def forget(self, robot_id: str) -> None:
        self._since.pop(robot_id, None)
        self._rung.pop(robot_id, None)

    def robots(self) -> Sequence[str]:
        return list(self._since)
