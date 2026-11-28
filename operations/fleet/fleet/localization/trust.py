"""Which snapshot poses Fleet traffic and bays may use (D-395 §10, Phase 2 P2-2). Pure.

Only LOCALIZED map-frame snapshots are trusted. Missing, null, or unreadable
localization is UNKNOWN, never an implicit map pose. Traffic keeps out around the
last trusted pose, or blocks the whole track when none exists. After 30 seconds
of missing localization the cached position expires; trust never returns by timeout.
Fleet camera/operator MapPose is a separate evidence source (D-494, D-598).

"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Mapping, Optional, Sequence

from pydantic import ValidationError

from core_common.protocol.evidence import STALE_POSE_S
from core_common.protocol.localization import LocalizationStatus, LocState, PoseFrame
from fleet.traffic.config import HEADING_UNKNOWN_KEEP_OUT_M

TRUSTED = "trusted"
UNTRUSTED = "untrusted"

#: Contract §3: an untrusted robot keeps this clear around its last trusted pose.
UNTRUSTED_KEEP_OUT_M = HEADING_UNKNOWN_KEEP_OUT_M

#: Missing localization expires the last trusted position after a CORE restart.
LAPSED_GRACE_S = 30.0

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
    status = status_of(state)
    if status is None:
        return UNTRUSTED
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
    """The snapshot pose only when LOCALIZED in the map frame."""
    return _xy(state) if classify(state) == TRUSTED else None


def _segment_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    t = 0.0 if span == 0.0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def route_distance(route: Sequence[Point], point: Point) -> float:
    """Minimum Euclidean distance to the polyline, infinity for an empty route."""
    if len(route) < 2:
        return math.dist(point, route[0]) if route else math.inf
    return min(_segment_distance(point, a, b) for a, b in zip(route, route[1:]))


def blocks(route: Sequence[Point], last_trusted: Optional[Point],
           keep_out_m: float = UNTRUSTED_KEEP_OUT_M) -> bool:
    """Whether an untrusted robot blocks `route`.

    No trusted pose: it could be anywhere, so it blocks the whole track. An unknown
    route is not blocked by a located obstacle (traffic's "unknown never blocks")."""
    if last_trusted is None:
        return True
    return route_distance(route, last_trusted) < keep_out_m


def native_pose_freshness(state: Mapping, state_age_s: float = 0.0) -> Optional[bool]:
    """Use CORE timestamps within one packet and Fleet's packet age, without assuming synchronized clocks."""
    if not 0.0 <= state_age_s < STALE_POSE_S:
        return False
    channels = state.get("evidence")
    evidence = channels.get("pose") if isinstance(channels, Mapping) else None
    if evidence is None:
        return None  # legacy snapshot: insufficient evidence to dismiss an outstanding ladder
    if not isinstance(evidence, Mapping) or evidence.get("evidence") != "fresh":
        return False
    try:
        snapshot_at = datetime.fromisoformat(state["timestamp"])
        pose_at = datetime.fromisoformat(evidence["received_at"])
        pose_age_s = (snapshot_at - pose_at).total_seconds()
    except (KeyError, TypeError, ValueError):
        return False
    xy = _xy(state)
    return (0.0 <= pose_age_s and pose_age_s + state_age_s < STALE_POSE_S
            and xy is not None and all(math.isfinite(v) for v in xy))


def _without_resolved_ladder(view: Optional[Mapping], localized: bool) -> Optional[Mapping]:
    if not localized or view is None or view.get("candidates_for_s") is None:
        return view
    pose_request = view.get("pose_request") or {}
    return {**view, "rung": None, "candidates_for_s": None, "rung_missions": [],
            "needs_human": pose_request.get("state") == "needs_human"}


def ladder_for_state(state: Optional[Mapping], view: Optional[Mapping], *, state_age_s: float = 0.0) -> Optional[Mapping]:
    """Show the recovery ladder as resolved when this read proves current CORE localization."""
    localized = state is not None and classify(state) == TRUSTED and native_pose_freshness(state, state_age_s) is True
    return _without_resolved_ladder(view, localized)


def badge(state: Optional[Mapping], view: Optional[Mapping] = None, *,
          lapsed: bool = False, state_age_s: float = 0.0) -> Optional[dict]:
    """Console badge for one robot row; None when the robot is offline (no state).

    `view` is the localization service's per-robot view; its `needs_human` (the
    ladder's last rung) or the robot's own flag shows "위치 확인 필요".
    A previously escalated ladder clears from the badge once CORE supplies a fresh map pose."""
    if state is None:
        return None
    pose_fresh = native_pose_freshness(state, state_age_s)
    trusted = classify(state) == TRUSTED and pose_fresh is not False and not lapsed
    status = status_of(state)
    view = _without_resolved_ladder(view, trusted and pose_fresh is True)
    pose_request = (view or {}).get("pose_request") or {}
    pose_request_needs_human = pose_request.get("state") == "needs_human"
    needs_human = bool((view or {}).get("needs_human")) or bool(status and status.needs_human)
    label = (NEEDS_HUMAN_LABEL if needs_human
             else STATE_LABELS[status.state] if status is not None and (trusted or status.state is not LocState.LOCALIZED)
             else STATE_LABELS[LocState.UNKNOWN])
    return {"state": status.state.value if status else LocState.UNKNOWN.value,
            "pose_frame": status.pose_frame.value if status else None,
            "trusted": trusted, "legacy": False, "needs_human": needs_human,
            "label": label, **({"pose_request_needs_human": True} if pose_request_needs_human else {})}
