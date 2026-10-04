"""Pure matcher: anonymous overhead detections <-> robot self-reported map poses (D-457 5).

One-to-one by distance inside a gate, solved exactly (Hungarian; scipy is not a Fleet
dependency). A pair outside the gate costs more than every gated pair together, so the
solution first maximises the number of matches, then minimises their total distance.
Display and cross-check only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

GATE_M = 0.30
#: When one robot is covered by several sources, the most informative status wins.
STATUS_RANK = {"MARKER": -1, "MATCHED": 0, "NO_DETECTION": 1, "NO_POSE": 2, "CAMERA_UNAVAILABLE": 3}
_OUT_OF_GATE = 1e6
_GATE_EPS = 1e-9


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    verified: bool  # D-395 localization says LOCALIZED in map; False = the robot predates D-395


@dataclass(frozen=True)
class Seen:
    x: float
    y: float
    footprint_m: float
    score: float


@dataclass(frozen=True)
class Track:
    robot_id: str
    status: str
    offset_m: Optional[float] = None
    camera: Optional[Seen] = None
    pose: Optional[Pose] = None


def assign(cost: Sequence[Sequence[float]]) -> list[int]:
    """Minimum-cost perfect assignment on a square matrix; ``result[row] = column``.

    Costs must be finite: NaN or inf corrupts the potentials and the result is undefined.
    """
    n = len(cost)
    if n == 0:
        return []
    inf = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = inf
            j1 = 0
            for j in range(1, n + 1):
                if not used[j]:
                    current = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if current < minv[j]:
                        minv[j] = current
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [-1] * n
    for j in range(1, n + 1):
        if p[j]:
            result[p[j] - 1] = j - 1
    return result


def match(robot_ids: Sequence[str], poses: Mapping[str, Optional[Pose]],
          detections: Optional[Sequence[Seen]], gate_m: float = GATE_M) -> tuple[list[Track], list[Seen]]:
    """Tracks in ``robot_ids`` order and the detections no robot claimed.

    ``detections`` None means no fresh OK payload for this source. Duplicate ``robot_ids``
    raise ValueError. The gate is inclusive with a 1e-9 m float tolerance.
    """
    if len(set(robot_ids)) != len(robot_ids):
        raise ValueError("duplicate robot_ids")
    if detections is None:
        return [Track(rid, "CAMERA_UNAVAILABLE", pose=poses.get(rid)) for rid in robot_ids], []
    tracks: dict[str, Track] = {rid: Track(rid, "NO_POSE") for rid in robot_ids if poses.get(rid) is None}
    eligible = [rid for rid in robot_ids if poses.get(rid) is not None]
    used: set[int] = set()
    limit = gate_m + _GATE_EPS
    if eligible and detections:
        size = max(len(eligible), len(detections))
        cost = [[_OUT_OF_GATE] * size for _ in range(size)]
        for i, rid in enumerate(eligible):
            pose = poses[rid]
            for j, seen in enumerate(detections):
                distance = math.hypot(seen.x - pose.x, seen.y - pose.y)
                if distance <= limit:
                    cost[i][j] = distance
        for i, j in enumerate(assign(cost)):
            if i < len(eligible) and j < len(detections) and cost[i][j] <= limit:
                rid = eligible[i]
                tracks[rid] = Track(rid, "MATCHED", round(cost[i][j], 4), detections[j], poses[rid])
                used.add(j)
    for rid in eligible:
        tracks.setdefault(rid, Track(rid, "NO_DETECTION", pose=poses[rid]))
    unknown = [seen for j, seen in enumerate(detections) if j not in used]
    return [tracks[rid] for rid in robot_ids], unknown


def better(a: Track, b: Track) -> Track:
    """The more informative track; on equal rank the first argument wins."""
    return a if STATUS_RANK[a.status] <= STATUS_RANK[b.status] else b
