"""core_features.docking.bay_lidar_steer — inside the rails ALIGNING steers on the LiDAR scan pose, not on the camera line.

y8xs survey (loop/survey-1795184961.json): inside x <= 0.21 the camera line heading is wrong by -11..-19 deg and its along drifts, while the
LiDAR scan pose (the stored seated reference scan matched to the live scan) is right; steering on the camera at saturated w yawed the robot to
-15 deg in the last 4 cm of every reverse. For a dock with a reference scan, once the along is <= bay_lidar_steer_along_m the phase asks the
bay scan pose every bay_lidar_ask_s (the cached reference grid: ~0.1 s on the Pi), steers on its lateral and heading with the angular rate
bounded by bay_rail_max_angular, and uses the camera only for the along/guards it already had. No fresh pose (bay_scan_fresh_s) there: stop, and
fail after bay_lidar_pose_grace_s; the camera is never the fallback inside the rails. A mixin of `BayPhases`. ROS-free.
"""

from __future__ import annotations

from typing import Optional

import math

from core_features.docking.bay_zone import lane_extent, pose_gate, scan_fit_pose
from core_features.docking.model import DockPhase


class BayLidarSteerMixin:
    def _init_ls(self) -> None:
        self._lp: Optional[tuple] = None         # (x out of the stop face, lateral, heading, answered at, odometry travel then)
        self._lp_start: Optional[float] = None   # when ALIGNING began waiting for its first pose
        self._lp_ask_at = -1e9
        self._last_drop = "none"
        self._lp_lost_since: Optional[float] = None
        self._lp_hist: list = []                 # the laterals of the accepted LiDAR poses (the rail entrance judges their mean)
        self._rail_judged = False
        self._judge_wait: Optional[float] = None
        self._x_now = None
        self._ls_cap = None
        self._rear_along = None

    def _reset_ls(self) -> None:
        self._init_ls()

    def _has_reference(self) -> bool:
        dock = self._h._dock
        return dock is not None and isinstance(getattr(dock, "metadata", {}).get("reference_scan"), dict)

    def ls_ask(self, now: float):
        """True when ALIGNING wants a fresh LiDAR bay pose now (scan_request opens the request)."""
        h = self._h
        if h.phase is not DockPhase.ALIGNING or not self._has_reference() or self._req_open is not None:
            return False
        if now - self._lp_ask_at < h._cfg.bay_lidar_ask_s:
            return False
        self._lp_ask_at = now
        return True

    def _ls_drop(self, why: str) -> None:
        self._last_drop = why
        self._h._last_event = "LiDAR pose dropped (align): " + why

    def ls_note(self, match, at: float) -> None:
        h = self._h
        cfg = h._cfg
        # fit gates and this bay's lane, but no staging-distance gate: ALIGNING starts at the staging point, beyond the row (x ~ 0.36)
        why = pose_gate(match, cfg)
        if why == "no fit" and self._track_why:
            why = self._track_why
        if why is not None and why.startswith("margin") and not self._ans_track and self._lp is None:
            why = self._first_acquisition(match, at)          # case I: a weak global margin in the row, accepted only on the rear gap
        if why is not None:
            return self._ls_drop(why)
        geo = (match.x, -match.y, match.heading)
        if self._lp is None and self._entry_match is not None:
            # R3: the first ALIGNING pose must agree with the LiDAR values of the entry window (taken stopped moments earlier)
            ent = scan_fit_pose(self._entry_match[0], cfg)
            if ent is not None and (abs(geo[1] - ent[1]) > cfg.bay_lidar_first_jump_m or abs(geo[2] - ent[2]) > cfg.bay_lidar_jump_rad):
                return self._ls_drop("first pose vs the entry window: lateral %.0f vs %.0f mm, heading %.1f vs %.1f deg" % (
                    geo[1] * 1000.0, ent[1] * 1000.0, math.degrees(geo[2]), math.degrees(ent[2])))
        if self._lp is not None:
            # A jump from the previous pose is not evidence (a wrong fit or another bay), but the robot moves and turns between two poses: the allowance
            # grows with the time since the previous one (round y8xs C3: a 0.7-1 s match under load plus the 0.15 rad/s steer = 6-9 deg > the flat 5 deg gate,
            # so every pose was dropped and the reverse stopped "no fresh pose").
            dt = min(1.0, max(0.0, at - self._lp[3]))          # capped: a long gap is not an excuse for a big jump
            allow_h = cfg.bay_lidar_jump_rad + cfg.bay_rail_max_angular * dt
            allow_l = cfg.bay_lidar_jump_m + cfg.bay_reverse_speed * dt * 0.5
            if abs(geo[1] - self._lp[1]) > allow_l or abs(geo[2] - self._lp[2]) > allow_h:
                return self._ls_drop("jump from the previous pose: lateral %.0f vs %.0f mm (allowed %.0f), heading %.1f vs %.1f deg (allowed %.1f), dt %.2f s" % (
                    geo[1] * 1000.0, self._lp[1] * 1000.0, allow_l * 1000.0, math.degrees(geo[2]), math.degrees(self._lp[2]), math.degrees(allow_h), dt))
        body, seat = self._body_fresh(at), self._seat_gap
        if (body is not None and body[2] is not None and seat is not None and h._dock is not None and seat[0] == h._dock.id
                and abs(geo[0] - (body[2] - seat[1])) > cfg.bay_lidar_x_gap_tol_m):
            return self._ls_drop("scan x %.3f vs rear gap - seated gap %.3f (tol %.3f)" % (geo[0], body[2] - seat[1], cfg.bay_lidar_x_gap_tol_m))
        travelled = abs(h.executor.travelled_m()) if h.executor is not None else 0.0
        self._lp = (geo[0], geo[1], geo[2], at, travelled)
        self._row_pose = (geo[0], geo[1], geo[2], at, travelled)           # tracking starts from the first accepted pose
        self._lp_hist = (self._lp_hist + [geo[1]])[-8:]

    def _first_acquisition(self, match, at: float) -> Optional[str]:
        """FIRST pose of a dock run inside the bay (case I) whose global margin is weak (self-similar bays: a one-pitch shift fits at 0.6-0.67).
        Accepted only when the rear gap confirms x, the pose is near the seat and straight, and the best fit beats the next by the margin for
        this evidence: seated at this dock earlier (prior) bay_first_margin_prior, else bay_first_margin_noprior and the identity stays
        "unconfirmed". Below bay_first_margin_wrong it is another bay. Alias risk: a one-pitch lateral alias has |y| ~ 0.21 > bay_first_lateral_m
        and a rear gap that does not change with the shift, so only a within-5-cm lateral alias is left, and the margin gate covers that. A robot sitting in the NEIGHBOUR bay sees the same rear gap but |y| ~ 0.21 against this reference: refused by the
        lateral window, never taken for this bay.
        Returns None = accepted, else the reason."""
        h, cfg = self._h, self._h._cfg
        body, seat = self._body_fresh(at), self._seat_gap
        if body is None or body[2] is None or seat is None or h._dock is None or seat[0] != h._dock.id:
            return "margin %.2f < %.2f and no rear gap to confirm the first pose" % (match.margin, cfg.bay_scan_margin_min)
        x_gap = body[2] - seat[1]
        prior = getattr(h, "_seated_dock_id", None) == h._dock.id
        need = cfg.bay_first_margin_prior if prior else cfg.bay_first_margin_noprior
        if match.margin < cfg.bay_first_margin_wrong:
            return "first pose margin %.2f < %.2f: another bay" % (match.margin, cfg.bay_first_margin_wrong)
        if match.margin < need:
            return "first pose margin %.2f < %.2f (%s): ambiguous" % (match.margin, need, "prior" if prior else "no prior")
        if (match.inliers < cfg.bay_first_inlier_min or match.x > cfg.bay_first_x_max_m or abs(match.x - x_gap) > cfg.bay_lidar_x_gap_tol_m
                or abs(match.y) > cfg.bay_first_lateral_m or abs(match.heading) > cfg.bay_first_heading_rad):
            return "first pose x %.3f (rear gap %.3f) y %.3f heading %.1f deg inliers %.2f outside the first-acquisition window" % (
                match.x, x_gap, match.y, math.degrees(match.heading), match.inliers)
        self.bay_identity = "confirmed" if prior else "unconfirmed"
        h._last_event = "first LiDAR pose accepted on the rear gap: margin %.2f, bay identity %s" % (match.margin, self.bay_identity)
        return None

    def _lp_lat(self) -> str:
        lat = getattr(self, "_req_lat", None)
        return "?" if lat is None else "%.2f s" % lat

    def _lidar_steer(self, now: float):
        """None = camera steering as before (no reference scan, or not in the rails); "stop" = handled this tick; "use" = self._est now
        holds the LiDAR lateral and heading."""
        h, cfg = self._h, self._h._cfg
        if h.phase is not DockPhase.ALIGNING or not self._has_reference():
            return None                      # nothing of a previous attempt's rails state applies outside ALIGNING
        along = self._lp[0] if self._lp is not None else self._along_m
        if self._lp is None and along is None:
            # No pose yet and the camera cannot measure the along: wait for the first LiDAR pose, never steer on the camera blind
            self._lp_start = now if self._lp_start is None else self._lp_start
            self._stop()
            if now - self._lp_start > cfg.bay_lidar_pose_grace_s + cfg.bay_scan_pose_wait_s:
                h._fail("bay no LiDAR pose and no measured along: stopped (not steering on the camera)")
            return "stop"
        if along is None or along > cfg.bay_lidar_steer_along_m:
            return None
        if self._lp is None or now - self._lp[3] > cfg.bay_scan_fresh_s + cfg.bay_lidar_ask_s:
            self._stop()
            self._gap_hist = []                       # standing still is not a stall: the stall window restarts when the reverse does
            self._lp_lost_since = now if self._lp_lost_since is None else self._lp_lost_since
            wait = cfg.bay_lidar_pose_grace_s + (cfg.bay_scan_pose_wait_s if self._lp is None else 0.0)     # the first pose has the match time
            if now - self._lp_lost_since > wait:
                lat = self._lp_lat()
                h._fail("bay no fresh LiDAR pose for the reverse: stopped (the camera is not trusted); last pose %s ago, last match took %s, last drop: %s" % (
                    "none" if self._lp is None else "%.1f s" % (now - self._lp[3]), lat, self._last_drop))
            return "stop"
        self._lp_lost_since = None
        if self._lp[0] <= cfg.bay_line_x_m and lane_extent(cfg, self._lp[1], self._lp[2]) > cfg.bay_lane_edge_m:
            self._stop()                       # inside the bay's lines the body centre may not leave the lane (user rule 2026-11-21)
            h._last_event = "lane keeping: left the lane (lateral %.0f mm at x %.2f m)" % (self._lp[1] * 1000.0, self._lp[0])
            h._fail("bay left the lane: the body footprint reaches past %.0f mm (lateral %.0f mm, heading %.0f deg) at x %.2f m: stopped" % (
                cfg.bay_lane_edge_m * 1000.0, self._lp[1] * 1000.0, math.degrees(self._lp[2]), self._lp[0]))
            return "stop"
        self._est = (self._lp[1], self._lp[2])
        # Inside the rails the LiDAR x, not the camera along, bounds the travel and the rear guard, and the camera slip rule is off
        travelled = abs(h.executor.travelled_m()) if h.executor is not None else 0.0
        x_now = self._lp[0] - max(0.0, travelled - self._lp[4])
        cap = self._lp[4] + max(0.0, self._lp[0]) + cfg.bay_travel_margin_m      # absolute: the travel at the pose + the x left
        self._travel_cap_m = cap if self._ls_cap is None else min(self._ls_cap, cap)   # only ever tightened: a body stuck at the seat keeps its cap
        self._ls_cap = self._travel_cap_m
        self._slip = None
        seat = self._seat_gap
        self._x_now = x_now
        # R6: a reference scan with no rear-band point gives no seated gap: the camera along feeds the rear guard (its old behaviour) instead of none
        self._rear_along = (x_now + cfg.bay_turn_rear_overhang_m + seat[1]
                            if seat is not None and h._dock is not None and seat[0] == h._dock.id else self._along_m)
        return "use"