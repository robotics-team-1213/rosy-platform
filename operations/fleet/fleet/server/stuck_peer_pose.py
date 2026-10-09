"""Trusted map poses and peer bands used by the Fleet stuck resolver."""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Optional


def _pose_of(row: Mapping) -> Optional[tuple[float, float, float]]:
    pose = (row.get("state") or {}).get("pose") or {}
    try:
        return float(pose["x"]), float(pose["y"]), float(pose.get("yaw", 0.0))
    except (KeyError, TypeError, ValueError):
        return None


def _map_pose(row: Mapping) -> Optional[tuple[float, float, float]]:
    """Painted-map xy. A legacy snapshot has no localization block (D-395).

    LOCALIZED + map is the same xy. An odom-frame pose is not the painted track,
    and the twist integrator in body_stop is the command, not this pose.
    """
    from fleet.localization.trust import LEGACY, TRUSTED, classify

    state = row.get("state")
    if not row.get("online", True) or not isinstance(state, Mapping):
        return None
    verdict = classify(state)
    if verdict not in (LEGACY, TRUSTED):
        return None
    if "localization" in row:
        # Console owns the D-395 restart grace. Null raw localization is not
        # legacy while its current badge says the map pose is untrusted.
        badge = row["localization"]
        if not isinstance(badge, Mapping) or badge.get("trusted") is not True:
            return None
        if (badge.get("legacy") is True) != (verdict == LEGACY):
            return None
    return _pose_of(row)


def peer_ahead(row: Mapping, rows: Iterable[Mapping], config) -> Optional[bool]:
    """R1's judgement: an online peer inside the front band. None = this robot has no pose.

    Shared with the Fleet stuck-episode log, so the recorded value is what R1 would see."""
    return _peer_in_band(row, rows, config, 1.0)


def peer_behind(row: Mapping, rows: Iterable[Mapping], config) -> Optional[bool]:
    """D-577 1: R1's band mirrored behind the robot, on trust-gated map poses (D-395) only.

    None = an online peer exists and this robot's or a peer's pose is missing or untrusted:
    R3 must not back off blind (safety review 2026-10-09). No online peer = False."""
    others = [other for other in rows if other is not row and other.get("online", True)]
    if not others:
        return False
    return _peer_in_band(row, others, config, -1.0, pose_of=_map_pose, strict=True)


def _peer_in_band(row: Mapping, rows: Iterable[Mapping], config, sign: float, *,
                  pose_of=_pose_of, strict: bool = False) -> Optional[bool]:
    me = pose_of(row)
    if me is None:
        return None
    x0, y0, yaw = me
    c, s = math.cos(yaw), math.sin(yaw)
    for other in rows:
        if other is row or not other.get("online", True):
            continue
        pose = pose_of(other)
        if pose is None:
            if strict:
                return None
            continue
        dx, dy = pose[0] - x0, pose[1] - y0
        ahead, side = sign * (c * dx + s * dy), -s * dx + c * dy
        if 0.0 < ahead <= config.peer_reach_m + config.peer_radius_m and abs(side) <= config.peer_band_half_width_m:
            return True
    return False
