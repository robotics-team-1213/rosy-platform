"""D-573 2/3/4/6: stop before a known crosswalk, look with the LiDAR, cross only on proof.

Pure and ROS-free. The manager feeds one ``step`` per CAMERA_LINE tick and applies the returned
linear cap with ``min`` after every other gate; the gate never lifts a zero (D-573 6).

Look area A, in the frame of the zone's odom anchor (x along the road at the image pose, y left):
the crosswalk part of this robot's lane corridor between the near and far edge, widened by the
waiting strips (crosswalk_approach_default_m each side), and the exit strip beyond the far edge
(the corridor, one body length + g(v_cross) long). The corridor is the inner paint edges the
camera saw with the zone (D-468 boundaries), never narrower than the body half width + margin;
without a seen edge it is the D-491 corridor half width. Lateral pad = the evidence's lateral bound
(uncertainty_m) + odom drift; the range error pads only the near/far edges. A scan is
*empty* only when no return lies in A and every ray that crosses A reaches past it with a finite
return (no return, a return in front of A or a part of A inside range_min is UNKNOWN). The camera
paint is never an occupancy source: only LiDAR rays judge A.

Crossing needs crosswalk_look_s of consecutive empty scans (at least crosswalk_look_min_scans)
while standing still. There is no timeout: after crosswalk_report_s without that proof the gate
asks for a human (D-407 cause ``crosswalk_blocked``) and keeps standing. A zone armed once and then
lost (odom epoch or frame change) stops for good until the session resets (D-573 3.4).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional

from core_features.line_follow.crosswalk_zone import CORRIDOR_HALF_M, EVIDENCE_TTL_S, MAX_TURN_RAD, _angle

NONE, ARMED, APPROACHING, LOOKING, WAITING, CROSSING = (
    "none", "armed", "approaching", "looking", "waiting", "crossing")
#: D-573 4 detail reasons of the stuck cause ``crosswalk_blocked``.
PERSON, UNKNOWN, STALE, LOST = "person_present", "look_unknown", "sensor_stale", "zone_lost"


@dataclass(frozen=True)
class Zone:
    """A camera crosswalk (D-491) at its image pose in odom: near/far metres ahead of base_footprint."""
    key: tuple
    x: float
    y: float
    yaw: float
    near: float
    far: float
    margin: float = 0.0          # along the road: range error + uncertainty (+ odom drift per tick)
    left: Optional[float] = None   # corridor edges (y, + left); None = not seen
    right: Optional[float] = None
    lateral: float = 0.0         # across the road: uncertainty (+ odom drift per tick)


@dataclass(frozen=True)
class Scan:
    """One LiDAR scan as rays (base-frame angle, range or None = no return) from the LiDAR origin."""
    rays: tuple
    range_min: Optional[float]
    at: float


@dataclass(frozen=True)
class Geometry:
    """URDF body and the derived D-573 2 distances (all from RobotBody / config, no hand numbers)."""
    front_x: float
    rear_x: float
    lidar_x: float
    v_cross: float
    s_wait: float          # body front to the near edge: max(g(v_cross), range_min - (front - lidar) + margin)
    slow_from: float       # g(v_cruise) + s_wait: slow down to v_cross from here
    lane_half_m: float     # corridor half width when an edge was not seen (D-491)
    body_half_m: float     # body half width + margin: the corridor is never narrower
    strip_m: float         # waiting strip beside the corridor (camera-only zone default)
    exit_m: float          # body length + g(v_cross)
    end_margin: float


def scan_rays(sample, *, forward_deg: float) -> tuple:
    """A LaserScan mapping as (robot-frame angle, range | None). Non-finite, <= 0 or above
    range_max is no return. Self returns stay returns: they shadow what is behind them."""
    ranges = list(sample.get("ranges") or [])
    if len(ranges) < 2:
        return ()
    angle_min = float(sample["angle_min"])
    if sample.get("angle_increment") is not None:
        step = float(sample["angle_increment"])
    else:
        step = (float(sample["angle_max"]) - angle_min) / (len(ranges) - 1)
    high = sample.get("range_max")
    high = math.inf if high is None else float(high)
    forward = math.radians(forward_deg)
    rays = []
    for index, raw in enumerate(ranges):
        angle = angle_min + index * step - forward
        angle = math.atan2(math.sin(angle), math.cos(angle))
        try:
            distance = float(raw)
        except (TypeError, ValueError):
            distance = math.nan
        ok = not isinstance(raw, bool) and math.isfinite(distance) and 0.0 < distance <= high
        rays.append((angle, distance if ok else None))
    return tuple(rays)


def _slab(ox, oy, dx, dy, box):
    """Ray o + t*d (t >= 0) against an axis box (x0, x1, y0, y1): (t_in, t_out) or None."""
    t0, t1 = 0.0, math.inf
    for o, d, lo, hi in ((ox, dx, box[0], box[1]), (oy, dy, box[2], box[3])):
        if abs(d) < 1e-12:
            if not lo <= o <= hi:
                return None
            continue
        a, b = (lo - o) / d, (hi - o) / d
        t0, t1 = max(t0, min(a, b)), min(t1, max(a, b))
        if t0 > t1:
            return None
    return t0, t1


def judge(scan: Scan, boxes, origin, heading, *, blind_proven: bool = False) -> Optional[str]:
    """None when A (boxes in the anchor frame) is proven empty, else PERSON or UNKNOWN."""
    return judge_cells(scan, boxes, origin, heading, blind_proven=blind_proven)[0]


def _edge_sides(boxes):
    """Per box, which of its sides (x0, x1, y0, y1) are outer edges of the union (not a seam)."""
    out = []
    for i, b in enumerate(boxes):
        others = [o for j, o in enumerate(boxes) if j != i]
        out.append((not any(abs(o[1] - b[0]) < 1e-9 for o in others),
                    not any(abs(o[0] - b[1]) < 1e-9 for o in others), True, True))
    return out


def judge_cells(scan: Scan, boxes, origin, heading, *, blind_proven: bool = False, band: float = 0.0):
    """(verdict, edge cells). A return deeper than ``band`` inside A is a person at once; one within
    ``band`` of A's outer edge only names its cell (size ``band``) for the caller's persistence count
    (D-573 rev 2). origin/heading: the LiDAR origin and base heading in the anchor frame.
    blind_proven: crossing, the part of A now inside range_min was proven empty before the move
    and is the D-422 body stop's (with its remembered near returns); only the rest is judged."""
    occupied = unknown = False
    cells = set()
    crossed = [False] * len(boxes)     # review M1: a box no ray crosses is not seen at all
    sides = _edge_sides(boxes) if band > 0.0 else None
    for angle, distance in scan.rays:
        direction = heading + angle
        dx, dy = math.cos(direction), math.sin(direction)
        spans = [_slab(origin[0], origin[1], dx, dy, b) for b in boxes]
        crossed = [c or s is not None for c, s in zip(crossed, spans)]
        spans = [s for s in spans if s is not None]
        if not spans:
            continue
        enter = min(s[0] for s in spans)
        if blind_proven and scan.range_min is not None:
            spans = [(max(t0, scan.range_min), t1) for t0, t1 in spans if t1 > scan.range_min]
            if not spans:
                continue
            enter = min(s[0] for s in spans)
        if scan.range_min is None or enter < scan.range_min or distance is None or distance < enter:
            unknown = True        # blind, no return, or shadowed in front of A
            continue
        if not any(t0 <= distance <= t1 for t0, t1 in spans):
            continue
        if band <= 0.0:
            occupied = True
            continue
        px, py = origin[0] + dx * distance, origin[1] + dy * distance
        depth = 0.0
        for b, edge in zip(boxes, sides):
            if b[0] <= px <= b[1] and b[2] <= py <= b[3]:
                d = [px - b[0], b[1] - px, py - b[2], b[3] - py]
                depth = max(depth, min([v for v, e in zip(d, edge) if e] or [math.inf]))
        if depth > band:
            occupied = True
        else:
            cells.add((math.floor(px / band), math.floor(py / band)))
    return (PERSON if occupied else UNKNOWN if unknown or not all(crossed) else None), cells


