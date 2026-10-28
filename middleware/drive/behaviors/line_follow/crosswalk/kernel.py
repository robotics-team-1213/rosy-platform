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

Crossing needs crosswalk_clear_s of consecutive empty scans (at least crosswalk_look_min_scans)
while standing still; any non-empty scan restarts it (D-573 rev 3). There is no timeout: after crosswalk_report_s without that proof the gate
asks for a human (D-407 cause ``crosswalk_blocked``) and keeps standing. A zone armed once and then
lost (odom epoch or frame change) stops for good until the session resets (D-573 3.4).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Optional

from core_features.line_follow.crosswalk.zone import (CORRIDOR_HALF_M, EVIDENCE_TTL_S, IR_CATCH_HALF_M, MAX_LATERAL_M,
                                                      MAX_TURN_RAD, _angle)

NONE, ARMED, APPROACHING, LOOKING, WAITING, CROSSING = (
    "none", "armed", "approaching", "looking", "waiting", "crossing")
HOLD_POSE_M = .01  #: a held corridor stands only this close to its image pose (inside the 3 sigma edge band)
CLIP_SLICE_M = .05  #: D-573 rev 8: along-road slice of a map-wall clip (extra floor <= tan(skew) x this)
#: D-573 4 detail reasons of the stuck cause ``crosswalk_blocked``.
#: D-573 rev 7: a later sighting this much better aligned with the robot's heading re-anchors the zone
REANCHOR_RAD = math.radians(3.0)
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


