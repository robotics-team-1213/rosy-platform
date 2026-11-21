"""core_features.docking.bay_centre — a pit-in arrival at the junction a few cm off the bay axis centres itself before it turns (user 2026-11-21: like a robot vacuum).

Facing the bay at the junction with 3-6 cm of lateral (bay_junction_lateral_m): a forward-and-back shuttle on its own line, steered by the LiDAR bay pose.
The forward leg creeps toward the bay with the heading offset a = clamp(gain * y, 0.35) (heading 180 + a drives y down), the reverse leg backs out with 180 - a
(reversing flips the sign); each leg ends when |lateral| <= bay_first_lateral_m, at bay_centre_min_x_m (forward), or back at the start x (reverse), and the zone verdict
then runs again on a fresh pose (and turns). Bounded: travel <= bay_centre_max_travel_m per leg, never closer than bay_centre_min_x_m (outside the bay line, so the
lane footprint guard is not involved), at most bay_centre_tries shuttles, a fresh pose on every tick, the front gap (forward) and the rear gap (reverse) watched; a
robot in the bay is refused before this starts. No pose / no progress = stop and call a person. A BayPhases mixin; ROS-free.
"""

from __future__ import annotations

import math
from typing import Optional

from core_features.docking.bay_zone import expected_front_gap, lane_edge, lane_extent
from core_features.docking.parking import wrap as _wrap