class CrosswalkGate:
    """One armed zone at a time. ``step`` returns (linear cap or None, hold reason or None)."""

    def __init__(self) -> None:
        self._count = 0
        self._look_s = 1.0
        self._persist = (0.0, 1, 1)
        self.reset()

    def reset(self) -> None:
        self._zone: Optional[Zone] = None
        self._id: Optional[str] = None
        self._state = NONE
        self._reason: Optional[str] = None      # why the last judged scan was not empty
        self._last_bad: Optional[str] = None
        self._window: Optional[float] = None    # first empty scan of the current window
        self._span = 0.0
        self._scans = 0
        self._scan_at: Optional[float] = None
        self._blocked_since: Optional[float] = None
        self._held = False                       # crossing, stopped by a return ahead
        self._edge_hist: list = []               # edge-band cells of the last persist_n scans
        self.report: Optional[str] = None       # D-407 detail once blocked >= report_s

    @property
    def zone(self) -> Optional[Zone]:
        return self._zone

    # ---- geometry --------------------------------------------------------------------------
    @staticmethod
    def _local(zone: Zone, pose, x_body: float) -> tuple[float, float]:
        """The base_footprint point (x_body, 0) of pose in the zone's anchor frame."""
        px, py = pose.x + math.cos(pose.yaw) * x_body, pose.y + math.sin(pose.yaw) * x_body
        c, s = math.cos(zone.yaw), math.sin(zone.yaw)
        return c * (px - zone.x) + s * (py - zone.y), -s * (px - zone.x) + c * (py - zone.y)

    def _boxes(self, z: Zone, geo: Geometry, front: float, side: float = 0.0):
        """side: the body's lateral offset in the anchor frame now (the same odom as the scan)."""
        near, far, m = z.near - z.margin, z.far + z.margin, z.margin
        left = max(geo.lane_half_m if z.left is None else z.left, geo.body_half_m) + z.lateral
        right = min(-geo.lane_half_m if z.right is None else z.right, -geo.body_half_m) - z.lateral
        if self._state != CROSSING or front < near:
            return ((near, far, right - geo.strip_m, left + geo.strip_m), (far, far + geo.exit_m + m, right, left))
        # The body front is in the zone: only the zone still ahead of it and the exit count; a
        # return in a waiting strip alone does not stop the crossing (D-573 2 "건너기"). The exit
        # strip is then where the body will stand: the body's own path (half width + margin) from
        # where it is now, judged in the scan's own odom frame, so no drift pad (SIM 2026-10-10:
        # the corridor plus drift reached the track wall beside the exit).
        # The rest of the zone ahead: the seen lane width centred on the body, which follows that
        # lane, again in the scan's own odom frame (the drift since the zone's image only moves the
        # zone's lane edges relative to the anchor, not the lane relative to the body).
        half = max(((geo.lane_half_m if z.left is None else z.left)
                    - (-geo.lane_half_m if z.right is None else z.right)) / 2, geo.body_half_m)
        exit_box = (far, far + geo.exit_m + m, side - geo.body_half_m, side + geo.body_half_m)
        return (((front, far, side - half, side + half), exit_box) if front < far else (exit_box,))

    # ---- tick ------------------------------------------------------------------------------
    def step(self, now: float, *, zones, pose, key, still: bool, scan: Optional[Scan],
             geo: Optional[Geometry], cruise: float, look_s: float, min_scans: int,
             report_s: float, stale_s: float, odom_error_fraction: float = 0.0,
             range_sigma_m: float = 0.0, persist_k: int = 1, persist_n: int = 1,
             corridor=None) -> tuple[Optional[float], Optional[str]]:
        """corridor: the freshest lane edges (image pose, left, right, uncertainty_m) or None."""
        self._look_s = look_s
        self._persist = (3.0 * range_sigma_m, persist_k, persist_n)
        if self._reason == LOST:
            return 0.0, "crosswalk_zone_lost"
        if self._zone is None and not self._arm(zones, pose, key, geo):
            return None, None
        if key is not None and key != self._zone.key:
            self._reason = self._last_bad = self.report = LOST
            self._state = WAITING
            if self._blocked_since is None:
                self._blocked_since = now
            return 0.0, "crosswalk_zone_lost"
        if pose is None or geo is None:
            if self._state in (ARMED, APPROACHING):
                return 0.0, "crosswalk_sensor_stale"   # cannot place the zone: stand, stay armed
            return self._block(now, STALE, report_s)
        speed = min(geo.v_cross, cruise)
        if self._state in (ARMED, APPROACHING):
            self._merge(zones, geo.lane_half_m)
        # Odom drift since the image pose widens every edge (D-491 margin rule).
        drift = odom_error_fraction * math.hypot(pose.x - self._zone.x, pose.y - self._zone.y)
        z = replace(self._zone, margin=self._zone.margin + drift, lateral=self._zone.lateral + drift)
        if corridor is not None:
            # The lane edges the camera sees now cap the zone's own edges plus drift since its
            # image (SIM 2026-10-10: 0.05 x 0.6 m of assumed drift put the track wall in A). Pad:
            # the evidence's lateral bound, drift since that image, and the edges' slope over A
            # from the heading difference between that image and the zone anchor.
            cpose, cleft, cright, unc = corridor
            offset = self._local(z, cpose, 0.0)[1]
            turn = abs(math.sin(cpose.yaw - z.yaw)) * (z.far + z.margin + geo.exit_m)
            pad = unc + odom_error_fraction * math.hypot(pose.x - cpose.x, pose.y - cpose.y) + turn
            # Both are bounds of the same lane: keep the tighter side of each (the body floor in
            # _boxes still covers the swept path). A misread edge on the stripes cannot widen A.
            left = offset + cleft + pad if z.left is None else min(z.left + z.lateral, offset + cleft + pad)
            right = offset + cright - pad if z.right is None else max(z.right - z.lateral, offset + cright - pad)
            z = replace(z, left=left, right=right, lateral=0.0)
        if self._state in (ARMED, APPROACHING):
            if not self._on_course(z, pose, geo):
                self.reset()      # turned away (review M2): the next tick arms the zone ahead, if any
                return None, None
            gap = z.near - z.margin - self._local(z, pose, geo.front_x)[0]
            if gap > geo.slow_from:
                self._state = ARMED
                return None, None
            if gap > geo.s_wait:
                self._state = APPROACHING
                return speed, None
            self._state, self._blocked_since = LOOKING, now
            self._restart()
        if self._state == CROSSING and self._local(z, pose, geo.rear_x)[0] > z.far + z.margin + geo.end_margin:
            self.reset()
            return None, None
        verdict = self._judge_new(now, scan, stale_s, geo, pose, z)
        if self._state == CROSSING and not self._held:
            if verdict in (None, "same"):
                return speed, None
            self._held = True
            return self._block(now, verdict, report_s)
        if not still:
            self._restart()      # D-573 2: the look window opens only once odom shows a stop
            return self._block(now, None, report_s)
        if verdict not in (None, "same"):
            return self._block(now, verdict, report_s)
        if verdict is None:
            self._reason = None
            if self._window is None:
                self._window, self._scans = scan.at, 0
            self._scans += 1
            self._span = scan.at - self._window
        if self._window is not None and self._span >= look_s - 1e-9 and self._scans >= min_scans:
            self._state, self._held, self._reason, self._last_bad = CROSSING, False, None, None
            self._blocked_since, self.report = None, None
            self._restart()
            return speed, None
        return self._block(now, None, report_s)

    def _arm(self, zones, pose, key, geo) -> bool:
        """Arm the nearest zone of this odom run whose near edge is still ahead of the body front."""
        if pose is None or geo is None:
            return False
        ahead = [z for z in zones if z.key == key and self._on_course(z, pose, geo)
                 and self._local(z, pose, geo.front_x)[0] <= z.near - z.margin]
        if not ahead:
            return False
        self._count += 1
        self._zone = min(ahead, key=lambda z: z.near - z.margin - self._local(z, pose, geo.front_x)[0])
        self._id, self._state = f"camera-{self._count}", ARMED
        return True

    def _on_course(self, z: Zone, pose, geo: Geometry) -> bool:
        """The body is in the zone's lane corridor and heads along it. MAX_TURN_RAD is D-491's
        "a crosswalk is crossed straight; more is another road" bound (review M2: a zone left
        behind at a junction kept the gate armed for the next crosswalk)."""
        side = self._local(z, pose, 0.0)[1]
        left = (geo.lane_half_m if z.left is None else z.left) + z.lateral
        right = (-geo.lane_half_m if z.right is None else z.right) - z.lateral
        return abs(_angle(pose.yaw - z.yaw)) <= MAX_TURN_RAD and right <= side <= left

    def _judge_new(self, now, scan, stale_s, geo, pose, z):
        """None = a new empty scan, "same" = no new scan since the last (still fresh), else why not."""
        if scan is None or not 0.0 <= now - scan.at <= stale_s:
            return STALE
        if self._scan_at is not None and scan.at <= self._scan_at:
            return "same"
        self._scan_at = scan.at
        heading = math.atan2(math.sin(pose.yaw - z.yaw), math.cos(pose.yaw - z.yaw))
        front = self._local(z, pose, geo.front_x)[0]
        band, k, n = self._persist
        verdict, cells = judge_cells(scan, self._boxes(z, geo, front, self._local(z, pose, 0.0)[1]),
                                     self._local(z, pose, geo.lidar_x),
                                     heading, blind_proven=self._state == CROSSING, band=band)
        # D-573 rev 2: a return within 3 sigma of A's edge is a person once the same cell is hit in
        # >= k of the last n scans; range noise from a surface just outside A scatters over cells.
        self._edge_hist = (self._edge_hist + [cells])[-n:]
        if verdict is None and any(sum(c in h for h in self._edge_hist) >= k for c in cells):
            return PERSON
        return verdict

    def _merge(self, zones, lateral_m: float) -> None:
        """D-573 1: sightings of the same crosswalk widen the armed one (near: nearer, far: farther),
        only before the stop; once looking, A is frozen."""
        z = self._zone
        cz, sz = math.cos(z.yaw), math.sin(z.yaw)
        for other in zones:
            if other.key != z.key or other == z:
                continue
            c, s = math.cos(other.yaw), math.sin(other.yaw)
            ends = []
            for d in (other.near, other.far):
                px, py = other.x + c * d - z.x, other.y + s * d - z.y
                ends.append((cz * px + sz * py, -sz * px + cz * py))
            (n, ny), (f, fy) = ends
            overlap = n <= z.far + z.margin + other.margin and f >= z.near - z.margin - other.margin
            if overlap and max(abs(ny), abs(fy)) <= lateral_m + z.lateral + other.lateral:
                shift = (ny + fy) / 2   # the other sighting's lateral offset in this anchor frame
                self._zone = z = replace(
                    z, near=min(z.near, n), far=max(z.far, f), margin=max(z.margin, other.margin),
                    left=None if None in (z.left, other.left) else max(z.left, other.left + shift),
                    right=None if None in (z.right, other.right) else min(z.right, other.right + shift),
                    lateral=max(z.lateral, other.lateral))

    def _restart(self) -> None:
        self._window, self._scans, self._span = None, 0, 0.0

    def _block(self, now, reason, report_s):
        """Zero; a reason restarts the window. Ask a human once blocked report_s (no timeout)."""
        if reason is not None:
            self._reason = self._last_bad = reason
            self._restart()
        if self._state != CROSSING:
            self._state = WAITING if self._reason is not None else LOOKING
        if self._blocked_since is None:
            self._blocked_since = now
        if now - self._blocked_since >= report_s - 1e-9:
            self.report = self._last_bad or UNKNOWN
        return 0.0, "crosswalk_" + (self._reason or "looking")

    def status(self, now: float) -> Optional[dict]:
        """D-573 6 ``line_follow.crosswalk``; None outside an armed zone."""
        if self._zone is None:
            return None
        looking = self._state in (LOOKING, WAITING) or self._held
        return dict(state=self._state, zone_id=self._id, source="camera", reason=self._reason,
                    waiting_s=None if self._blocked_since is None
                    else round(max(0.0, now - self._blocked_since), 2),
                    look_progress=round(min(1.0, self._span / self._look_s), 2) if looking else None)




