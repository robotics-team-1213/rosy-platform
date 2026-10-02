"""Fleet localization arbiter (D-395 §3, §7): score each robot's candidates, decide on a held margin.

Pure: the caller feeds `CandidateReport`s, what Fleet knows (`Context`) and its
clock; `observe` returns a `LocalizationDecision` once one candidate has led
the next by at least `margin` for `hold_s` under the same request id, and
never twice for one request. No transport, no asyncio, no robot calls.

D-395 rev. 3: a decision names the scan-asymmetric cues that separated the
leader (`ASYMMETRIC`); with none there is no decision, because the robot would
reject it. Its lifetime is `ttl_s` from receipt, not an absolute time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from core_common.protocol.localization import CandidateReport, LocalizationDecision

from fleet.localization import cues

#: D-395 §7: the hold is 2 s; margin and weights are initial values for S1 tuning.
HOLD_S = 2.0
MARGIN = 1.0
DECISION_TTL_S = 5.0
#: Cues that differ between a pose and its 180-degree mirror (same set as the robot's).
ASYMMETRIC = ("paint", "peers", "slot", "square")


@dataclass(frozen=True)
class Weights:
    scan_fit: float = 1.0
    paint: float = 2.0
    peers: float = 2.0
    slot: float = 1.5
    last_good: float = 0.5
    overhead: float = 0.5
    square: float = 3.0


@dataclass(frozen=True)
class Context:
    """What Fleet knows about one robot's surroundings at decision time."""
    peers: Sequence[tuple[float, float]] = ()            # other LOCALIZED robots, map frame
    slots: Sequence[cues.Slot] = ()
    squares: Sequence[tuple[float, float]] = ()          # mapped reference square centres
    last_good: Optional[cues.Pose] = None
    sighting: Optional[cues.Sighting] = None


def score(report: CandidateReport, context: Context, now: float,
          weights: Weights = Weights()) -> list[dict]:
    """Per-candidate cue values and weighted total, in report order."""
    objects = [(o.x, o.y) for o in report.unmapped_objects]
    # Only ranged sightings are evidence (D-395 rev. 11); bearing-only ones stay on the wire.
    seen = [(s.bearing_rad, s.range_m) for s in report.square_sightings if s.range_m is not None]
    out = []
    for c in report.candidates:
        pose = (c.x, c.y, c.yaw)
        values = {
            "scan_fit": c.scan_fit,
            "paint": c.paint_score or 0.0,
            "peers": cues.peers_cue(pose, objects, context.peers),
            "slot": cues.slot_cue(pose, context.slots),
            "last_good": cues.last_good_cue(pose, context.last_good, report.pickup),
            "overhead": cues.overhead_cue(pose, context.sighting, now),
            "square": cues.square_cue(pose, context.squares, seen) if seen else 0.0,
        }
        values["total"] = sum(getattr(weights, k) * v for k, v in values.items())
        out.append(values)
    return out


@dataclass
class _Lead:
    request_id: str
    index: int
    since: float


@dataclass
class Arbiter:
    margin: float = MARGIN
    hold_s: float = HOLD_S
    ttl_s: float = DECISION_TTL_S
    weights: Weights = field(default_factory=Weights)
    _leads: dict = field(default_factory=dict)
    _decided: dict = field(default_factory=dict)
    #: robot -> request id of its last report in which an asymmetric cue favoured the leader.
    _favoured: dict = field(default_factory=dict)

    def pending(self, robot_id: str, request_id: Optional[str]) -> bool:
        """True while the arbiter may still decide `request_id` for this robot, or just did:
        a lead is held, an asymmetric cue favours one candidate (margin or not), or a
        decision went out for it. The ladder waits meanwhile (S1 re-run R2)."""
        if request_id is None:
            return False
        lead = self._leads.get(robot_id)
        decided = self._decided.get(robot_id)
        return ((lead is not None and lead.request_id == request_id)
                or self._favoured.get(robot_id) == request_id
                or (decided is not None and decided[0] == request_id))

    def observe(self, report: CandidateReport, context: Context,
                now: float) -> Optional[LocalizationDecision]:
        robot = report.robot_id
        if self._decided.get(robot) == (report.request_id, report.stamp):
            return None
        scores = score(report, context, now, self.weights)
        order = sorted(range(len(scores)), key=lambda i: -scores[i]["total"])
        best = order[0]
        gap = scores[best]["total"] - scores[order[1]]["total"] if len(order) > 1 else math.inf
        lead = self._leads.get(robot)
        carried = _carried(scores, best)
        if carried:
            self._favoured[robot] = report.request_id
        else:
            self._favoured.pop(robot, None)
        if gap < self.margin or not carried:
            self._leads.pop(robot, None)
            return None
        if lead is None or lead.request_id != report.request_id or lead.index != best:
            self._leads[robot] = _Lead(report.request_id, best, now)
            return None
        if now - lead.since < self.hold_s:
            return None
        # Keyed by the report stamp too: a robot whose decision was lost or rejected
        # re-reports with a newer stamp and gets a fresh hold and decision.
        self._decided[robot] = (report.request_id, report.stamp)
        self._leads.pop(robot, None)
        return LocalizationDecision(
            request_id=report.request_id, candidate_index=best, source="candidate", cues=carried,
            evidence={"totals": [round(s["total"], 3) for s in scores],
                      "margin": round(min(gap, 99.0), 3),
                      "cues": {k: round(v, 3) for k, v in scores[best].items()}},
            ttl_s=self.ttl_s)


def _carried(scores: list[dict], best: int) -> list[str]:
    """Asymmetric cues with positive evidence for the leader that beat every other candidate.

    Positive: beating a -1 (a peer hidden from the scan, a square not seen) with 0
    is no evidence for the leader. Every other candidate, not just the runner-up:
    the cue must separate the leader from its 180-degree twin wherever that twin
    ranks (review of 1aeada8d)."""
    others = [row for i, row in enumerate(scores) if i != best]
    return [k for k in ASYMMETRIC
            if scores[best][k] > 0.0 and all(scores[best][k] > row[k] for row in others)]
