"""One robot body for every near/stop check (D-424, builds on D-422).

CORE line follow (D-422), the sensing gate and the PC calibration tools judge "too near" from
the same body: the URDF outline (front x, rear x, half width, in-place rotation radius) and the
sensor poses, in base_footprint (x forward, y left, metres). Order of authority, as everywhere
(D-397): URDF nominal (the robot package's profile config/geometry.yaml) < accepted calibration
record (D-47 addendum store; today only the LiDAR mount yaw) < operator overlay.

Rules every consumer shares:
- gap: the body travels `stop_gap_m(v) = margin + v*latency + v^2/(2*decel)` before it must stop;
  resume needs `+ hysteresis` (D-422).
- every sensor reading becomes base_footprint points. A return inside the body outline is the
  robot itself. A finite return nearer than the scan's range_min still counts as an obstacle
  (fail-safe: a near return can only shorten a gap).
- a beam without a return (inf, NaN, 0) is UNKNOWN out to range_min, never "inf = free" and
  never "blocked everywhere": it blocks only translation into the band it covers (unless a
  fresh ultrasonic echo covers it) and never rotation.
- in-place rotation needs every seen point outside rotation_radius + pad; never below the URDF
  rotation radius.

Stdlib only (shared by CORE, the sensing nodes and the PC tools; D-155 allows sensing to import
this module like the calibration store).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Iterator, Mapping, Optional, Sequence

Point = tuple[float, float]
#: (from_deg, to_deg, max_range_m) in the robot frame (0 = forward, + = left), D-422 format.
SelfMask = tuple[tuple[float, float, float], ...]

#: Pinky Pro URDF nominal: the subset of geometry.yaml (D-397) the body needs. Drift-tested
#: against the generated file in tools/calibration/test/test_urdf_nominal.py.
PINKY_PRO_GEOMETRY: dict[str, dict[str, float]] = {
    "lidar": {"x_m": -0.017, "y_m": 0.0, "forward_deg": 180.0},
    "ultrasonic": {"x_m": 0.0267},
    "caster": {"rear_x_m": -0.076},
    "footprint": {"front_x_m": 0.04205, "half_width_m": 0.05655, "rotation_radius_m": 0.08257},
}

# Gap policy (not geometry): the D-422 line_follow.obstacle_* defaults, one source for all.
MARGIN_M = 0.02          # URDF/calibration error and floor slip
LATENCY_S = 0.15         # scan age + tick + command to wheels
DECEL_MPS2 = 0.5         # conservative Pinky braking until measured
HYSTERESIS_M = 0.03      # resume beyond stop + this
#: Lateral pad of the swept strip and of the rotation circle in the sensing gate (D-424).
SWEEP_PAD_M = 0.010
#: Forward ultrasonic cone half angle: the D-422 line_follow.obstacle_ultrasonic_half_angle_deg.
ULTRASONIC_HALF_ANGLE_DEG = 15.0
#: D-424 review M1: a turn needs at least one seen return in each of these equal sectors around
#: the base. A sector with none is a gap wider than 360/8 = 45 deg the LiDAR did not see into
#: (blocked, absorbing or too near) -- not evidence of free space. 45 deg is the order of the
#: front-sector widths the bumpers have always used (D-344 +-20, the gate's +-45 deg).
ROTATION_SECTORS = 8


def stop_gap_m(speed: float, *, margin_m: float = MARGIN_M, latency_s: float = LATENCY_S,
               decel_mps2: float = DECEL_MPS2) -> float:
    """D-422 body gap that stops in time from `speed`: margin + reaction + braking."""
    speed = abs(float(speed))
    return margin_m + speed * latency_s + speed * speed / (2.0 * decel_mps2)


def inside_body(x: float, y: float, front_x: float, rear_x: float, half_width: float,
                radius: float) -> bool:
    """D-422 body outline: the URDF rectangle cut by the rotation circle (rounded corners)."""
    return rear_x <= x <= front_x and abs(y) <= half_width and x * x + y * y <= radius * radius


def masked(angle: float, distance: float, mask: SelfMask) -> bool:
    """A configured self-mask window (robot-frame angle in rad) hides this return."""
    deg = math.degrees(angle)
    return any(lo <= deg <= hi and distance <= reach for lo, hi, reach in mask)


@dataclass(frozen=True)
class ScanView:
    """One scan in base_footprint: seen obstacle points and the ends of the unknown beams
    (a beam without a return may hide an object anywhere out to range_min)."""
    points: tuple[Point, ...]
    unknown: tuple[Point, ...]
    range_min: float


@dataclass(frozen=True)
class RobotBody:
    front_x_m: float
    rear_x_m: float
    half_width_m: float
    rotation_radius_m: float
    lidar_x_m: float
    lidar_y_m: float = 0.0
    lidar_forward_deg: float = 0.0
    ultrasonic_x_m: Optional[float] = None
    margin_m: float = MARGIN_M
    latency_s: float = LATENCY_S
    decel_mps2: float = DECEL_MPS2
    hysteresis_m: float = HYSTERESIS_M
    sweep_pad_m: float = SWEEP_PAD_M
    source: str = "geometry.yaml"

    def __post_init__(self) -> None:
        values = (self.front_x_m, self.rear_x_m, self.half_width_m, self.rotation_radius_m,
                  self.lidar_x_m, self.lidar_y_m, self.lidar_forward_deg, self.margin_m,
                  self.latency_s, self.decel_mps2, self.hysteresis_m, self.sweep_pad_m)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in values):
            raise ValueError("robot body values must be finite numbers")
        if not self.rear_x_m < 0.0 < self.front_x_m or self.half_width_m <= 0.0:
            raise ValueError("robot body needs rear < 0 < front and a positive half width")
        if self.rotation_radius_m < max(self.front_x_m, -self.rear_x_m, self.half_width_m) - 1e-9:
            raise ValueError("rotation_radius_m cannot be smaller than the body extent")
        if not self.rear_x_m < self.lidar_x_m < self.front_x_m:
            raise ValueError("the LiDAR must sit over the body")
        if self.decel_mps2 <= 0.0 or min(self.margin_m, self.latency_s, self.hysteresis_m,
                                         self.sweep_pad_m) < 0.0:
            raise ValueError("gap policy terms must be non-negative (decel positive)")

    # --- gap rule ------------------------------------------------------------------------

    def stop_gap_m(self, speed: float) -> float:
        return stop_gap_m(speed, margin_m=self.margin_m, latency_s=self.latency_s,
                          decel_mps2=self.decel_mps2)

    def resume_gap_m(self, speed: float) -> float:
        return self.stop_gap_m(speed) + self.hysteresis_m

    @property
    def lidar_to_front_m(self) -> float:
        return self.front_x_m - self.lidar_x_m

    @property
    def lidar_to_rear_m(self) -> float:
        return self.lidar_x_m - self.rear_x_m

    def lidar_stop_m(self, speed: float, *, reverse: bool = False) -> float:
        """The stop gap as a range straight ahead (or behind) from the LiDAR origin."""
        offset = self.lidar_to_rear_m if reverse else self.lidar_to_front_m
        return offset + self.stop_gap_m(speed)

    def lidar_clear_m(self, speed: float, *, reverse: bool = False) -> float:
        return self.lidar_stop_m(speed, reverse=reverse) + self.hysteresis_m

    def rotation_clear_m(self, margin_m: Optional[float] = None) -> float:
        """Base-frame distance every seen point must exceed for an in-place turn."""
        return self.rotation_radius_m + (self.sweep_pad_m if margin_m is None else float(margin_m))

    def box_bounds(self) -> tuple[float, float, float]:
        """(rear extent, front extent, half width) for footprint_guard.translation_clearance."""
        return -self.rear_x_m, self.front_x_m, self.half_width_m

    # --- sensors to base_footprint -------------------------------------------------------

    def contains(self, x: float, y: float) -> bool:
        return inside_body(x, y, self.front_x_m, self.rear_x_m, self.half_width_m,
                           self.rotation_radius_m)

    def lidar_point(self, angle: float, distance: float) -> Point:
        """A LiDAR return at robot-frame angle (rad, 0 = forward) as a base_footprint point."""
        return (self.lidar_x_m + distance * math.cos(angle),
                self.lidar_y_m + distance * math.sin(angle))

    def scan_view(self, sample: Mapping[str, Any], *, forward_deg: Optional[float] = None,
                  self_mask: SelfMask = (), max_range: float = math.inf) -> ScanView:
        """A scan (`ranges`, `angle_min`, `angle_max` or `angle_increment`, `range_min`,
        `range_max`) as base_footprint points plus the unknown band ends.

        forward_deg: scan angle of the robot's forward (default: this body's LiDAR mount).
        Returns inside the body outline or a self-mask window are the robot itself."""
        ranges = list(sample.get("ranges") or [])
        count = len(ranges)
        low = _number(sample.get("range_min"), 0.0)
        high = _number(sample.get("range_max"), math.inf)
        if count < 2:
            return ScanView((), (), low)
        angle_min = float(sample["angle_min"])
        if sample.get("angle_max") is not None:
            step = (float(sample["angle_max"]) - angle_min) / (count - 1)
        else:
            step = float(sample["angle_increment"])
        forward = math.radians(self.lidar_forward_deg if forward_deg is None else float(forward_deg))
        points, unknown = [], []
        for index, value in enumerate(ranges):
            angle = angle_min + index * step - forward
            angle = math.atan2(math.sin(angle), math.cos(angle))
            distance = _number(value, math.nan)
            if not math.isfinite(distance) or distance <= 0.0:
                if low > 0.0:
                    unknown.append(self.lidar_point(angle, low))
                continue
            if distance > min(high, max_range):
                continue
            if self_mask and masked(angle, distance, self_mask):
                continue
            point = self.lidar_point(angle, distance)
            if not self.contains(*point):
                points.append(point)
        return ScanView(tuple(points), tuple(unknown), low)

    def ultrasonic_points(self, range_m: float, *, half_angle_deg: float,
                          step_deg: float = 2.5) -> tuple[Point, ...]:
        """A forward echo at range_m as points across its cone (fail-safe: every point counts)."""
        if self.ultrasonic_x_m is None:
            return ()
        count = max(1, int(math.ceil(2.0 * half_angle_deg / step_deg)))
        out = []
        for index in range(count + 1):
            angle = math.radians(-half_angle_deg + 2.0 * half_angle_deg * index / count)
            out.append((self.ultrasonic_x_m + range_m * math.cos(angle), range_m * math.sin(angle)))
        return tuple(out)

    # --- judgements ----------------------------------------------------------------------

    def translation_gap(self, points: Sequence[Point], *, reverse: bool = False,
                        pad_m: Optional[float] = None) -> Optional[float]:
        """Straight travel before the body (half width + pad) touches a point; 0 = a point is
        already beside or inside the padded strip, None = nothing in the strip that way.
        Points outside the strip never count."""
        pad = self.sweep_pad_m if pad_m is None else float(pad_m)
        width = self.half_width_m + pad
        best: Optional[float] = None
        for x, y in points:
            if abs(y) > width:
                continue
            gap = (self.rear_x_m - x) if reverse else (x - self.front_x_m)
            if gap <= 0.0:
                if (self.rear_x_m <= x <= self.front_x_m):
                    return 0.0
                continue          # behind the direction of travel
            if best is None or gap < best:
                best = gap
        return best

    def ultrasonic_clears(self, point: Point, echo_m: Optional[float],
                          half_angle_deg: float = ULTRASONIC_HALF_ANGLE_DEG) -> bool:
        """D-424 review M6: a forward ultrasonic proves `point` free only with a finite echo
        farther than the point, and only inside its cone. No echo (an HC-SR04 timeout) proves
        nothing -- an angled or soft surface returns nothing too -- so it never clears."""
        if self.ultrasonic_x_m is None or echo_m is None or not math.isfinite(echo_m):
            return False
        dx, dy = point[0] - self.ultrasonic_x_m, point[1]
        if dx <= 0.0:
            return False
        return (math.degrees(math.atan2(abs(dy), dx)) <= half_angle_deg
                and math.hypot(dx, dy) < float(echo_m))

    def _front_band_cleared(self, end: Point, echo_m: Optional[float]) -> bool:
        """The unknown band of one beam past the body front is cleared by the ultrasonic only
        when both its end and where it leaves the body front lie in the cone, nearer than the echo."""
        if echo_m is None:
            return False
        dx = end[0] - self.lidar_x_m
        if dx <= 0.0:
            return False
        t = (self.front_x_m - self.lidar_x_m) / dx
        exit_point = (self.front_x_m, self.lidar_y_m + t * (end[1] - self.lidar_y_m))
        return self.ultrasonic_clears(end, echo_m) and self.ultrasonic_clears(exit_point, echo_m)

    def unknown_blocks(self, view: ScanView, *, reverse: bool = False,
                       pad_m: Optional[float] = None, ultrasonic_m: Optional[float] = None) -> bool:
        """An unknown beam reaches past the body edge inside the strip of this direction: the
        robot cannot know the first metres of that way are free. Forward, a fresh finite
        ultrasonic echo clears the part of the band inside its cone (M6)."""
        pad = self.sweep_pad_m if pad_m is None else float(pad_m)
        width = self.half_width_m + pad
        for end in view.unknown:
            x, y = end
            if abs(y) > width:
                # The beam may still cross the strip nearer the LiDAR: check its crossing.
                x, y = self._strip_crossing(x, y, width)
                if x is None:
                    continue
            if (x < self.rear_x_m) if reverse else (x > self.front_x_m):
                if not reverse and self._front_band_cleared((x, y), ultrasonic_m) \
                        and self._front_band_cleared(end, ultrasonic_m):
                    continue
                return True
        return False

    def _strip_crossing(self, x: float, y: float, width: float) -> tuple[Optional[float], float]:
        """Where the ray from the LiDAR to (x, y) leaves |y| <= width (None = never inside)."""
        dy = y - self.lidar_y_m
        if abs(self.lidar_y_m) > width or abs(dy) < 1e-12:
            return None, y
        edge = math.copysign(width, dy)
        t = (edge - self.lidar_y_m) / dy
        return self.lidar_x_m + t * (x - self.lidar_x_m), edge

    def rotation_gap(self, points: Sequence[Point]) -> Optional[float]:
        """Smallest distance of a seen point outside the rotation radius (negative = inside)."""
        best: Optional[float] = None
        for x, y in points:
            gap = math.hypot(x, y) - self.rotation_radius_m
            if best is None or gap < best:
                best = gap
        return best

    def can_rotate(self, points: Sequence[Point], margin_m: Optional[float] = None) -> bool:
        """Every seen point clears rotation_radius + margin; no point at all is not clear."""
        need = self.rotation_clear_m(margin_m)
        return bool(points) and all(math.hypot(x, y) > need for x, y in points)

    def seen_sectors(self, points: Sequence[Point]) -> int:
        """How many of ROTATION_SECTORS equal sectors around the base hold a seen point."""
        return len({int((math.atan2(y, x) + math.pi) / (2.0 * math.pi) * ROTATION_SECTORS)
                    % ROTATION_SECTORS for x, y in points})

    def rotation_reason(self, view: ScanView, margin_m: Optional[float] = None, *,
                        ultrasonic_m: Optional[float] = None) -> Optional[str]:
        """Why an in-place turn is not clear (None = clear), D-424 + review M1/M2:
        - every sector around the base needs a seen return (coverage), else unknown;
        - every seen point must clear rotation_radius + margin;
        - a beam without a return whose unknown band leaves the body crosses the swept annulus:
          behind the body (no rear sensor) it is never clear; in front only a fresh finite
          ultrasonic echo inside its cone clears it."""
        if not view.points:
            return "no LiDAR return to judge the turn"
        seen = self.seen_sectors(view.points)
        if seen < ROTATION_SECTORS:
            return f"the scan sees only {seen} of {ROTATION_SECTORS} sectors around the base"
        need = self.rotation_clear_m(margin_m)
        nearest = min(math.hypot(x, y) for x, y in view.points)
        if nearest <= need:
            return (f"a return {nearest:.3f} m from the base <= {need:.3f} m "
                    "(rotation radius + margin)")
        for end in view.unknown:
            if self.contains(*end):
                continue                      # the blind zone ends inside the body
            if end[0] < 0.0:
                return "a beam without a return behind the body crosses the turn's sweep"
            if not self.ultrasonic_clears(end, ultrasonic_m):
                return "a beam without a return in front crosses the turn's sweep"
        return None

    def with_lidar(self, *, x_m: Optional[float] = None, y_m: Optional[float] = None,
                   forward_deg: Optional[float] = None) -> "RobotBody":
        return replace(self, lidar_x_m=self.lidar_x_m if x_m is None else float(x_m),
                       lidar_y_m=self.lidar_y_m if y_m is None else float(y_m),
                       lidar_forward_deg=(self.lidar_forward_deg if forward_deg is None
                                          else float(forward_deg)))


def _number(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if not math.isnan(out) or math.isnan(default) else default


#: geometry.yaml keys a body reads, and the overlay keys that replace them (operator wins).
OVERLAY_KEYS = ("front_x_m", "rear_x_m", "half_width_m", "rotation_radius_m", "lidar_x_m",
                "lidar_y_m", "lidar_forward_deg", "ultrasonic_x_m")


def from_geometry(geometry: Mapping[str, Any], *, source: str = "geometry.yaml",
                  overlay: Optional[Mapping[str, Any]] = None, **policy: float) -> RobotBody:
    """A body from a geometry.yaml mapping (D-397 layout); `overlay` keys (OVERLAY_KEYS, an
    operator's explicit values) win; `policy` sets margin_m/latency_s/decel_mps2/... ."""
    footprint, lidar = geometry["footprint"], geometry["lidar"]
    ultrasonic = geometry.get("ultrasonic") or {}
    values = {
        "front_x_m": float(footprint["front_x_m"]),
        "rear_x_m": float(geometry["caster"]["rear_x_m"]),
        "half_width_m": float(footprint["half_width_m"]),
        "rotation_radius_m": float(footprint["rotation_radius_m"]),
        "lidar_x_m": float(lidar["x_m"]),
        "lidar_y_m": float(lidar.get("y_m", 0.0)),
        "lidar_forward_deg": float(lidar.get("forward_deg", 0.0)),
        "ultrasonic_x_m": None if ultrasonic.get("x_m") is None else float(ultrasonic["x_m"]),
    }
    chosen = {k: v for k, v in (overlay or {}).items() if k in OVERLAY_KEYS and v is not None}
    if chosen:
        values.update({k: float(v) for k, v in chosen.items()})
        source += f"; operator overlay {', '.join(sorted(chosen))}"
    return RobotBody(**values, **policy, source=source)


def load_geometry(path) -> dict:
    """Read a geometry.yaml (PyYAML is imported here only: the module stays stdlib)."""
    import yaml  # noqa: PLC0415
    with open(path, encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def resolve_body(geometry: Optional[Mapping[str, Any]] = None, *, source: str = "geometry.yaml",
                 robot: Optional[str] = None, root=None, overlay: Optional[Mapping[str, Any]] = None,
                 **policy: float) -> RobotBody:
    """URDF nominal < accepted lidar_mount record (mount yaw) < operator overlay."""
    from core_common.calibration_store import resolve  # noqa: PLC0415 - keeps import light
    geometry = PINKY_PRO_GEOMETRY if geometry is None else geometry
    nominal = float(geometry["lidar"].get("forward_deg", 0.0))
    values, why = resolve("lidar_mount", {"lidar_yaw_offset": math.radians(nominal)},
                          fallback_source=source, robot=robot, root=root,
                          nominal={"lidar_forward_deg": nominal})
    lidar = dict(geometry["lidar"], forward_deg=math.degrees(float(values["lidar_yaw_offset"])))
    return from_geometry({**geometry, "lidar": lidar}, source=why, overlay=overlay, **policy)


PINKY_PRO = from_geometry(PINKY_PRO_GEOMETRY)
