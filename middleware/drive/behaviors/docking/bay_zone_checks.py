"""core_features.docking.bay_zone_checks — the zone phase's map / facing / track gates, split from bay_zone_phases.py for the 600-line limit (D-766).

_map_frame_mismatch, _map_verified (Nav2 staging by the map needs a verified map), _facing_recent (the last LiDAR bay pose faced the bay) and _track_gate (the gates of a
TRACKED pose). A BayPhases mixin; ROS-free.
"""

from __future__ import annotations

import math
from typing import Optional

from core_features.docking.bay_zone import map_offsets, scan_fit_pose


class BayZoneChecksMixin:
    def _map_frame_mismatch(self, pose) -> Optional[str]:
        """A Nav2 start (the map pose says "outside the row") with a good LiDAR scan pose of the bay that puts the robot elsewhere than the map
        does: the SLAM map restarted or drifted since the dock was taught (its origin is the robot's start pose; scan matching runs only after
        0.5 m / 0.5 rad of travel, so inside a bay the map is dead reckoning). Refuse with the numbers instead of driving by it."""
        h, cfg = self._h, self._h._cfg
        m = self._scan_match[0] if self._scan_match is not None else None
        if (pose is None or m is None or m.inliers < cfg.bay_scan_inlier_min or m.margin < cfg.bay_scan_margin_min
                or abs(m.heading) > cfg.bay_scan_heading_max_rad):
            return None
        along, lateral, _ = map_offsets(pose, h._dock)
        gap = math.hypot(along - m.x, lateral + m.y)
        if gap <= cfg.bay_map_scan_tol_m:
            return None
        return ("map frame does not match the LiDAR: the dock's map pose puts the robot %.2f m from where the scan sees the bay "
                "(the SLAM map restarted or drifted since the dock was taught): teach the dock again" % gap)


    def _facing_recent(self, now: float, window_s: float = 10.0) -> bool:
        """The last LiDAR bay pose of this run (any age <= window) had the nose toward the bay: no forward move, no acquire on the camera."""
        ll = getattr(self, "_last_lidar", None)
        return ll is not None and now - ll[1] <= window_s and abs(math.remainder(ll[0] - math.pi, math.tau)) < math.pi / 2


    def _map_verified(self, pose) -> Optional[str]:
        """None = the map pose may be used for a Nav2 staging leg; else why not."""
        h, cfg = self._h, self._h._cfg
        if not h.localization_ok():
            return "localization is not LOCALIZED before Nav2 staging"
        if self._site_verified:
            return None
        m = self._scan_match[0] if self._scan_match is not None else None
        if m is not None and pose is not None and scan_fit_pose(m, cfg) is not None and self._map_frame_mismatch(pose) is None:
            return None
        return ("the map frame is not verified: site_pose_evidence not accepted (%s) and no good LiDAR bay fit (inliers %s, margin %s) agreeing with the map pose"
                % (self._site_refusal or "none given", "-" if m is None else "%.2f" % m.inliers, "-" if m is None else "%.2f" % m.margin))


    def _track_gate(self, match) -> Optional[str]:
        """Gates of a TRACKED pose (no margin): inliers, heading, and inside the rails the lateral; the jump, lane and rear-gap gates follow in ls_note."""
        cfg = self._h._cfg
        if match is None or not all(math.isfinite(v) for v in (match.x, match.y, match.heading, match.inliers)):
            return "no fit"
        floor = cfg.bay_junction_inlier_min if (self._pitin and match.x > cfg.bay_line_x_m) or self._zone == "centre" else cfg.bay_track_inlier_min       # at the junction the scene is seen from far
        if match.inliers < floor:
            return "inliers %.2f < %.2f" % (match.inliers, floor)
        facing = self._zone == "centre"                    # back-out / centring: the nose is toward the bay, heading ~180
        if (abs(math.remainder(match.heading - math.pi, math.tau)) > cfg.bay_junction_heading_rad + 0.2) if facing else abs(match.heading) > cfg.bay_scan_heading_max_rad:
            return "heading %.0f deg" % math.degrees(match.heading)
        if match.x <= cfg.bay_track_rail_x_m and abs(match.y) > cfg.bay_track_rail_lateral_m:
            return "lateral %.0f mm inside the rails (limit %.0f mm)" % (abs(match.y) * 1000.0, cfg.bay_track_rail_lateral_m * 1000.0)
        return None