def judge_cells(scan: Scan, boxes, origin, heading, *, blind_proven: bool = False, band: float = 0.0, hits=None):
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
            if hits is not None and not hits:   # diagnostics: the first return that held
                hits.append((origin[0] + dx * distance, origin[1] + dy * distance))
            continue
        px, py = origin[0] + dx * distance, origin[1] + dy * distance
        depth = 0.0
        for b, edge in zip(boxes, sides):
            if b[0] <= px <= b[1] and b[2] <= py <= b[3]:
                d = [px - b[0], b[1] - px, py - b[2], b[3] - py]
                depth = max(depth, min([v for v, e in zip(d, edge) if e] or [math.inf]))
        if depth > band:
            occupied = True
            if hits is not None and not hits:
                hits.append((px, py))
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
        self._first_yaw: Optional[float] = None
        self._walls = None
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
        self._lane_yaw: Optional[float] = None  # 개정 5 8항: the lane yaw a corridor last gave this zone
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

    def _boxes(self, z: Zone, geo: Geometry, front: float, side: float = 0.0, heading: float = 0.0):
        """side: the body's lateral offset in the anchor frame now (the same odom as the scan);
        heading: the body's yaw off the anchor axis."""
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
        # 개정 5: the zone's own lane width; the pads a seen corridor merges into z's edges are
        # position bounds the body centring already covers (m15: 0.046 m of them reached the wall).
        # The boxes are axis-aligned: a body heading off the axis sweeps sideways by its slope over
        # what is left of A (review 2026-10-14).
        sweep = abs(math.sin(heading)) * max(0.0, far + geo.exit_m + m - front)
        half = max(((geo.lane_half_m if self._zone.left is None else self._zone.left)
                    - (-geo.lane_half_m if self._zone.right is None else self._zone.right)) / 2,
                   geo.body_half_m) + sweep
        exit_box = (far, far + geo.exit_m + m, side - geo.body_half_m - sweep, side + geo.body_half_m + sweep)
        return (((front, far, side - half, side + half), exit_box) if front < far else (exit_box,))

    # ---- tick ------------------------------------------------------------------------------
    def step(self, now: float, *, zones, pose, key, still: bool, scan: Optional[Scan],
             geo: Optional[Geometry], cruise: float, look_s: float, min_scans: int,
             report_s: float, stale_s: float, odom_error_fraction: float = 0.0,
             range_sigma_m: float = 0.0, persist_k: int = 1, persist_n: int = 1,
             corridor=None, walls=None) -> tuple[Optional[float], Optional[str]]:
        """corridor: the freshest lane edges (image pose, left, right, uncertainty_m) or None. walls (rev 8):
        (lane yaw, left, right, ahead) clip lines across the lane from the body now (None: no wall that side) and
        how far along the lane from the body they hold."""
        self._walls = walls
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
            self._merge(zones, geo.lane_half_m, None if pose is None else pose.yaw, odom_error_fraction)
        # Odom drift since the image pose widens every edge (D-491 margin rule).
        drift = odom_error_fraction * math.hypot(pose.x - self._zone.x, pose.y - self._zone.y)
        z = replace(self._zone, margin=self._zone.margin + drift, lateral=self._zone.lateral + drift)
        # The lane edges the camera sees now cap the zone's own edges plus drift since its
        # image (SIM 2026-10-10: 0.05 x 0.6 m of assumed drift put the track wall in A).
        # 개정 5: A is judged along the lane as that image saw it, not along the zone's older
        # anchor: the heading difference between the two used to widen A by its slope over A's
        # length (0.02-0.03 m on a lane whose walls stand 0.038 m outside its edges). Only while
        # that turn moves A's ends along the road by less than the zone's own margin; a larger
        # one keeps the zone's frame and the slope pad. The zone's own edges keep the slope.
        # 개정 5 8항: a tick without a corridor keeps the lane yaw the last one applied to this zone, not
        # the zone's body yaw (m34/m35: 0.106 rad off the lane swept A onto the wall mid-crossing).
        lane_yaw = corridor[0].yaw if corridor is not None else self._lane_yaw
        if lane_yaw is not None:
            skew, own = _angle(lane_yaw - z.yaw), z.lateral
            turn = abs(math.sin(skew)) * (z.far + z.margin + geo.exit_m)
            shift = z.far * (1 - math.cos(skew)) + geo.lane_half_m * abs(math.sin(skew))
            if shift <= z.margin:    # the turn's along-road shift of A's ends is added, not spent
                z, own, turn = replace(z, yaw=lane_yaw, margin=z.margin + shift), own + turn, 0.0
                self._lane_yaw = lane_yaw
            if corridor is None:
                z = replace(z, lateral=own)     # the zone's own edges keep the turn pad
        if corridor is not None:
            cpose, cleft, cright, unc, *reach = corridor
            cleft, cright = lane_edges(cleft, cright, geo.lane_half_m, geo.body_half_m)
            ahead, offset = self._local(z, cpose, 0.0)
            if reach:   # past the range the edges were seen over, the lane may run on at their slope
                turn += reach[0] * max(0.0, z.far + z.margin + geo.exit_m - ahead - reach[1])
            pad = unc + odom_error_fraction * math.hypot(pose.x - cpose.x, pose.y - cpose.y) + turn
            # Both are bounds of the same lane: keep the tighter side of each (the body floor in
            # _boxes still covers the swept path). A misread edge on the stripes cannot widen A.
            left = offset + cleft + pad if z.left is None else min(z.left + own, offset + cleft + pad)
            right = offset + cright - pad if z.right is None else max(z.right - own, offset + cright - pad)
            z = replace(z, left=left, right=right, lateral=0.0)
        if self._state in (ARMED, APPROACHING):
            if not self._on_course(z, pose, geo, self._first_yaw if self._first_yaw is not None else self._zone.yaw):
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
        self._first_yaw = self._zone.yaw   # rev 7: 'turned away' stays judged on the first sighting (rev 5 3)
        return True

    def _on_course(self, z: Zone, pose, geo: Geometry, yaw=None) -> bool:
        """The body is in the zone's lane corridor and heads along it. MAX_TURN_RAD is D-491's
        "a crosswalk is crossed straight; more is another road" bound (review M2: a zone left
        behind at a junction kept the gate armed for the next crosswalk)."""
        side = self._local(z, pose, 0.0)[1]
        left = (geo.lane_half_m if z.left is None else z.left) + z.lateral
        right = (-geo.lane_half_m if z.right is None else z.right) - z.lateral
        # yaw: the anchor as imaged; z may be turned to the lane seen now (개정 5)
        return abs(_angle(pose.yaw - (z.yaw if yaw is None else yaw))) <= MAX_TURN_RAD and right <= side <= left

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
        boxes, hits = self._clip(self._boxes(z, geo, front, self._local(z, pose, 0.0)[1], heading), z, geo, pose), []
        verdict, cells = judge_cells(scan, boxes, self._local(z, pose, geo.lidar_x),
                                     heading, blind_proven=self._state == CROSSING, band=band, hits=hits)
        # diagnostics (the gate glue logs them when the reason changes): A and the return that held, anchor frame
        self.last_look = tuple(round(f(b[i] for b in boxes), 3) for i, f in enumerate((min, max, min, max)))
        self.last_hit = tuple(round(v, 3) for v in hits[0]) if hits else None
        # D-573 rev 2: a return within 3 sigma of A's edge is a person once the same cell is hit in
        # >= k of the last n scans; range noise from a surface just outside A scatters over cells.
        self._edge_hist = (self._edge_hist + [cells])[-n:]
        if verdict is None and any(sum(c in h for h in self._edge_hist) >= k for c in cells):
            return PERSON
        return verdict

    def _clip(self, boxes, z: Zone, geo: Geometry, pose):
        """D-573 rev 8: A ends at Fleet's map wall clip lines beside the lane (gate: inside each wall face by
        the band), never inside the body's own lane-parallel path (half width + margin), and only as far
        along as those walls run: past that a box is judged unclipped. The lines run along the lane, turned off
        the zone axis: each box is cut into CLIP_SLICE_M slices, each clipped at the line's outermost over it
        (v2 lap r48a stood 5 deg off the lane; one sweep over all of A gave the 2 cm clip back)."""
        if self._walls is None:
            return boxes
        lane_yaw, left, right, cover = self._walls
        skew = _angle(lane_yaw - z.yaw)
        along, side = self._local(z, pose, 0.0)
        end = along + cover * math.cos(skew)
        if math.cos(skew) < .5 or end <= along:
            return boxes     # the lane far off the zone axis (MAX_TURN_RAD is well inside), or no wall left ahead
        slope, out = math.tan(skew), []
        # an offset across the lane is offset / cos(skew) across the zone axis (farther out, never nearer)
        left, right = (None if v is None else v / math.cos(skew) for v in (left, right))
        # The body crosses along the lane (it keeps the lane): its own path is the lane-parallel band of body half
        # width + margin through it, turned like the clip lines; the crossing boxes carry their heading sweep
        # themselves. A heading sweep over all of A here put the floor on the wall (v2 lap r50a, -0.11 m).
        for x0, x1, y0, y1 in boxes:
            cut = x0
            while cut < min(x1, end) - 1e-9:
                nxt = min(cut + CLIP_SLICE_M, x1, end)
                ends = [slope * (x - along) for x in (cut, nxt)]
                hi = y1 if left is None else min(y1, side + max(left, geo.body_half_m) + max(ends))
                lo = y0 if right is None else max(y0, side + min(right, -geo.body_half_m) + min(ends))
                out.append((cut, nxt, lo, hi))
                cut = nxt
            if x1 > end:
                out.append((max(x0, end), x1, y0, y1))
        return tuple(out)

    @staticmethod
    def _ends_in(z, other):
        """other's near/far ends ((along, across), (along, across)) in z's anchor frame."""
        cz, sz, c, s = math.cos(z.yaw), math.sin(z.yaw), math.cos(other.yaw), math.sin(other.yaw)
        ends = []
        for d in (other.near, other.far):
            px, py = other.x + c * d - z.x, other.y + s * d - z.y
            ends.append((cz * px + sz * py, -sz * px + cz * py))
        return ends

    def _merge(self, zones, lateral_m: float, heading: float | None = None, drift_fraction: float = 0.0) -> None:
        """D-573 1: sightings of the same crosswalk widen the armed one (near: nearer, far: farther),
        only before the stop; once looking, A is frozen. Rev 7: a later sighting better aligned with the
        robot's heading (by REANCHOR_RAD) becomes the anchor, the older one merged into it: a zone first
        seen mid-turn kept that skew and a slope pad of +-0.2 m put the wall in A (v2 lap r43, east)."""
        for other in zones:
            z = self._zone
            if other.key != z.key or other == z:
                continue
            (n, ny), (f, fy) = self._ends_in(z, other)
            overlap = n <= z.far + z.margin + other.margin and f >= z.near - z.margin - other.margin
            if not (overlap and max(abs(ny), abs(fy)) <= lateral_m + z.lateral + other.lateral):
                continue
            if heading is not None and (abs(_angle(other.yaw - heading)) + REANCHOR_RAD
                                        < abs(_angle(z.yaw - heading))):
                (zn, zny), (zf, zfy) = self._ends_in(other, z)
                shift = (zny + zfy) / 2   # the old anchor's lateral offset in the new frame
                # review: drift since the old anchor is carried, and without seen edges the old axis stays inside A
                carry = drift_fraction * math.hypot(other.x - z.x, other.y - z.y)
                unseen = None in (z.left, other.left) or None in (z.right, other.right)
                # the old body line's offset (anchor point, not its skewed ends: that skew is what is dropped)
                across = -math.sin(other.yaw) * (z.x - other.x) + math.cos(other.yaw) * (z.y - other.y)
                self._zone = replace(
                    other, near=min(other.near, zn), far=max(other.far, zf),
                    margin=max(z.margin, other.margin) + carry,
                    left=None if None in (z.left, other.left) else max(other.left, z.left + shift),
                    right=None if None in (z.right, other.right) else min(other.right, z.right + shift),
                    lateral=max(z.lateral, other.lateral) + carry + (abs(across) if unseen else 0.0))
                continue
            shift = (ny + fy) / 2   # the other sighting's lateral offset in this anchor frame
            self._zone = replace(
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
        if self._window is None and now - self._blocked_since >= report_s - 1e-9:   # not while clearing
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




def lane_edges(left, right, half: float = CORRIDOR_HALF_M, body_half: float = 0.0, inner=IR_CATCH_HALF_M-.045):
    """Raw seen lane edges, no wider than a lane (D-573 개정 4: wall bases 0.120/0.122 m either side
    were read as the edges and held 'person' for good). A wider pair gives way to the lane's own inner
    half-width (the 0.079 m IR_CATCH_HALF_M is built on) about their middle, at most half - body_half
    from the anchor (the body that took the image stands in that lane); the pads go on outside."""
    if left is not None and right is not None and left - right > 2 * half:
        reach = max(half - body_half, 0.0)
        middle = min(max((left + right) / 2, -reach), reach)
        return middle + inner, middle - inner
    return left, right


def zone_of(z: dict, range_error_fraction: float, along_default=None, body_half_m: float = 0.0) -> Zone:
    """A D-491 zone record with a resolved anchor as a Zone. Along the road the frame's crosswalk
    bound (D-573 6 개정), else along_default, else the lane's lateral bound (D-491 as before)."""
    a = z["anchor"]
    along = z.get("along")
    along = along if along is not None else along_default if along_default is not None else z["uncertainty"]
    left, right = lane_edges(z.get("left"), z.get("right"), body_half=body_half_m)
    return Zone(key=(z["epoch"], a.frame), x=a.x, y=a.y, yaw=a.yaw, near=z["near"], far=z["far"],
                margin=along + range_error_fraction * z["far"], left=left, right=right, lateral=z["uncertainty"])