class CrosswalkGateMixin:
    """LineFollowManager glue (manager lock throughout). Default off (crosswalk_gate_enabled)."""

    def _init_crosswalk_gate(self) -> None:
        self._xwalk = CrosswalkGate()
        self._xwalk_scan: Optional[Scan] = None

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
            a = z["anchor"]
            if a is not None:
                out.append(Zone(key=(z["epoch"], a.frame), x=a.x, y=a.y, yaw=a.yaw, near=z["near"],
                                far=z["far"], margin=z["uncertainty"] + c.crosswalk_range_error_fraction * z["far"],
                                left=z.get("left"), right=z.get("right"), lateral=z["uncertainty"]))
        return out

    def _fresh_corridor(self, now: float):
        """The latest accepted D-468 lane evidence with both inner edges and a bounded lateral error,
        as (image pose, left, right, uncertainty_m) over its observed x range; None if older than the
        D-491 evidence TTL or incomplete."""
        ev = self._return_evidence
        lane, at = ev._lane, ev._received_at
        if lane is None or at is None or lane.uncertainty_m is None or not 0.0 <= now - at <= EVIDENCE_TTL_S:
            return None
        edges = {b.side: [b.slope * x + b.intercept_m for x in (b.observed_x_min_m, b.observed_x_max_m)]
                 for b in lane.boundaries}
        image = ev._image_pose(round(lane.stamp * 1e9))
        if image is None or set(edges) != {"left", "right"}:
            return None
        return image, max(edges["left"]), min(edges["right"]), lane.uncertainty_m

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
            cruise=c.cruise_speed, look_s=c.crosswalk_look_s, min_scans=c.crosswalk_look_min_scans,
            report_s=c.crosswalk_report_s, stale_s=c.clearance_stale_s,
            odom_error_fraction=c.crosswalk_odom_error_fraction, range_sigma_m=c.crosswalk_range_sigma_m,
            persist_k=c.crosswalk_persist_k, persist_n=c.crosswalk_persist_n,
            corridor=self._fresh_corridor(now))
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

    def _crosswalk_armed(self) -> bool:
        return self._config.crosswalk_gate_enabled and self._xwalk.zone is not None

    def _crosswalk_report(self) -> Optional[str]:
        """D-573 4 detail when the gate asks for a human, else None."""
        return self._xwalk.report if self._config.crosswalk_gate_enabled else None
