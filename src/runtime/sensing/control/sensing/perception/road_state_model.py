"""Subject: road-state inputs and parameters (D-384). ROS-free, numpy only.

Measurement records, the estimator parameters with the ADR numbers, and the
adapters that turn a LaneKeeper bundle, a learned-shadow payload or a LaserScan
into measurements. The estimator itself is road_state.py."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

TRACK, COAST, SLOW, STOP = "TRACK", "COAST", "SLOW", "STOP"
SCHEMA = "rosy.perception.road_state/1"
TOPIC = "perception/road_state"
#: LaneKeeper evaluates boundary offsets here (lane_keep.SIDE_X_M).
SIDE_X_M = 0.22
#: Keeper candidate rejection reasons that mean "this is a wall".
WALL_REASONS = frozenset({"wall", "blob", "wall_base"})
RIGHT, LEFT, NOISE = "R", "L", "N"


@dataclass(frozen=True)
class BoundaryMeas:
    """A camera boundary line: lateral offset y and heading psi (rad) at x ahead."""
    y: float
    psi: float
    x: float = SIDE_X_M
    side_hint: str | None = None
    source: str = "rule"
    rejected: str | None = None
    #: x where the whole-line heading is predicted: the chord midpoint of the seen
    #: paint (a straight fit through an arc runs along the tangent there).
    x_psi: float | None = None


@dataclass(frozen=True)
class OffsetMeas:
    """A direct lane-offset measurement d (learned shadow) taken at `stamp`."""
    d: float
    sigma: float
    stamp: float | None = None
    wall_fraction: float = 0.0
    confidence: float = 1.0
    source: str = "learned"


@dataclass(frozen=True)
class IrMeas:
    """A line under the IR bar at lateral offset y (x ~ 0)."""
    y: float
    source: str = "ir"


@dataclass(frozen=True)
class WallSeg:
    """A wall segment on the floor (base_link), from the LiDAR."""
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class RoadStateParams:
    lane_width_m: float = 0.185
    near_x_m: float = 0.33
    ir_x_m: float = 0.0
    # process noise (D-384: measured odometry error)
    q_d_per_m: float = 0.08
    q_phi_per_rad: float = 0.03
    q_phi_per_m: float = 0.02
    q_kappa_per_m: float = 2.0
    q_w_per_m: float = 0.002
    q_d_floor: float = 0.002                 # m / sqrt(s)
    q_phi_floor: float = math.radians(0.5)   # rad / sqrt(s)
    q_kappa_floor: float = 0.05              # 1/m / sqrt(s)
    q_w_floor: float = 0.0002                # m / sqrt(s)
    kappa_pull_m: float = 0.3
    # measurement noise
    sigma_y_m: float = 0.015
    sigma_psi_rad: float = math.radians(4.0)
    sigma_ir_m: float = 0.005
    learned_sigma_m: float = 0.03
    learned_min_confidence: float = 0.2
    learned_max_wall_fraction: float = 0.3
    # gates
    nis_2d: float = 9.21
    nis_1d: float = 6.63
    jump_m: float = 0.04
    pair_width_tol_m: float = 0.04
    pair_parallel_rad: float = math.radians(12.0)
    lidar_wall_veto: bool = False
    # D-384 review: "shadow" is R0/R1 only. The side+learned re-acquisition
    # path exists only there, and only while IR is uncalibrated.
    mode: str = "shadow"
    ir_calibrated: bool = False
    # IR spacing is not measured yet: until it is, IR evidence is OFF.
    ir_geometry_measured: bool = False
    learned_reacq_min_confidence: float = 0.5
    learned_reacq_sigmas: float = 2.0
    wall_distance_m: float = 0.05
    wall_angle_rad: float = math.radians(10.0)
    # association
    max_candidates: int = 4
    max_hypotheses: int = 3
    winner_margin: float = 2.0
    noise_logl: float = -3.0
    # degradation ladder
    track_frames: int = 2
    odom_scale: float = 1.08
    coast_s_m: float = 0.10
    coast_sigma_d_m: float = 0.03
    slow_s_m: float = 0.25
    slow_sigma_d_m: float = 0.05
    slow_sigma_phi_rad: float = math.radians(10.0)
    lost_after_s: float = 3.0                # CORE line_follow LOST latch
    lost_margin_s: float = 0.5
    wall_only_frames: int = 3
    slow_gate: float = 1.5
    # re-acquisition
    reacq_gate: float = 2.0
    reacq_frames: int = 3
    reacq_min_travel_m: float = 0.01
    reacq_timeout_s: float = 2.0
    # CORE-facing suggestion (SLOW = lane_bev.MEMORY_CONFIDENCE)
    track_confidence: float = 0.9
    coast_confidence: float = 0.8
    slow_confidence: float = 0.6
    # priors
    sigma_d0_m: float = 0.10
    sigma_phi0_rad: float = math.radians(20.0)
    # phi and kappa share one heading measurement (psi = -phi + kappa x_psi): this
    # prior decides the split, so a yawed robot on a straight lane reads as phi.
    sigma_kappa0: float = 0.5
    sigma_w0_m: float = 0.005
    calib_ratio_tol: float = 0.10
    calib_suspect_s: float = 2.0
    odom_history_s: float = 2.0




def _wrap_line(angle: float) -> float:
    """An undirected line angle difference into (-pi/2, pi/2]."""
    a = (angle + math.pi / 2) % math.pi - math.pi / 2
    return a if a != -math.pi / 2 else math.pi / 2


def offset_from_shadow(payload: dict, *, half_width_m: float, params: RoadStateParams | None = None):
    """An OffsetMeas from a perception/learned/shadow payload, or None when not visible.

    The learned error follows the lane contract (> 0: lane right of centre, so
    the robot is left of it): d = error * half width."""
    p = params or RoadStateParams()
    if not isinstance(payload, dict) or not payload.get("visible"):
        return None
    error, stamp = payload.get("error"), payload.get("stamp")
    if not isinstance(error, (int, float)) or isinstance(error, bool) or not math.isfinite(error):
        return None
    confidence = payload.get("confidence") or 0.0
    fractions = payload.get("class_fractions") or {}
    wall = payload.get("wall_fraction", fractions.get("wall", 0.0)) or 0.0
    return OffsetMeas(d=float(error) * half_width_m,
                      sigma=p.learned_sigma_m / max(float(confidence), p.learned_min_confidence),
                      stamp=float(stamp) if isinstance(stamp, (int, float)) else None,
                      wall_fraction=float(wall), confidence=float(confidence))


def boundaries_from_keep(last: dict, *, near_x_m: float = 0.33) -> list[BoundaryMeas]:
    """BoundaryMeas from a LaneKeeper.last bundle (line/keep_debug).

    Uses last['candidates'] (with a rejection reason each) when the keeper
    provides it, else last['boundaries']. A line whose nearest seen end lies
    beyond the near field gets that end as its x, so the estimator drops it."""
    records = last.get("candidates")
    if records is None:
        records = last.get("boundaries") or []
    out = []
    for r in records:
        try:
            y = float(r["y_at_side_x_m"])
            psi = _wrap_line(math.radians(float(r["heading_deg"])))
        except (KeyError, TypeError, ValueError):
            continue
        ends = r.get("ends_m") or []
        nearest = min((float(e[0]) for e in ends), default=SIDE_X_M)
        mid = sum(float(e[0]) for e in ends) / len(ends) if ends else None
        x = SIDE_X_M if nearest <= near_x_m else nearest
        flag = r.get("rejected")
        # LaneKeeper candidates (feat/lane-keep-candidates, 7218c6b5): rejected is
        # a bool; reason None (accepted), "transverse" (no side fields: skipped
        # above, a decision-point cue) or "extrapolation". Junction, flipping and
        # no_boundary stay frame-level in last['reason'].
        reason = (str(r.get("reason") or "keeper") if flag is True
                  else flag if isinstance(flag, str) and flag else None)
        out.append(BoundaryMeas(y=y, psi=psi, x=x, side_hint=r.get("side"),
                                rejected=reason, x_psi=mid))
    return out


def decision_point_from_keep(last: dict) -> bool:
    """A declared decision point: a line across the path, a latched corner or a
    junction hold in the keeper bundle. Only there may a route hint break a tie."""
    strategy = str(last.get("strategy") or "")
    reason = str(last.get("reason") or "")
    return bool(last.get("transverse")) or strategy.startswith("corner") or reason.startswith("junction")


def wall_segments_from_scan(ranges, angle_min: float, angle_increment: float, *,
                            yaw_offset_rad: float = math.pi, x_offset_m: float = 0.0,
                            max_range_m: float = 0.6, max_gap_m: float = 0.05,
                            chunk: int = 4) -> list[WallSeg]:
    """Floor wall segments (base_link) from a LaserScan's ranges: runs of
    consecutive returns ahead of the robot, cut into `chunk`-point pieces."""
    r = np.asarray(ranges, dtype=float)
    yaw = angle_min + angle_increment * np.arange(r.size) - yaw_offset_rad
    ok = np.isfinite(r) & (r > 0.0) & (r <= max_range_m)
    xs = r * np.cos(yaw) + x_offset_m
    ys = r * np.sin(yaw)
    ok &= xs > 0.0
    segs, run = [], []

    def flush():
        for i in range(0, len(run) - 1, chunk - 1):
            a, b = run[i], run[min(i + chunk - 1, len(run) - 1)]
            segs.append(WallSeg(float(xs[a]), float(ys[a]), float(xs[b]), float(ys[b])))

    for i in range(r.size):
        if not ok[i]:
            flush()
            run = []
            continue
        if run and math.hypot(xs[i] - xs[run[-1]], ys[i] - ys[run[-1]]) > max_gap_m:
            flush()
            run = []
        run.append(i)
    flush()
    return segs


def _near_wall(b: BoundaryMeas, walls, p: RoadStateParams) -> bool:
    point = np.array([b.x, b.y])
    for w in walls:
        a, c = np.array([w.x0, w.y0]), np.array([w.x1, w.y1])
        seg = c - a
        length2 = float(seg @ seg)
        if length2 <= 0.0:
            continue
        t = min(1.0, max(0.0, float((point - a) @ seg) / length2))
        if float(np.linalg.norm(point - (a + t * seg))) > p.wall_distance_m:
            continue
        if abs(_wrap_line(math.atan2(seg[1], seg[0]) - b.psi)) <= p.wall_angle_rad:
            return True
    return False


def _compatible(a: str, b: str) -> bool:
    """Two labellings describe the same lane: no candidate gets two different
    sides, and no side goes to two different candidates."""
    for i, (x, y) in enumerate(zip(a, b)):
        if NOISE not in (x, y) and x != y:
            return False
    for side in (RIGHT, LEFT):
        if side in a and side in b and a.index(side) != b.index(side):
            return False
    return True


def _route_key(h, cands, hint: str):
    """Sort key: smaller wins. right: has an R, rightmost R; left: has an L,
    leftmost L; straight: best score."""
    if hint == "left":
        return (not h.has(LEFT), -h.y_of(LEFT, cands) if h.has(LEFT) else 0.0, -h.score, h.labels)
    if hint == "straight":
        return (-h.score, h.labels)
    return (not h.has(RIGHT), h.y_of(RIGHT, cands) if h.has(RIGHT) else 0.0, -h.score, h.labels)


def _r(value, digits: int = 6):
    value = float(value)
    return round(value, digits) if math.isfinite(value) else None
