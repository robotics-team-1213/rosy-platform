"""Subject: road-state estimator (D-384 decisions 1-3). ROS-free, numpy only.

Keeps the expected road when the tape drops out, and says how far it can be
trusted. Shadow evidence only: nothing here commands motion (D-369); the
snapshot carries a CORE-facing *suggestion* (visible, confidence) and no
command field.

State x = [d, phi, kappa, w] with covariance P (base_link, y LEFT positive):
  d      lateral offset of the robot from its lane centre (left +)
  phi    heading error of the robot against the lane (CCW +)
  kappa  road curvature (left bend +)
  w      apparent lane width; a tight prior at the map width (sigma 0.005 m).
         The ground is assumed calibrated (a profile id comes with the
         measurements); w does not absorb pitch bias. |w/w_map - 1| > 10 %
         for 2 s raises `calibration_suspect`.

Prediction per odometry step (ds = v dt, dtheta = omega dt):
  d <- d + ds sin(phi);  phi <- phi + dtheta - kappa ds
  kappa pulled toward the map curvature when one is set, else a random walk.
  Q_d = (0.08 ds)^2 + (0.002 m)^2 dt,
  Q_phi = (0.03 |dtheta|)^2 + (0.02 ds)^2 + floor^2 dt  (the floors keep a held
  robot's filter from collapsing at ds = 0).

Measurements (near field only, x <= 0.33 m):
  boundary  y = +-w/2 - d - x phi + kappa x^2 / 2 (L +, R -), psi = -phi + kappa x
            from LaneKeeper.last; which side it is, is decided here by the
            gates and the association, not by the keeper's side label.
  learned   1-D d, sigma = 0.03 / max(confidence, 0.2); skipped when the
            wall fraction exceeds 0.3; shifted by the odometry since its stamp.
  IR        1-D boundary at x ~ 0 (sigma 0.005 m), gated as R or L.
  LiDAR     a veto, not a measurement, and OFF by default (lidar_wall_veto)
            until the LiDAR yaw calibration lands. Wall rejection otherwise
            comes from image evidence only: the learned wall fraction and the
            keeper's own candidate rejection reasons.

Gates, in order: wall, NIS (chi2 99 %: 9.21 for 2-D, 6.63 for 1-D), lateral
jump |dy| > 0.04 m (only on an established track: a fresh acquisition has no
track to jump from), pair width |y_L - y_R - w| < 0.04 m and |psi_L - psi_R| <
12 deg. SLOW widens every gate 1.5x, re-acquisition 2x (NIS thresholds by the
square).

Association: every near-field candidate is labelled R, L or noise; at most one
R and one L. Score = sum of Gaussian log-likelihoods + a noise penalty per
noise label. The top 3 hypotheses are kept. The best wins when it leads every
*conflicting* hypothesis (one that labels some candidate differently) by
more than 2. Otherwise it is a tie:
  - an explicit route hint (Fleet) picks the leftmost / rightmost lane, or the
    best score for "straight";
  - on a fresh acquisition (no established track) the rightmost lane wins
    (Korean right-hand traffic: keep a lone line on the right). If IR sees a
    line, the choice must agree with it or the frame HOLDs (STOP, reason
    `ambiguous`);
  - an established track is never switched by a tie: the frame's boundaries
    are not used (reject reason `ambiguous`) and the ladder degrades.

Degradation ladder (s_lost = odometry distance since the last accepted
measurement x 1.08; t_lost = time since then; CORE latches LOST after
lost_after_s = 3.0 s, so COAST and SLOW end at 2.5 s whatever the distance):
  TRACK  a measurement accepted within the last 2 frames
  COAST  1.08 s_lost < 0.10 m, sigma_d < 0.03 m, t_lost <= 2.5 s
  SLOW   1.08 s_lost < 0.25 m, sigma_d < 0.05 m, sigma_phi < 10 deg, t_lost <= 2.5 s
  STOP   otherwise, or 3 wall-only frames in a row, or an ambiguous acquisition.
STOP is left only by re-acquisition: 3 consecutive consistent frames (a pair,
or one side plus IR on the same side) spanning >= 0.01 m of travel. No
candidate for 2 s while stopped is reported (`reacquire.timed_out`).
"""

