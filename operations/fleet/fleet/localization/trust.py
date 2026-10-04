"""Which snapshot poses Fleet traffic and bays may use (D-395 §10, Phase 2 P2-2). Pure.

A robot whose snapshot carries `localization` is trusted only when it is LOCALIZED
with its pose in the map frame. Otherwise its pose is skipped: the robot becomes a
wide obstacle (`UNTRUSTED_KEEP_OUT_M`) at its last trusted pose, or blocks the whole
track when it never had one. A snapshot without `localization` (`null` or absent)
is a robot that predates D-395: contract §3 keeps today's behaviour for it and the
console shows "위치 상태 미보고" (open question 2, decided).

A last trusted pose comes only from a LOCALIZED map snapshot, never from a legacy one
(S2 Finding 1: a power-on odom pose read before loc_assist was up became the keep-out
centre once the robot reported CANDIDATES). A robot that has reported localization and
then goes null (a CORE restart) is not legacy: the console treats it as untrusted until
it has been null for `LAPSED_GRACE_S` (`badge(..., lapsed=True)`).
"""

from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence

from pydantic import ValidationError

from core_common.protocol.localization import LocalizationStatus, LocState, PoseFrame

TRUSTED = "trusted"
UNTRUSTED = "untrusted"
LEGACY = "legacy"

#: Contract §3: an untrusted robot keeps this clear around its last trusted pose.
UNTRUSTED_KEEP_OUT_M = 0.45

#: A robot that reported localization and then went null stays untrusted this long before
#: it counts as legacy again. 30 s covers a CORE restart (whose node comes back reporting)
#: without pinning a robot whose D-395 stack was really removed forever.
LAPSED_GRACE_S = 30.0

LEGACY_LABEL = "위치 상태 미보고"
NEEDS_HUMAN_LABEL = "위치 확인 필요"
STATE_LABELS = {
    LocState.UNKNOWN: "위치 모름",
    LocState.CANDIDATES: "위치 후보 중재 중",
    LocState.LOCALIZED: "위치 확정",
    LocState.SUSPECT: "위치 의심",
}

Point = tuple[float, float]


def status_of(state: Optional[Mapping]) -> Optional[LocalizationStatus]:
    """The snapshot's LocalizationStatus; None when absent or malformed."""
    raw = (state or {}).get("localization")
    if raw is None:
        return None
    try:
        return LocalizationStatus.model_validate(raw)
    except ValidationError:
        return None


def classify(state: Optional[Mapping]) -> str:
    if (state or {}).get("localization") is None:
        return LEGACY
    status = status_of(state)
    if status is None:
        return UNTRUSTED            # present but unreadable: never trust it
    if status.state is LocState.LOCALIZED and status.pose_frame is PoseFrame.MAP:
        return TRUSTED
    return UNTRUSTED


def _xy(state: Optional[Mapping]) -> Optional[Point]:
    pose = (state or {}).get("pose") or {}
    try:
        return float(pose["x"]), float(pose["y"])
    except (KeyError, TypeError, ValueError):
        return None


def trusted_xy(state: Optional[Mapping]) -> Optional[Point]:
    """The snapshot pose when it may become a last trusted pose (LOCALIZED, map), else None.

    A legacy snapshot's pose is used live while the robot stays legacy, never stored."""
    return _xy(state) if classify(state) == TRUSTED else None


def _segment_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    t = 0.0 if span == 0.0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def blocks(route: Sequence[Point], last_trusted: Optional[Point],
           keep_out_m: float = UNTRUSTED_KEEP_OUT_M) -> bool:
    """Whether an untrusted robot blocks `route`.

    No trusted pose: it could be anywhere, so it blocks the whole track. An unknown
    route is not blocked by a located obstacle (traffic's "unknown never blocks")."""
    if last_trusted is None:
        return True
    if not route:
        return False
    if len(route) == 1:
        return math.dist(route[0], last_trusted) < keep_out_m
    return any(_segment_distance(last_trusted, route[i], route[i + 1]) < keep_out_m
               for i in range(len(route) - 1))


def badge(state: Optional[Mapping], view: Optional[Mapping] = None, *,
          lapsed: bool = False) -> Optional[dict]:
    """Console badge for one robot row; None when the robot is offline (no state).

    `view` is the localization service's per-robot view; its `needs_human` (the
    ladder's last rung) or the robot's own flag shows "위치 확인 필요". `lapsed`: a
    D-395 robot inside its null grace, shown untrusted rather than legacy."""
    if state is None:
        return None
    verdict = classify(state)
    if verdict == LEGACY and lapsed:
        verdict = UNTRUSTED
    if verdict == LEGACY:
        return {"state": None, "pose_frame": None, "trusted": True, "legacy": True,
                "needs_human": False, "label": LEGACY_LABEL}
    status = status_of(state)
    needs_human = bool((view or {}).get("needs_human")) or bool(status and status.needs_human)
    label = (NEEDS_HUMAN_LABEL if needs_human
             else STATE_LABELS[status.state] if status is not None else STATE_LABELS[LocState.UNKNOWN])
    return {"state": status.state.value if status else None,
            "pose_frame": status.pose_frame.value if status else None,
            "trusted": verdict == TRUSTED, "legacy": False, "needs_human": needs_human,
            "label": label}
