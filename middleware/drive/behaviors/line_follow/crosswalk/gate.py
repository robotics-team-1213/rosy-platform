"""D-573 manager glue; pure gate types and helpers retain their existing import paths."""
from __future__ import annotations
import logging
import math
from dataclasses import replace
from types import SimpleNamespace
from typing import Optional
from core_features.line_follow.crosswalk.zone import CORRIDOR_HALF_M, EVIDENCE_TTL_S, MAX_LATERAL_M, MAX_TURN_RAD, _angle

from .kernel import (
    NONE as NONE,
    ARMED as ARMED,
    APPROACHING as APPROACHING,
    LOOKING as LOOKING,
    WAITING as WAITING,
    CROSSING as CROSSING,
    HOLD_POSE_M as HOLD_POSE_M,
    PERSON as PERSON,
    UNKNOWN as UNKNOWN,
    STALE as STALE,
    LOST as LOST,
    Zone as Zone,
    Scan as Scan,
    Geometry as Geometry,
    scan_rays as scan_rays,
    _slab as _slab,
    judge as judge,
    _edge_sides as _edge_sides,
    judge_cells as judge_cells,
    CrosswalkGate as CrosswalkGate,
    lane_edges as lane_edges,
    zone_of as zone_of,
)


class CrosswalkGateMixin:
    """LineFollowManager glue (manager lock throughout). Default off (crosswalk_gate_enabled)."""

    def _init_crosswalk_gate(self) -> None:
        self._xwalk = CrosswalkGate()
        self._xwalk_scan: Optional[Scan] = None
        self._xwalk_corridor = (None, None, None, None)   # (received_at, odom epoch, image pose, corridor)

    @property
    def wants_crosswalk_scan(self) -> bool:
        with self._lock:
            return self._config.crosswalk_gate_enabled and self._mode.value == "CAMERA_LINE"

    def observe_crosswalk_scan(self, rays, *, range_min: Optional[float],
                               received_at: Optional[float] = None) -> None:
        """Every ray of one scan (``scan_rays``), for the look; range_min None = unknown."""
        now = self._clock() if received_at is None else received_at
        with self._lock:
            self._xwalk_scan = Scan(tuple(rays), None if range_min is None else float(range_min), float(now))

    def _crosswalk_geometry(self) -> Optional[Geometry]:
        """D-573 2 from the URDF body and the scan's range_min; None = unknown (stand)."""
        c, scan = self._config, self._xwalk_scan
        if not c.body_stop_known or scan is None or scan.range_min is None:
            return None
        v = min(c.crosswalk_cross_speed, c.cruise_speed)
        s_wait = max(c.derived_stop_gap_m(v),
                     scan.range_min - (c.body_front_x_m - c.body_lidar_x_m) + c.obstacle_body_margin_m)
        return Geometry(front_x=c.body_front_x_m, rear_x=c.body_rear_x_m, lidar_x=c.body_lidar_x_m,
                        v_cross=v, s_wait=s_wait, slow_from=c.derived_stop_gap_m(c.cruise_speed) + s_wait,
                        lane_half_m=CORRIDOR_HALF_M, body_half_m=c.body_half_width_m + c.obstacle_body_margin_m,
                        strip_m=c.crosswalk_approach_default_m,
                        exit_m=c.body_front_x_m - c.body_rear_x_m + c.derived_stop_gap_m(v),
                        end_margin=c.obstacle_body_margin_m)

    def _crosswalk_zones(self) -> list:
        """D-491 camera zones at their image pose (the shared odom anchor; own lifetime here)."""
        c, ev, out = self._config, self._return_evidence, []
        for z in self._crosswalks._zones:  # ponytail: shares the D-491 list; an accessor if a third reader comes
            if z["anchor"] is None and z["epoch"] == ev.epoch:
                z["anchor"] = ev._image_pose(z["stamp_ns"])
            if z["anchor"] is not None:
                out.append(zone_of(z, c.crosswalk_range_error_fraction, body_half_m=c.body_half_width_m))
        return out

    def _fresh_corridor(self, now: float, pose=None):
        """Seen now, else this odom run's last within EVIDENCE_TTL_S or standing still where it was seen (m25/m26)."""
        seen = self._seen_corridor(now)
        held_at, epoch, image, held = self._xwalk_corridor
        if seen is not None or held_at is None or epoch != self._return_evidence.epoch:
            return seen
        there = pose is not None and math.hypot(pose.x - image.x, pose.y - image.y) <= HOLD_POSE_M and abs(
            _angle(pose.yaw - image.yaw)) <= HOLD_POSE_M / .75 and self._standing_still(now)
        return held if 0.0 <= now - held_at <= EVIDENCE_TTL_S or there else None

    def _seen_corridor(self, now: float):
        """D-468 lane evidence as (lane pose, left, right, uncertainty_m, residual |slope|, seen-to x); None if stale,
        incomplete, looser than MAX_LATERAL_M or turned past MAX_TURN_RAD. D-573 개정 5 7항: the image pose turned
        along the edges' mean slope (the lane, not the body: m23 stood 0.1 rad off it), edges in that frame."""
        ev = self._return_evidence
        lane, at = ev._lane, ev._received_at
        if lane is None or at is None or lane.uncertainty_m is None or not 0.0 <= now - at <= EVIDENCE_TTL_S:
            return None
        if lane.uncertainty_m > MAX_LATERAL_M:  # m24: on the stripes (0.043 m, edges 0.08 m apart) it is no lane
            return None                         # D-491's bound for a zone's lane; the zone's own frame then
        edges = {b.side: b for b in lane.boundaries}
        image = ev._image_pose(round(lane.stamp * 1e9))
        if image is None or set(edges) != {"left", "right"}:
            return None
        slope = (edges["left"].slope + edges["right"].slope) / 2
        turn = math.atan(slope)
        if abs(turn) > MAX_TURN_RAD:
            return None
        # each edge's seen ends in the lane frame; the outermost keeps an edge that disagrees with the mean (review)
        side = {k: [math.cos(turn) * (b.slope * x + b.intercept_m) - math.sin(turn) * x
                    for x in (b.observed_x_min_m, b.observed_x_max_m)] for k, b in edges.items()}
        self._xwalk_corridor = (at, ev.epoch, image, (SimpleNamespace(x=image.x, y=image.y, yaw=image.yaw + turn), max(side["left"]),
                                     min(side["right"]), lane.uncertainty_m,
                                     max(abs(b.slope - slope) for b in edges.values()),
                                     min(b.observed_x_max_m for b in edges.values())))
        return self._xwalk_corridor[3]

    def _crosswalk_walls(self, now: float, pose):
        """D-573 rev 8: Fleet's map walls beside the lane (route prior, at its odom sample) as clip lines across
        the lane from the body now: inside each face by the map band + 3 sigma range, out again by the odom
        drift since that sample. None without a fresh prior with a wall, or on another odom run."""
        c, binding = self._config, self.route_guide_binding(now)
        prior = None if binding is None else binding['prior']
        if (c.crosswalk_map_wall_band_m is None or pose is None or prior is None or prior.wall_ahead_m is None
                or (prior.wall_left_m is None and prior.wall_right_m is None)):
            return None
        src = self._return_evidence._image_pose(binding.get('stamp_ns'))
        if src is None or src.frame != pose.frame:
            return None
        lane_yaw = src.yaw + math.radians(prior.heading_here_deg)
        dx, dy = pose.x - src.x, pose.y - src.y
        across = -math.sin(lane_yaw) * dx + math.cos(lane_yaw) * dy
        along = math.cos(lane_yaw) * dx + math.sin(lane_yaw) * dy
        inset = c.crosswalk_map_wall_band_m + 3.0 * c.crosswalk_range_sigma_m
        drift = c.crosswalk_odom_error_fraction * math.hypot(dx, dy)
        return (lane_yaw, None if prior.wall_left_m is None else prior.wall_left_m - across - inset + drift,
                None if prior.wall_right_m is None else prior.wall_right_m - across + inset - drift,
                prior.wall_ahead_m - along - drift)

    def _crosswalk_gate(self, now: float, decision):
        """Cap the tick's final decision; never lifts a zero (D-573 6)."""
        c = self._config
        if not c.crosswalk_gate_enabled or self._mode.value != "CAMERA_LINE":
            return decision
        pose = self._fresh_pose(now)
        cap, reason = self._xwalk.step(
            now, zones=self._crosswalk_zones(), pose=pose,
            key=None if pose is None else (self._return_evidence.epoch, pose.frame),
            still=self._standing_still(now), scan=self._xwalk_scan, geo=self._crosswalk_geometry(),
            cruise=c.cruise_speed, look_s=c.crosswalk_clear_s, min_scans=c.crosswalk_look_min_scans,
            report_s=c.crosswalk_report_s, stale_s=c.clearance_stale_s,
            odom_error_fraction=c.crosswalk_odom_error_fraction, range_sigma_m=c.crosswalk_range_sigma_m,
            persist_k=c.crosswalk_persist_k, persist_n=c.crosswalk_persist_n,
            corridor=self._fresh_corridor(now, pose), walls=self._crosswalk_walls(now, pose))
        if reason != getattr(self, '_xwalk_logged', None):   # diagnostics on stderr (ROS launch logs keep it)
            self._xwalk_logged = reason
            logging.getLogger(__name__).warning('crosswalk %s look=%s hit=%s', reason,
                                                getattr(self._xwalk, 'last_look', None), getattr(self._xwalk, 'last_hit', None))
        if cap is None:
            return decision
        if cap <= 0.0:
            if not (decision.linear or decision.angular):
                return decision
            linear = angular = 0.0
        elif decision.linear <= cap:
            return decision
        else:
            linear, angular = cap, decision.angular * cap / decision.linear  # same arc, slower
        if self._status.state not in ("LOST", "OFF"):
            update = {"linear": linear, "angular": angular}
            if reason is not None:
                update.update(state="HOLD", reason=reason)
            self._status = self._status.model_copy(update=update)
        return replace(decision, linear=linear, angular=angular)

    def _regulated_wait_share(self, now: float, dt: float, speed: Optional[float], clock: Optional[dict] = None) -> float:
        """D-507 13 / D-760 2b, for a maneuver's or an arc's clock: the seconds of the last dt a later
        gate took. All of it while a non-FREE D-517 authority, a D-573 look/wait or a crossing held by a
        return ahead (look_progress) stands the robot; a crossing's slower share against `speed`. dt
        counts at most stale_after_s, only with a matching previous tick that also lost time. With `clock`
        (the maneuver or arc, its 'added'): a HOLDING authority on both ticks in full, Fleet's live ttl
        bounds it (m33c: 30 s behind a parked robot); any other share, NONE/EXPIRED authority included,
        crosswalk_report_s + clear_s in all. Locked."""
        c = self._config
        wait = self._regulation_wait(now)
        if wait is not None:
            lost = 1.0
        else:
            xw = self._xwalk.status(now) or {}
            lost = max(0.0, 1 - c.crosswalk_cross_speed / speed) if xw.get("state") == CROSSING and speed else 0.0
        # uncapped only while Fleet is alive and says wait (HOLDING); NONE/EXPIRED keep the cap
        auth = wait == "authority" and self._authority_state(now)[0] == "HOLDING"
        previous = getattr(self, '_regulated_wait_sample', None)
        if previous is not None and now == previous[0]:
            self._regulated_wait_sample = (now, min(lost, previous[1]), auth and previous[2])
            return 0.0
        self._regulated_wait_sample = (now, lost, auth)
        if (previous is None or now <= previous[0]
                or abs(now - dt - previous[0]) > 1e-6):
            return 0.0
        share = max(0.0, min(dt, c.stale_after_s)) * min(lost, previous[1])
        if clock is None or (auth and previous[2]):
            return share
        share = min(share, c.crosswalk_report_s + c.crosswalk_clear_s - clock.get('added', 0.0))
        clock['added'] = clock.get('added', 0.0) + share
        return share

    def _regulation_wait(self, now: float) -> Optional[str]:
        """D-760 rev 3 9 ``line_follow.regulation_wait`` and the share above: the regulation standing
        the robot. Precedence authority > signal > crosswalk_held > crosswalk_wait > crosswalk_look (the
        crosswalk three exclude each other: held only while crossing). None = none. Locked."""
        auth = self._authority_on() and self._authority_state(now)
        if auth and auth[0] != "FREE":
            return "authority"
        if self._signal_holding():
            return "signal"
        xw = self._xwalk.status(now) or {}
        if xw.get("state") in (LOOKING, WAITING):
            return "crosswalk_wait" if xw["state"] == WAITING else "crosswalk_look"
        return "crosswalk_held" if xw.get("look_progress") is not None else None

    @property
    def supports_lane_crosswalk_gate(self) -> bool:  # D-763 10 (c): line_follow.crosswalk_gate_enabled
        return self._config.crosswalk_gate_enabled

    def _crosswalk_armed(self) -> bool:
        return self._config.crosswalk_gate_enabled and self._xwalk.zone is not None

    def _crosswalk_report(self) -> Optional[str]:
        """D-573 4 detail when the gate asks for a human, else None."""
        return self._xwalk.report if self._config.crosswalk_gate_enabled else None