from __future__ import annotations

import bisect
import itertools
import math
from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class OffsetMeas:
    """A direct lane-offset measurement d (learned shadow) taken at `stamp`."""
    d: float
    sigma: float
    stamp: float | None = None
    wall_fraction: float = 0.0
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
    sigma_kappa0: float = 2.0
    sigma_w0_m: float = 0.005
    calib_ratio_tol: float = 0.10
    calib_suspect_s: float = 2.0
    odom_history_s: float = 2.0


@dataclass
class _Eval:
    label: str
    z: np.ndarray
    h: np.ndarray
    H: np.ndarray
    R: np.ndarray
    nu: np.ndarray
    nis: float
    logl: float
    reason: str | None


@dataclass
class _Hyp:
    labels: str
    score: float
    evals: list = field(default_factory=list)

    def has(self, label):
        return label in self.labels

    def y_of(self, label, cands):
        return cands[self.labels.index(label)].y


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
                      wall_fraction=float(wall))


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
        x = SIDE_X_M if nearest <= near_x_m else nearest
        reason = r.get("rejected") or r.get("reason")
        out.append(BoundaryMeas(y=y, psi=psi, x=x, side_hint=r.get("side"),
                                rejected=str(reason) if reason else None))
    return out


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


class RoadStateEstimator:
    """EKF over [d, phi, kappa, w] with gated multi-hypothesis association."""

    def __init__(self, params: RoadStateParams | None = None, *, route_hint: str | None = None):
        if route_hint not in (None, "left", "straight", "right"):
            raise ValueError("route_hint must be None, 'left', 'straight' or 'right'")
        self.p = p = params or RoadStateParams()
        self.route_hint = route_hint
        self.w_map = p.lane_width_m
        self.x = np.array([0.0, 0.0, 0.0, p.lane_width_m])
        self._P0 = np.diag([p.sigma_d0_m ** 2, p.sigma_phi0_rad ** 2,
                            p.sigma_kappa0 ** 2, p.sigma_w0_m ** 2])
        self.P = self._P0.copy()
        self.map_kappa = None
        self.rejects = {k: 0 for k in ("wall", "nis", "jump", "width", "stale", "ambiguous",
                                       "keeper", "noise")}
        self.last_frame: dict = {"candidates": [], "hypotheses": [], "hypothesis": None,
                                 "tie": False, "tie_rule": None,
                                 "accepted": {"boundaries": 0, "ir": 0, "learned": 0}}
        self.profile = None
        self._now = None
        self._s_total = 0.0          # |ds| travelled
        self._cum_s = 0.0            # signed, for latency compensation
        self._cum_th = 0.0
        self._history: list = []     # (stamp, cum_s, cum_th)
        self._s_lost = 0.0
        self._t_accept = None
        self._frames_since = 0
        self._wall_run = 0
        self._stopped = True
        self.stop_reason = "init"
        self._stop_t = None
        self._t_candidate = None
        self._consistent = 0
        self._consistent_s0 = 0.0
        self._calib_since = None
        self._calib_suspect = False
        self._level = STOP

    # ------------------------------------------------------------ public

    @property
    def level(self) -> str:
        return self._level

    def set_map_curvature(self, kappa: float | None) -> None:
        self.map_kappa = None if kappa is None else float(kappa)

    def predict(self, ds: float, dtheta: float, *, dt: float = 0.0, stamp: float | None = None) -> None:
        p = self.p
        d, phi, kappa, w = self.x
        pull = 0.0
        if self.map_kappa is not None:
            pull = min(1.0, abs(ds) / p.kappa_pull_m)
        self.x = np.array([d + ds * math.sin(phi), phi + dtheta - kappa * ds,
                           kappa + pull * ((self.map_kappa or 0.0) - kappa), w])
        F = np.array([[1.0, ds * math.cos(phi), 0.0, 0.0],
                      [0.0, 1.0, -ds, 0.0],
                      [0.0, 0.0, 1.0 - pull, 0.0],
                      [0.0, 0.0, 0.0, 1.0]])
        dt = max(0.0, float(dt))
        Q = np.diag([(p.q_d_per_m * ds) ** 2 + p.q_d_floor ** 2 * dt,
                     (p.q_phi_per_rad * dtheta) ** 2 + (p.q_phi_per_m * ds) ** 2 + p.q_phi_floor ** 2 * dt,
                     (p.q_kappa_per_m * ds) ** 2 + p.q_kappa_floor ** 2 * dt,
                     (p.q_w_per_m * ds) ** 2 + p.q_w_floor ** 2 * dt])
        self.P = F @ self.P @ F.T + Q
        self._s_lost += abs(ds)
        self._s_total += abs(ds)
        self._cum_s += ds
        self._cum_th += dtheta
        if stamp is not None:
            self._tick(float(stamp))
            self._history.append((float(stamp), self._cum_s, self._cum_th))
            while self._history and self._history[0][0] < stamp - p.odom_history_s:
                self._history.pop(0)
        self._refresh_level()

    def shifted_offset(self, meas: OffsetMeas) -> float | None:
        """meas.d moved to now by the odometry since its stamp; None when the stamp
        is older than the kept odometry history."""
        if meas.stamp is None or not self._history or meas.stamp >= self._history[-1][0]:
            return meas.d
        stamps = [h[0] for h in self._history]
        j = bisect.bisect_right(stamps, meas.stamp) - 1
        if j < 0:
            return None
        ds = self._cum_s - self._history[j][1]
        turn = (self._cum_th - self._history[j][2]) - self.x[2] * ds
        phi_then = self.x[1] - turn
        return meas.d + ds * math.sin(phi_then + turn / 2.0)

    def update(self, measurements, now: float, *, profile: str | None = None) -> str:
        p = self.p
        self._tick(float(now))
        if profile is not None:
            self.profile = profile
        fresh = self._stopped
        scale = p.reacq_gate if fresh else (p.slow_gate if self._level == SLOW else 1.0)
        bounds = [m for m in measurements if isinstance(m, BoundaryMeas)]
        offsets = [m for m in measurements if isinstance(m, OffsetMeas)]
        irs = [m for m in measurements if isinstance(m, IrMeas)]
        walls = ([m for m in measurements if isinstance(m, WallSeg)]
                 if p.lidar_wall_veto else [])
        frame = {"candidates": [], "hypotheses": [], "hypothesis": None, "tie": False,
                 "tie_rule": None, "accepted": {"boundaries": 0, "ir": 0, "learned": 0}}
        near = [b for b in bounds if b.x <= p.near_x_m]
        cands, wall_rejected = [], 0
        for b in near:
            record = self._record(b)
            if b.rejected is not None:
                reason = "wall" if b.rejected in WALL_REASONS else "keeper"
            elif walls and _near_wall(b, walls, p):
                reason = "wall"
            else:
                cands.append(b)
                continue
            self.rejects[reason] += 1
            wall_rejected += reason == "wall"
            record["gate"] = reason
            frame["candidates"].append(record)
        cands = sorted(sorted(cands, key=lambda b: abs(b.y))[:p.max_candidates], key=lambda b: b.y)
        if cands:
            self._t_candidate = self._now
        winner, hold = self._associate(cands, irs, scale, fresh, frame)
        accepted_labels = []
        if winner is not None and winner.evals:
            self._apply([e for e in winner.evals if e.label != NOISE])
            accepted_labels = [e.label for e in winner.evals if e.label != NOISE]
        frame["accepted"]["boundaries"] = len(accepted_labels)
        ir_labels = []
        if not hold:
            for m in irs:
                label = self._update_ir(m, scale)
                if label is not None:
                    ir_labels.append(label)
            for m in offsets:
                frame["accepted"]["learned"] += self._update_offset(m, scale)
        frame["accepted"]["ir"] = len(ir_labels)
        accepted = bool(accepted_labels or ir_labels or frame["accepted"]["learned"])
        if accepted:
            self._frames_since, self._s_lost, self._t_accept = 0, 0.0, self._now
        else:
            self._frames_since += 1
        wall_only = bool(near) and wall_rejected == len(near) and not accepted
        self._wall_run = self._wall_run + 1 if wall_only else 0
        self._calibration()
        if hold:
            self._enter_stop("ambiguous")
            self._consistent = 0
        elif self._stopped:
            consistent = (set(accepted_labels) == {RIGHT, LEFT}
                          or (len(accepted_labels) == 1 and accepted_labels[0] in ir_labels))
            if consistent:
                if self._consistent == 0:
                    self._consistent_s0 = self._s_total
                self._consistent += 1
                if (self._consistent >= p.reacq_frames
                        and self._s_total - self._consistent_s0 >= p.reacq_min_travel_m):
                    self._stopped, self.stop_reason, self._consistent = False, None, 0
            else:
                self._consistent = 0
        self.last_frame = frame
        self._refresh_level()
        return self._level

    def snapshot(self) -> dict:
        p = self.p
        frame = self.last_frame
        visible, confidence = {TRACK: (True, p.track_confidence), COAST: (True, p.coast_confidence),
                               SLOW: (True, p.slow_confidence), STOP: (False, 0.0)}[self._level]
        return {
            "schema": SCHEMA,
            "stamp": self._now,
            "d": _r(self.x[0]), "phi": _r(self.x[1]), "kappa": _r(self.x[2]), "w": _r(self.x[3]),
            "p_diag": [_r(v, 9) for v in np.diag(self.P)],
            "sigma_d_m": _r(math.sqrt(self.P[0, 0])),
            "sigma_phi_deg": _r(math.degrees(math.sqrt(self.P[1, 1])), 3),
            "level": self._level,
            "stop_reason": self.stop_reason,
            "s_lost_m": _r(self._s_lost),
            "t_lost_s": None if self._t_accept is None or self._now is None
            else _r(self._now - self._t_accept, 3),
            "hypothesis": frame["hypothesis"],
            "hypotheses": frame["hypotheses"],
            "tie": frame["tie"], "tie_rule": frame["tie_rule"],
            "candidates": frame["candidates"],
            "accepted": dict(frame["accepted"]),
            "rejects": dict(self.rejects),
            "reacquire": {"consistent_frames": self._consistent,
                          "timed_out": self._reacquire_timed_out()},
            "calibration_suspect": self._calib_suspect,
            "w_ratio": _r(self.x[3] / self.w_map, 4),
            "profile": self.profile,
            "route_hint": self.route_hint,
            "map_kappa": self.map_kappa,
            "core_suggestion": {"visible": visible, "confidence": confidence},
        }

    # ------------------------------------------------------------ internals

    def _tick(self, now: float) -> None:
        self._now = now
        if self._stopped and self._stop_t is None:
            self._stop_t = now

    def _record(self, b: BoundaryMeas) -> dict:
        return {"y": _r(b.y), "psi_deg": _r(math.degrees(b.psi), 3), "x": _r(b.x),
                "side_hint": b.side_hint, "source": b.source, "rejected": b.rejected,
                "nis": None, "gate": None, "label": None}

    def _boundary_eval(self, b: BoundaryMeas, label: str, scale: float, locked: bool) -> _Eval:
        p = self.p
        d, phi, kappa, w = self.x
        s = -1.0 if label == RIGHT else 1.0
        x = b.x
        h = np.array([s * w / 2 - d - x * phi + kappa * x * x / 2, -phi + kappa * x])
        H = np.array([[-1.0, -x, x * x / 2, s / 2], [0.0, -1.0, x, 0.0]])
        R = np.diag([p.sigma_y_m ** 2, p.sigma_psi_rad ** 2])
        z = np.array([b.y, b.psi])
        nu = np.array([z[0] - h[0], _wrap_line(z[1] - h[1])])
        S = H @ self.P @ H.T + R
        nis = float(nu @ np.linalg.solve(S, nu))
        logl = -0.5 * (nis + math.log(np.linalg.det(2 * math.pi * S)))
        reason = None
        if nis > p.nis_2d * scale ** 2:
            reason = "nis"
        elif locked and abs(nu[0]) > p.jump_m * scale:
            reason = "jump"
        return _Eval(label, z, h, H, R, nu, nis, logl, reason)

    def _associate(self, cands, irs, scale, fresh, frame):
        """(winner hypothesis or None, hold) and fills frame's debug fields."""
        p = self.p
        if not cands:
            frame["hypothesis"] = {"id": "", "labels": "", "score": 0.0, "margin": None}
            return None, False
        evals = [{lab: self._boundary_eval(b, lab, scale, not fresh) for lab in (RIGHT, LEFT)}
                 for b in cands]
        records = []
        for b, ev in zip(cands, evals):
            record = self._record(b)
            record["nis"] = {lab: _r(e.nis, 3) for lab, e in ev.items()}
            record["gate"] = {lab: e.reason for lab, e in ev.items()}
            records.append(record)
        hyps, width_failed = [], False
        for labels in itertools.product((RIGHT, LEFT, NOISE), repeat=len(cands)):
            if labels.count(RIGHT) > 1 or labels.count(LEFT) > 1:
                continue
            chosen = [evals[i][lab] for i, lab in enumerate(labels) if lab != NOISE]
            if any(e.reason for e in chosen):
                continue
            if RIGHT in labels and LEFT in labels:
                r, l = cands[labels.index(RIGHT)], cands[labels.index(LEFT)]
                if (abs(l.y - r.y - self.x[3]) >= p.pair_width_tol_m * scale
                        or abs(_wrap_line(l.psi - r.psi)) >= p.pair_parallel_rad * scale):
                    width_failed = True
                    continue
            score = sum(e.logl for e in chosen) + p.noise_logl * labels.count(NOISE)
            hyps.append(_Hyp("".join(labels), score, chosen))
        hyps.sort(key=lambda h: (-h.score, h.labels))
        best = hyps[0]   # the all-noise hypothesis always exists
        top = hyps[:p.max_hypotheses]
        conflicting = [h for h in top[1:] if best.score - h.score <= p.winner_margin
                       and not _compatible(best.labels, h.labels)]
        winner, hold, rule = best, False, None
        if conflicting:
            frame["tie"] = True
            ties = [h for h in top if best.score - h.score <= p.winner_margin]
            if self.route_hint is not None:
                rule = "route"
                winner = min(ties, key=lambda h: _route_key(h, cands, self.route_hint))
            elif fresh:
                rule = "right"
                winner = min(ties, key=lambda h: _route_key(h, cands, "right"))
            else:
                rule, winner = "ambiguous", None
                self.rejects["ambiguous"] += 1
            if fresh and winner is not None and irs and not self._ir_agrees(winner, irs, scale):
                rule, winner, hold = "ambiguous", None, True
                self.rejects["ambiguous"] += 1
        if width_failed and (winner is None or not (winner.has(RIGHT) and winner.has(LEFT))):
            self.rejects["width"] += 1   # a pair was seen but none passed the width gate
        frame["tie_rule"] = rule
        frame["hypotheses"] = [{"labels": h.labels, "score": _r(h.score, 4)} for h in top]
        if winner is not None:
            for i, lab in enumerate(winner.labels):
                records[i]["label"] = lab
            margin = None if len(hyps) < 2 else _r(best.score - hyps[1].score, 4)
            frame["hypothesis"] = {"id": winner.labels, "labels": winner.labels,
                                   "score": _r(winner.score, 4), "margin": margin}
        else:
            frame["hypothesis"] = {"id": None, "labels": None, "score": None, "margin": None}
        # rejects per candidate: gate reason of its likelier side when unused
        for i, ev in enumerate(evals):
            used = winner is not None and winner.labels[i] != NOISE
            if used:
                continue
            likelier = min(ev.values(), key=lambda e: e.nis)
            if likelier.reason is not None and all(e.reason for e in ev.values()):
                self.rejects[likelier.reason] += 1
            elif winner is not None:
                self.rejects["noise"] += 1
        frame["candidates"].extend(records)
        return winner, hold

    def _ir_agrees(self, hyp, irs, scale) -> bool:
        saved = self.x.copy(), self.P.copy()
        try:
            self._apply([e for e in hyp.evals if e.label != NOISE])
            return any(self._ir_label(m, scale) is not None for m in irs)
        finally:
            self.x, self.P = saved

    def _apply(self, evals) -> None:
        if not evals:
            return
        H = np.vstack([e.H for e in evals])
        nu = np.concatenate([e.nu for e in evals])
        R = np.zeros((len(nu), len(nu)))
        for i, e in enumerate(evals):
            R[2 * i:2 * i + 2, 2 * i:2 * i + 2] = e.R
        self._kalman(H, nu, R)

    def _kalman(self, H, nu, R) -> None:
        S = H @ self.P @ H.T + R
        K = np.linalg.solve(S, H @ self.P).T
        self.x = self.x + K @ nu
        I_KH = np.eye(4) - K @ H
        self.P = I_KH @ self.P @ I_KH.T + K @ R @ K.T

    def _ir_model(self, m: IrMeas, label: str):
        d, phi, kappa, w = self.x
        x = self.p.ir_x_m
        s = -1.0 if label == RIGHT else 1.0
        h = s * w / 2 - d - x * phi + kappa * x * x / 2
        H = np.array([[-1.0, -x, x * x / 2, s / 2]])
        R = np.array([[self.p.sigma_ir_m ** 2]])
        nu = np.array([m.y - h])
        S = H @ self.P @ H.T + R
        return H, R, nu, float(nu[0] ** 2 / S[0, 0])

    def _ir_label(self, m: IrMeas, scale: float):
        best = None
        for label in (RIGHT, LEFT):
            H, R, nu, nis = self._ir_model(m, label)
            if nis <= self.p.nis_1d * scale ** 2 and (best is None or nis < best[1]):
                best = (label, nis, H, R, nu)
        return best

    def _update_ir(self, m: IrMeas, scale: float):
        best = self._ir_label(m, scale)
        if best is None:
            self.rejects["nis"] += 1
            return None
        label, _, H, R, nu = best
        self._kalman(H, nu, R)
        return label

    def _update_offset(self, m: OffsetMeas, scale: float) -> int:
        p = self.p
        if m.wall_fraction > p.learned_max_wall_fraction:
            self.rejects["wall"] += 1
            return 0
        d = self.shifted_offset(m)
        if d is None:
            self.rejects["stale"] += 1
            return 0
        H = np.array([[1.0, 0.0, 0.0, 0.0]])
        R = np.array([[m.sigma ** 2]])
        nu = np.array([d - self.x[0]])
        S = H @ self.P @ H.T + R
        if float(nu[0] ** 2 / S[0, 0]) > p.nis_1d * scale ** 2:
            self.rejects["nis"] += 1
            return 0
        self._kalman(H, nu, R)
        return 1

    def _calibration(self) -> None:
        if abs(self.x[3] / self.w_map - 1.0) > self.p.calib_ratio_tol:
            if self._calib_since is None:
                self._calib_since = self._now
            self._calib_suspect = self._now - self._calib_since >= self.p.calib_suspect_s - 1e-9
        else:
            self._calib_since, self._calib_suspect = None, False

    def _reacquire_timed_out(self) -> bool:
        if not self._stopped or self._now is None:
            return False
        since = max(t for t in (self._stop_t, self._t_candidate, -math.inf) if t is not None)
        return self._now - since > self.p.reacq_timeout_s

    def _enter_stop(self, reason: str) -> None:
        if not self._stopped:
            self._stop_t = self._now
        self._stopped, self.stop_reason = True, reason
        self._consistent = 0
        for i in range(3):   # d, phi, kappa start over as wide as a first acquisition
            self.P[i, i] = max(self.P[i, i], self._P0[i, i])

    def _refresh_level(self) -> None:
        p = self.p
        if self._stopped:
            self._level = STOP
            return
        s = p.odom_scale * self._s_lost
        t = 0.0 if self._t_accept is None or self._now is None else self._now - self._t_accept
        sd, sphi = math.sqrt(self.P[0, 0]), math.sqrt(self.P[1, 1])
        cap = p.lost_after_s - p.lost_margin_s
        reason = None
        if self._wall_run >= p.wall_only_frames:
            reason = "wall_only"
        elif self._frames_since < p.track_frames and s < p.coast_s_m and t <= cap:
            self._level = TRACK
        elif t > cap:
            reason = "lost_time"
        elif s < p.coast_s_m and sd < p.coast_sigma_d_m:
            self._level = COAST
        elif s < p.slow_s_m and sd < p.slow_sigma_d_m and sphi < p.slow_sigma_phi_rad:
            self._level = SLOW
        else:
            reason = "lost_distance" if s >= p.slow_s_m else "covariance"
        if reason is not None:
            self._enter_stop(reason)
            self._level = STOP


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


def _route_key(h: _Hyp, cands, hint: str):
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
