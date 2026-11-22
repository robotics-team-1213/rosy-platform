"""core_features.docking.site_pose — CORE's judgement of the site pose evidence a dock command carries (Fleet session contract).

A reference-scan bay dock stages by the map (Nav2) only when this accepts: anchor_source in cfg.site_pose_anchor_sources (sighting, track), anchor_age_s within
cfg.site_pose_max_anchor_age_s, camera_residual_m present and within cfg.site_pose_max_camera_residual_m, map_id equal to the robot's. anchor_age_s is used, `at`
never (host clocks differ by ~21 s). POSITION only: heading and the bay entry stay with the LiDAR reference scan. ROS-free.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Tuple


def _get(evidence: Any, name: str):
    return evidence.get(name) if isinstance(evidence, dict) else getattr(evidence, name, None)


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def judge_site_pose(evidence: Any, cfg: Any, robot_map_id: Optional[str]) -> Tuple[bool, Optional[str]]:
    """(accepted, reason when not)."""
    if evidence is None:
        return False, "no site_pose_evidence in the dock command"
    source = _get(evidence, "anchor_source")
    if source not in cfg.site_pose_anchor_sources:
        return False, "anchor_source %r is not accepted (accepted: %s)" % (source, ", ".join(cfg.site_pose_anchor_sources))
    age = _number(_get(evidence, "anchor_age_s"))
    if age is None or age < 0.0 or age > cfg.site_pose_max_anchor_age_s:
        return False, "anchor_age_s %r is missing or older than %.0f s" % (_get(evidence, "anchor_age_s"), cfg.site_pose_max_anchor_age_s)
    residual = _number(_get(evidence, "camera_residual_m"))
    if residual is None or residual < 0.0 or residual > cfg.site_pose_max_camera_residual_m:
        return False, "camera_residual_m %r is missing or above %.2f m" % (_get(evidence, "camera_residual_m"), cfg.site_pose_max_camera_residual_m)
    map_id = _get(evidence, "map_id")
    if not robot_map_id:
        return False, "the robot's map id is unknown"
    if map_id != robot_map_id:
        return False, "map_id %r is not the robot's map %r" % (map_id, robot_map_id)
    return True, None