class BayCentreMixin:
    def _init_centre(self) -> None:
        self._cen: Optional[dict] = None
        self._cen_pose: Optional[tuple] = None        # (BayScanPose, answered at, odometry travel then)
        self._cen_n = 0

    def centre_begin(self, now: float) -> bool:
        """The zone verdict found the junction pose off the axis: start centring (False = tries used up)."""
        h, cfg = self._h, self._h._cfg
        if self._cen_n >= cfg.bay_centre_tries:
            return False
        self._cen_n += 1
        h.executor.reset_odometry_mark()
        self._cen, self._cen_pose = {"since": now, "lost": None, "leg": "swing_f", "x0": None, "mark": 0.0}, None
        self._zone = "centre"
        h._last_event = "pit-in: centring on the bay axis (try %d/%d)" % (self._cen_n, cfg.bay_centre_tries)
        return True

    def backout_begin(self, now: float, geo, match=None) -> None:
        """Nose toward the bay inside the lane: back straight OUT along the lane (LiDAR-steered, rear = away from the bay, footprint guard and rear gap watched) to the
        junction, then the zone verdict runs again (pit-in turn). Never toward the bay, never an in-place turn inside the row."""
        h = self._h
        if h.executor is None:
            h._fail("bay executor unavailable")
            return
        h.executor.reset_odometry_mark()
        self._cen = {"since": now, "lost": None, "leg": "backout", "x0": geo[0], "mark": 0.0, "start": (geo[0], -geo[1], geo[2])}
        # the accepted start pose (row gates, or junction-level + depth) is the first TRACKED pose: the next ones are local ICP from it carried by the odometry
        self._cen_pose = None if match is None else (match, now, 0.0)
        self._zone, self._facing_bay = "centre", True
        h._last_event = "pit-in: nose toward the bay inside the lane (LiDAR x %.3f, lateral %.0f mm, heading %.0f deg): backing out along the lane to the junction" % (
            geo[0], geo[1] * 1000.0, math.degrees(geo[2]))

    def no_staging_retry(self, phase) -> bool:
        """A pit-in dock (turned, backing out or centring at the junction, or facing the bay) never retries through the forward back-off + Nav2 staging + a turn at the
        staging point: it fails (person call) unless the reseat loop (ALIGNING / SETTLING) takes it."""
        from core_features.docking.model import DockPhase  # noqa: PLC0415
        return (self._pitin or self._facing_bay or self._zone == "centre") and phase not in (DockPhase.ALIGNING, DockPhase.SETTLING)

    def new_dock(self) -> None:
        """A new dock run: nothing of the last one may steer it (a stale _zone_checked skipped the zone check and sent the robot to Nav2 staging, b8xy nosein-4)."""
        self.clear_run_state()
        self.bay_identity = "unknown"                    # set by the evidence of THIS run (row-gate fit / weak first or junction fit)
        key = getattr(self, "_seat_key", None)
        if key is not None and key != self._ref_key():   # the dock's reference scan was re-taught: the cached seated gap / depth points are the OLD scan's
            self._ref_points, self._seat_gap, self._seat_gap_asked, self._seat_key = None, None, None, None

    def clear_run_state(self) -> None:
        """The end of a run (fail / cancel / DOCKED) and the start of the next: no bay state outlives it, so a status read after a cancel is not stale. The identity
        evidence stays readable until the next dock starts."""
        self._zone_checked, self._zone, self._cen, self._cen_pose, self._cen_n = False, None, None, None, 0
        self._pitin = self._facing_bay = False
        self._scan_match, self._scan_asked, self._row_pose, self._entry_match, self._find_match, self._seat_match = None, False, None, None, None, None
        self._req_open = None
        self._last_lidar = None

    def _cen_seed(self):
        """The carried pose for a tracked request: the last accepted pose moved by the odometry travel since (back-out and the reverse leg: x grows; the forward leg: x falls)."""
        c, (m, _, t0) = self._cen, self._cen_pose
        sign = {"backout": 1.0, "rev": 1.0, "fwd": -1.0}.get(c["leg"], 0.0)
        return m.x + sign * max(0.0, abs(self._h.executor.travelled_m()) - t0), m.y, m.heading

    def centre_request_due(self, now: float) -> bool:
        return self._zone == "centre" and self._cen is not None and self._req_open is None and now - self._ap_ask_at >= self._h._cfg.bay_lidar_ask_s

    def _backout_pose_ok(self, m) -> bool:
        """While backing out: facing the bay within the window, in the lane, and a row-gate fit (0.70 / 0.40) or the junction-level fit once it is at the junction."""
        cfg = self._h._cfg
        if not (math.isfinite(m.x) and abs(_wrap(m.heading - math.pi)) <= cfg.bay_junction_heading_rad + 0.1 and abs(m.y) <= cfg.bay_lane_half_m):
            return False
        return m.inliers >= cfg.bay_junction_inlier_min       # a tracked pose: the start was accepted by the row gates / the junction-level rule; the track gate and the jump bound hold the rest

    def _tick_backout(self, now: float, c: dict, m, x: float, travel: float) -> None:
        h, cfg = self._h, self._h._cfg
        goal = cfg.bay_turn_x_target_m                              # the turn point (absolute), not the dock type's staging offset
        if x >= goal - 0.01:
            self._stop()
            self._cen, self._cen_pose, self._scan_match, self._scan_asked = None, None, None, False
            self._zone, h._phase_since = "check", now                   # at the junction: judged again, and it turns there
            h._last_event = "pit-in: backed out to x %.3f m (junction %.3f): judging the turn" % (x, goal)
            return
        if travel > min((goal - c["x0"]) + cfg.bay_backout_extra_m, cfg.bay_turn_x_max_m - c["x0"]):
            self._centre_fail("backed out %.0f mm without reaching the junction (x %.2f)" % (travel * 1000.0, x))
            return
        dh = cfg.bay_rail_max_angular * max(0.0, now - self._cen_pose[1])                 # the heading may have changed this much since the pose: the worse side
        if x < cfg.bay_turn_x_min_m and max(lane_extent(cfg, -m.y, m.heading - dh), lane_extent(cfg, -m.y, m.heading + dh)) > lane_edge(cfg, h._dock):      # the footprint guard holds all the way to the turn floor
            self._centre_fail("the body footprint would leave the lane (lateral %.0f mm, heading %.0f deg) at x %.2f" % (m.y * -1000.0, math.degrees(m.heading), x))
            return
        body = self._body_fresh(now)
        if body is None or body[2] is None:
            self._stop()                                           # no rear gap measured is not a free way behind (None must not pass)
            if now - c["since"] > cfg.bay_scan_wait_s + cfg.bay_lidar_pose_grace_s:
                self._centre_fail("no rear gap measured behind the tray")
            return
        if body[2] < cfg.bay_backout_rear_gap_m:
            self._centre_fail("something behind the tray within %.2f m (rear gap %.2f)" % (cfg.bay_backout_rear_gap_m, body[2]))
            return
        a = max(-0.1, min(0.1, cfg.bay_centre_gain * m.y)) if x <= cfg.bay_line_x_m else max(-0.35, min(0.35, cfg.bay_centre_gain * m.y))
        self._drive(-cfg.bay_backoff_speed, max(-cfg.bay_rail_max_angular, min(cfg.bay_rail_max_angular, 1.5 * _wrap(math.pi - a - m.heading))))

    def _centre_pose_ok(self, m) -> bool:
        """The shuttle moves within the junction: a good fit facing the bay (heading within the junction window + 11 deg: the legs swing it), x between the creep limit and
        the start, lateral inside the window plus 2 cm."""
        cfg, x0 = self._h._cfg, (self._cen or {}).get("x0")
        return (math.isfinite(m.x) and m.inliers >= cfg.bay_junction_inlier_min and abs(_wrap(m.heading - math.pi)) <= cfg.bay_junction_heading_rad + 0.2
                and abs(m.y) <= cfg.bay_junction_lateral_m + 0.02 and cfg.bay_centre_min_x_m - 0.03 <= m.x <= (m.x if x0 is None else x0 + 0.06))

    def _empty_front_reason(self, now: float, match):
        """None = the front gap matches the EMPTY bay seen from this LiDAR pose (modelled from the reference scan; the constant only as fallback); "wait" = no fresh body
        scan yet; else the reason it does not (occupied or not measurable)."""
        h, cfg = self._h, self._h._cfg
        body = self._body_fresh(now)
        if body is None or body[3] < h._phase_since:
            return "wait" if now - h._phase_since <= cfg.bay_scan_wait_s else "no fresh body scan to check that the bay is empty"
        ref = self._ref_points
        model = None
        if ref is not None and h._dock is not None and ref[0] == h._dock.id:
            model = expected_front_gap(ref[1], match.x, match.y, match.heading, cfg)
        expect = model if model is not None else match.x + cfg.bay_empty_front_extra_m
        if body[1] is None or body[1] < expect - cfg.bay_empty_front_tol_m or body[1] > expect + cfg.bay_empty_front_long_tol_m:
            return "front gap %.3f m but an empty bay gives %.3f m (LiDAR x %.3f): occupied or not measurable" % (body[1] or -1.0, expect, match.x)
        return None

    def _pit_in(self, now: float, junction, reason: str) -> None:
        """At the staging junction facing the bay (LiDAR pose): check that the bay is EMPTY by the front gap, then turn here to the LiDAR bay heading (no Nav2, no map)."""
        h, cfg = self._h, self._h._cfg
        odo, body = self._odometry(), self._body_fresh(now)
        if odo is None:
            h._fail("bay odometry unavailable")
            return
        if body is None or body[3] < h._phase_since:
            if now - h._phase_since > cfg.bay_scan_wait_s:
                h._fail("bay pit-in: no fresh body scan to check that the bay is empty")
            return                                          # the zone stays "check": look again next tick
        self._zone = None                                   # NOT _zone_checked: that flag is only for the "out" verdict's immediate hand-over to Nav2 staging (a stale True skipped the zone check of the NEXT dock)
        ref = self._ref_points
        model = None
        if ref is not None and h._dock is not None and ref[0] == h._dock.id and self._scan_match is not None:
            m = self._scan_match[0]
            model = expected_front_gap(ref[1], m.x, m.y, m.heading, cfg)          # the empty bay seen from this pose (reference scan), not a constant
        expect = model if model is not None else junction[0] + cfg.bay_empty_front_extra_m
        shorter = body[1] is None or body[1] < expect - cfg.bay_empty_front_tol_m
        if shorter or body[1] > expect + cfg.bay_empty_front_long_tol_m:
            # facing the bay the front gap is the depth of the bay: x + 0.112 when empty; a robot in it (or an unmeasured depth) is never reversed into
            h._fail("bay pit-in: front gap %.3f m but an empty bay gives %.3f m (LiDAR x %.3f): occupied or not measurable, not turning in" % (body[1] or -1.0, expect, junction[0]))
            return
        self._stop()
        if abs(junction[1]) > cfg.bay_first_lateral_m:
            if not self.centre_begin(now):
                h._fail("bay pit-in: still %.0f mm off the axis after %d centring tries" % (abs(junction[1]) * 1000.0, cfg.bay_centre_tries))
                h._call_person("stopped at the junction: off the bay axis")
            return
        h._last_event = "pit-in: %s; front gap %.3f m = empty bay: turning here to heading 0, no Nav2 [bay %s: matched by LiDAR to its reference scan, margin %.2f]" % (
            reason, body[1], h._dock.id if h._dock is not None else "?", self._scan_match[0].margin if self._scan_match is not None else 0.0)
        m = self._scan_match[0] if self._scan_match is not None else None
        self.bay_identity = "confirmed" if m is not None and m.inliers >= cfg.bay_scan_inlier_min and m.margin >= cfg.bay_scan_margin_min else "unconfirmed"
        self._start_staging_turn(now, odo, bay_heading=junction[2])

    def _centre_fail(self, why: str) -> None:
        self._stop()
        name = "back-out" if self._cen is not None and self._cen.get("leg") == "backout" else "centring"
        self._cen = None
        self._h._fail("bay pit-in %s: %s" % (name, why))
        self._h._call_person("stopped at the junction: " + why)

    def _tick_centre(self, now: float) -> None:
        h, cfg = self._h, self._h._cfg
        c = self._cen
        if c is None:
            self._zone = "check"
            return
        pose = self._cen_pose
        stale = pose is None or now - pose[1] > cfg.bay_row_pose_fresh_s
        if stale or not (self._backout_pose_ok(pose[0]) if c["leg"] == "backout" else self._centre_pose_ok(pose[0])):
            self._stop()                                    # stand; the next answer decides; no pose for the grace = person
            c["lost"] = now if c["lost"] is None else c["lost"]
            if now - c["lost"] > cfg.bay_lidar_pose_grace_s:
                self._centre_fail("no fresh LiDAR bay pose at the junction for %.0f s" % cfg.bay_lidar_pose_grace_s)
            return
        c["lost"] = None
        travel = abs(h.executor.travelled_m())
        m = pose[0]
        if c["leg"] == "backout":
            self._tick_backout(now, c, m, m.x + max(0.0, travel - pose[2]), travel)         # backing out: x grows
            return
        x = m.x - max(0.0, travel - pose[2])
        if abs(m.y) <= cfg.bay_first_lateral_m and x < cfg.bay_turn_x_min_m and c["leg"] in ("swing_f", "fwd"):
            self._stop()
            c["leg"], c["mark"] = "swing_r", travel                  # centred but still below the turn floor: back out to where it started, then judge
            return
        if abs(m.y) <= cfg.bay_first_lateral_m and x >= cfg.bay_turn_x_min_m:
            self._stop()
            self._cen, self._cen_pose, self._scan_match, self._scan_asked = None, None, None, False
            self._zone = "check"                            # judge again: it turns now, on a fresh pose
            h._phase_since = now
            return
        if c["x0"] is None:
            c["x0"] = x
        leg_travel = travel - c["mark"]
        a = max(-0.35, min(0.35, cfg.bay_centre_gain * m.y))
        if c["leg"] in ("swing_f", "swing_r"):
            # the legs need opposite heading offsets (reversing flips the sign): swing in place to this leg's heading first, so the move does not undo the last one
            err = _wrap((math.pi + a if c["leg"] == "swing_f" else math.pi - a) - m.heading)
            body = self._body_fresh(now)
            if abs(err) <= 0.04:
                self._stop()
                c["leg"], c["mark"] = ("fwd" if c["leg"] == "swing_f" else "rev"), travel
                return
            if body is None or body[0] in ("near", "empty", "unknown"):
                self._stop()                                       # the tray sweep must be clear to turn, even this little
                if now - c["since"] > cfg.bay_centre_max_travel_m * 100.0:
                    self._centre_fail("the tray sweep is not clear for the swing")
                return
            self._drive(0.0, max(-0.3, min(0.3, 1.5 * err)))
            return
        if c["leg"] == "fwd":
            if x <= cfg.bay_centre_min_x_m or leg_travel > cfg.bay_centre_max_travel_m:
                self._stop()
                c["leg"], c["mark"] = "swing_r", travel              # back out toward the junction, heading flipped
                return
            block = self._forward_block(now, c["since"], 0.05, facing_ok=True)      # the centring forward leg is a deliberate creep toward the bay (front gap watched)
            if block is not None:
                self._stop()
                if block != "wait":
                    self._centre_fail(block)
                return
            self._drive(cfg.bay_backoff_speed, max(-cfg.bay_rail_max_angular, min(cfg.bay_rail_max_angular, 1.5 * _wrap(math.pi + a - m.heading))))
            return
        body = self._body_fresh(now)
        if x >= c["x0"] - 0.005 or leg_travel > cfg.bay_centre_max_travel_m + 0.02:
            self._stop()                                           # shuttle done and still off the axis: another shuttle, or the tries are used up
            self._cen, self._cen_pose, self._scan_match, self._scan_asked = None, None, None, False
            self._zone, h._phase_since = "check", now
            return
        if body is None or (body[2] is not None and body[2] < cfg.bay_exit_front_gap_m):
            self._stop()
            if body is not None:
                self._centre_fail("something behind within %.2f m" % cfg.bay_exit_front_gap_m)
            return
        self._drive(-cfg.bay_backoff_speed, max(-cfg.bay_rail_max_angular, min(cfg.bay_rail_max_angular, 1.5 * _wrap(math.pi - a - m.heading))))
