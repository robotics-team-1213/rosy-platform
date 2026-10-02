"""core_features.localization.mission — D-395 P2-7 check manoeuvres and homing missions.

Contract: docs/plans/2026-10-01-d395-phase2-interfaces.md §2. Fleet asks, CORE
drives (D-2, D-369): a mission is CORE's own very slow motion while the robot is
NOT LOCALIZED, so the robot node sees the world from a new place and searches again.

How motion reaches the wheels: the mission takes NAVIGATION from IDLE and writes
the nav slot of `CommandManager` (`set_nav_twist`), the same slot Nav2 and line
follow write. `select_output` (the 50 Hz final arbiter) still applies E-stop,
the readiness HOLD, the speed clip and the bound control policy. Kinds:

- `rotate_in_place`: up to one turn at `rotate_angular`, measured by odometry. D-424 (the
  robot's URDF body known from `line_follow.body_*`): refused when a return, moved to
  base_footprint, is within the rotation radius + `rotate_margin_m` (Pinky 0.113 m; returns
  inside the body outline are the robot itself), when a base sector has no return, or when
  a beam without a return crosses the sweep (rotation_reason). While turning, the same check
  with `rotate_stop_margin_m` (0.093 m) ends the turn ("obstacle"); D-424 review H1.
  Without the body: refused when any valid return is closer than `rotate_clearance_m`.
- `nudge_forward`: up to `max_distance_m` (<= `nudge_max_m`) by odometry. D-424 with the
  body: the front strip (half width + 0.010) must leave room for the D-422 stop gap
  g(`nudge_linear`) (Pinky ~0.085 m from the LiDAR) + `nudge_min_m`; less room than asked
  shortens the nudge, reaching the stop gap ends it, and a beam without a return that reaches
  past the body front (unknown out to `range_min`) refuses it. Without the body: refused and
  ended when the front LiDAR sector is closer than `min_front_clearance_m`, or when the
  sector cannot be measured: fewer than `min_front_beams` valid beams, or more than
  `max_blind_share` of them inf, NaN or below `range_min`. Self-masked returns do not count.
- `lane_to_stopline`: CORE's camera line follow, started here without the
  LOCALIZED gate of `PUT /line-follow/mode` (this kind only), capped to
  `lane_linear` through the safety session speed. Line follow keeps its own
  obstacle hold. Ends at a stop line (traffic policy evidence) or the bounds.
- `to_square`: refused `unsupported`. Without a map frame CORE has no lane route
  to a square; a straight crawl on a bearing would leave the lanes (follow-up).

Every mission ends on done, timeout, an obstacle, E-stop, LOCALIZED, odometry or
LiDAR going stale (every kind), or a cancel (any mode change out of NAVIGATION, line follow
OFF). The end stops motion, gives NAVIGATION back to IDLE and is published on
`localization/mission`, which makes the robot node search again.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, fields
from typing import Any, Callable, Mapping, Optional

from core_common.protocol.localization import CHECKING, LocState
from core_common.protocol.schemas import RobotMode
from core_common.robot_body import RobotBody
from core_features.command.arbitration import Mode
from core_features.command.manager import Twist
from core_features.line_follow.clearance import front_sector
from core_features.line_follow.model import LineFollowMode

ROTATE, NUDGE, LANE, SQUARE = "rotate_in_place", "nudge_forward", "lane_to_stopline", "to_square"
KINDS = (ROTATE, NUDGE, LANE, SQUARE)
UNSUPPORTED = {SQUARE: "to_square needs a lane route to the square without a map frame; "
                       "not implemented (D-395 P2-7 follow-up), use lane_to_stopline"}
#: End reasons that count as a completed mission; every other reason is `aborted`.
DONE_REASONS = frozenset({"done", "stop_line", "localized"})
_log = logging.getLogger(__name__)


class MissionRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MissionConfig:
    rotate_angular: float = 0.3          # rad/s; one turn takes about 21 s
    rotate_max_rad: float = 2.0 * math.pi
    nudge_linear: float = 0.03           # m/s
    nudge_max_m: float = 0.10
    lane_linear: float = 0.04            # m/s, half the line-follow cruise
    # Without the URDF body (line_follow.body_* unset) the LiDAR-origin rules below apply.
    min_front_clearance_m: float = 0.25
    front_half_angle_deg: float = 20.0
    min_front_beams: int = 5              # valid beams the nudge sector needs
    max_blind_share: float = 0.3          # inf/NaN/below-range share that blocks a nudge
    rotate_clearance_m: float = 0.20      # nothing this close anywhere before a turn
    # D-424 with the body: rotation radius + this (the D-422 body margin); shortest nudge.
    # D-424 review H1, until device evidence: start a turn with rho + 0.03, end it at rho + 0.01.
    rotate_margin_m: float = 0.03
    rotate_stop_margin_m: float = 0.01
    nudge_min_m: float = 0.02
    stop_line_m: float = 0.12            # the traffic policy's stop distance
    max_time_s: float = 120.0
    max_distance_m: float = 1.0
    sensor_stale_s: float = 0.5


def mission_config(raw: Optional[Mapping[str, Any]]) -> MissionConfig:
    """`localization_mission:` from the CORE config; absent or empty = the defaults (D-424).
    Unknown keys are an error, not silently ignored."""
    if not raw:
        return MissionConfig()
    if not isinstance(raw, Mapping):
        raise ValueError("localization_mission must be a mapping")
    known = {f.name: f.type for f in fields(MissionConfig)}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ValueError(f"unknown localization_mission keys: {unknown}")
    values = {k: (int(v) if known[k] in (int, "int") else float(v)) for k, v in raw.items()}
    config = MissionConfig(**values)
    if not all(math.isfinite(float(getattr(config, f.name))) for f in fields(config)):
        raise ValueError("localization_mission values must be finite")
    if (min(config.rotate_margin_m, config.rotate_stop_margin_m, config.nudge_min_m) < 0.0
            or config.rotate_stop_margin_m > config.rotate_margin_m or config.nudge_linear <= 0.0):
        raise ValueError("localization_mission margins must be >= 0 and nudge_linear > 0")
    return config


@dataclass
class _Run:
    kind: str
    max_distance_m: float
    max_time_s: float
    target: Optional[dict]
    started_at: float
    travelled_m: float = 0.0
    turned_rad: float = 0.0


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


class LocalizationMission:
    def __init__(self, events, *, command, modes, state, safety, line_follow, traffic_policy,
                 localization, busy: Callable[[], Optional[str]],
                 config: Optional[MissionConfig] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._events = events
        self._command, self._modes, self._state = command, modes, state
        self._safety, self._line_follow, self._traffic = safety, line_follow, traffic_policy
        self._loc = localization
        self._busy = busy
        self.config = config or MissionConfig()
        self._clock = clock
        #: Bound by the bridge to the `localization/mission` publisher.
        self.publish: Optional[Callable[[dict], None]] = None
        self._lock = threading.RLock()
        self._run: Optional[_Run] = None
        self._last: dict[str, Any] = {"kind": None, "state": "idle", "reason": None}
        self._odom: Optional[tuple[float, float, float]] = None
        self._odom_at: Optional[float] = None
        self._scan: Optional[tuple[Any, float]] = None
        self._front: tuple[Any, Any] = (None, None)
        modes.change_listeners.append(self._on_mode_change)

    def bind_clock(self, clock: Callable[[], float]) -> None:
        """The bridge's line clock: the ROS (sim) clock under `use_sim_time`, else monotonic."""
        with self._lock:
            self._clock = clock

    # --- inputs (bridge) ------------------------------------------------------

    def observe_odom(self, x: float, y: float, yaw: float) -> None:
        with self._lock:
            run, previous = self._run, self._odom
            if run is not None and previous is not None:
                run.travelled_m += math.hypot(x - previous[0], y - previous[1])
                run.turned_rad += abs(_wrap(yaw - previous[2]))
            self._odom, self._odom_at = (float(x), float(y), float(yaw)), self._clock()

    def observe_scan(self, sample) -> None:
        """Keep the latest LiDAR sample; the front sector is measured only when needed."""
        with self._lock:
            self._scan = (sample, self._clock())

    @property
    def owns_wheels(self) -> bool:
        """A rotate or nudge writes the nav slot itself; Nav2 output is dropped meanwhile."""
        with self._lock:
            return self._run is not None and self._run.kind != LANE

    # --- start / status -------------------------------------------------------

    def start(self, kind: str, max_distance_m: float, max_time_s: float,
              target: Optional[dict] = None) -> dict:
        """Start a mission or raise `MissionRefused` (409) / `ValueError` (400)."""
        if kind not in KINDS:
            raise ValueError(f"unknown mission kind {kind!r}")
        cfg = self.config
        if not (math.isfinite(max_time_s) and 0.0 < max_time_s <= cfg.max_time_s):
            raise ValueError(f"max_time_s must be in (0, {cfg.max_time_s}]")
        limit = cfg.nudge_max_m if kind == NUDGE else cfg.max_distance_m
        if not (math.isfinite(max_distance_m) and 0.0 <= max_distance_m <= limit):
            raise ValueError(f"max_distance_m must be in [0, {limit}] for {kind}")
        if kind in (NUDGE, LANE) and max_distance_m <= 0.0:
            raise ValueError(f"{kind} needs max_distance_m > 0")
        if kind in UNSUPPORTED:
            raise MissionRefused("unsupported", UNSUPPORTED[kind])
        # The leave-LOCALIZED halt and the LOCALIZED end take the same gate, so the
        # state cannot change between the check below and the dispatch.
        with self._loc.gate, self._lock:
            now = self._clock()
            if self._safety.estop or self._modes.is_emergency:
                raise MissionRefused("estop", "release the emergency stop first")
            status = self._loc.status()
            if status is not None and status.state is LocState.LOCALIZED:
                raise MissionRefused("localized", "the robot is LOCALIZED; missions only run without a pose")
            if self._run is not None:
                raise MissionRefused("busy", f"mission {self._run.kind} is running")
            if status is not None and status.reason == CHECKING:
                raise MissionRefused("busy", "the robot's 3 s injection check is running")
            reason = self._busy() or (None if self._modes.mode is Mode.IDLE
                                      else f"mode is {self._modes.mode.value}")
            if reason:
                raise MissionRefused("busy", reason)
            blocked, room = self._judge(kind, now)
            distance = float(max_distance_m)
            if blocked is None and kind == NUDGE and room < distance:
                if room < cfg.nudge_min_m:
                    blocked = f"only {room:.3f} m of room before the stop gap"
                else:
                    _log.info("nudge shortened to %.3f m of %.3f m (room before the stop gap)",
                              room, distance)
                    distance = room
            if blocked is not None:
                raise MissionRefused("path_not_clear", blocked)
            self._command.clear_navigation()
            ok, why = self._modes.transition(Mode.NAVIGATION, expect=Mode.IDLE)
            if not ok:
                raise MissionRefused("busy", why)
            self._state.set_mode(RobotMode.NAVIGATION)
            run = _Run(kind, distance, float(max_time_s), target, now)
            self._run = run
            if kind == LANE:
                self._safety.set_session_speed(cfg.lane_linear)
                self._state.set_line_follow(self._line_follow.set_mode(LineFollowMode.CAMERA_LINE))
            self._last = {"kind": kind, "state": "running", "reason": None}
            self._announce("started", run, None, now)
            return self.status()

    def status(self) -> dict:
        with self._lock:
            run = self._run
            if run is None:
                return dict(self._last)
            return {"kind": run.kind, "state": "running", "reason": None,
                    "elapsed_s": round(self._clock() - run.started_at, 2),
                    "travelled_m": round(run.travelled_m, 3), "turned_rad": round(run.turned_rad, 3)}

    # --- run --------------------------------------------------------------------

    def tick(self) -> None:
        """Bridge timer (20 Hz): check the end conditions, then command the next twist."""
        with self._lock:
            run = self._run
            if run is None:
                return
            try:
                reason = self._end_reason(run, self._clock())
            except Exception:  # noqa: BLE001 — the bridge timer must survive; the robot stops
                _log.exception("localization mission tick failed")
                reason = "error"
            if reason is None:
                if run.kind == ROTATE:
                    self._command.set_nav_twist(Twist(0.0, self.config.rotate_angular))
                elif run.kind == NUDGE:
                    self._command.set_nav_twist(Twist(self.config.nudge_linear, 0.0))
                return
            self.end(reason)

    def _end_reason(self, run: _Run, now: float) -> Optional[str]:
        cfg = self.config
        if self._safety.estop or self._modes.is_emergency:
            return "estop"
        status = self._loc.status()
        if status is not None and status.state is LocState.LOCALIZED:
            return "localized"
        if self._modes.mode is not Mode.NAVIGATION:
            return "cancelled"
        if now - run.started_at > run.max_time_s:
            return "timeout"
        if now - (self._odom_at if self._odom_at is not None else run.started_at) > cfg.sensor_stale_s:
            return "odometry_stale"
        if self._scan is None or now - self._scan[1] > cfg.sensor_stale_s:
            return "obstacle_sensor_stale"
        if run.kind == ROTATE:
            if run.turned_rad >= cfg.rotate_max_rad:
                return "done"
            # H1: something entering the sweep during the turn ends it.
            return "obstacle" if self._judge(ROTATE, now, running=True)[0] is not None else None
        if run.travelled_m >= run.max_distance_m:
            return "done"
        if run.kind == NUDGE:
            return "obstacle" if self._judge(NUDGE, now)[0] is not None else None
        if not self._line_follow.active:
            return "cancelled"
        if self._line_follow.status().state == "LOST":
            return "lane_lost"
        road = self._traffic.status()
        if (road.stop_line_visible and road.stop_line_distance_m is not None
                and road.stop_line_distance_m <= cfg.stop_line_m):
            return "stop_line"
        return None

    def end(self, reason: str) -> None:
        """Stop the running mission, if any: no motion, NAVIGATION back to IDLE."""
        with self._lock:
            run = self._run
            if run is None:
                return
            self._run = None
            if run.kind == LANE:
                if self._line_follow.active:
                    self._state.set_line_follow(self._line_follow.stop())
                self._safety.set_session_speed(None)
            if self._modes.transition(Mode.IDLE, expect=Mode.NAVIGATION)[0]:
                self._state.set_mode(RobotMode.IDLE)
            self._command.clear_navigation()
            state = "done" if reason in DONE_REASONS else "aborted"
            self._last = {"kind": run.kind, "state": state, "reason": reason}
            self._announce(state, run, reason, self._clock())

    def _on_mode_change(self, old: Mode, new: Mode) -> None:
        if old is Mode.NAVIGATION and new is not Mode.NAVIGATION:
            self.end("estop" if new is Mode.EMERGENCY else "cancelled")

    # --- helpers -----------------------------------------------------------------

    def _body(self) -> Optional[RobotBody]:
        """D-424: the URDF body from the line-follow config (robot package core.yaml), or None."""
        c = self._line_follow.config
        if not c.body_stop_known:
            return None
        try:
            return RobotBody(front_x_m=c.body_front_x_m, rear_x_m=c.body_rear_x_m,
                             half_width_m=c.body_half_width_m,
                             rotation_radius_m=c.body_rotation_radius_m, lidar_x_m=c.body_lidar_x_m,
                             lidar_forward_deg=c.lidar_forward_deg,
                             ultrasonic_x_m=c.body_ultrasonic_x_m,
                             margin_m=c.obstacle_body_margin_m, latency_s=c.obstacle_latency_s,
                             decel_mps2=c.obstacle_decel_mps2,
                             hysteresis_m=c.obstacle_resume_hysteresis_m, source="line_follow.body_*")
        except ValueError:
            _log.warning("line_follow body geometry is inconsistent; mission uses the LiDAR-origin rules")
            return None

    def _judge(self, kind: str, now: float, *, running: bool = False) -> tuple[Optional[str], float]:
        """(why the LiDAR does not show this kind's path clear or None, nudge room in metres).

        Room is the straight travel left before the D-422 stop gap (inf = nothing ahead)."""
        cfg = self.config
        if self._scan is None or now - self._scan[1] > cfg.sensor_stale_s:
            return "no fresh LiDAR scan", 0.0
        body = self._body()
        if body is None:
            return self._blocked(kind, now), math.inf
        config = self._line_follow.config
        view = body.scan_view(self._scan[0], forward_deg=config.lidar_forward_deg,
                              self_mask=config.lidar_self_mask)
        if kind == ROTATE:
            margin = cfg.rotate_stop_margin_m if running else cfg.rotate_margin_m
            reason = body.rotation_reason(view, margin)
            return (None, math.inf) if reason is None else (reason, 0.0)
        if body.unknown_blocks(view):
            return "front not measurable: a beam without a return reaches past the body front", 0.0
        gap = body.translation_gap(view.points)
        if gap is None:
            return None, math.inf
        stop = body.stop_gap_m(cfg.nudge_linear)
        if gap <= stop:
            return (f"front clearance {gap + body.lidar_to_front_m:.3f} m <= stop "
                    f"{stop + body.lidar_to_front_m:.3f} m (from the LiDAR)", 0.0)
        return None, gap - stop

    def _blocked(self, kind: str, now: float) -> Optional[str]:
        """Pre-D-424 rule (no URDF body): why the LiDAR does not show this kind's path clear."""
        cfg = self.config
        sample = self._scan[0]
        if self._front[0] is not sample:
            config = self._line_follow.config
            look = {"forward_deg": config.lidar_forward_deg, "self_mask": config.lidar_self_mask}
            self._front = (sample, (front_sector(sample, half_angle_deg=cfg.front_half_angle_deg, **look),
                                    front_sector(sample, half_angle_deg=180.0, **look)[0]))
        (front, valid, beams), nearest = self._front[1]
        if kind == ROTATE:
            if nearest is not None and nearest < cfg.rotate_clearance_m:
                return f"a return at {nearest:.2f} m < {cfg.rotate_clearance_m} m around the robot"
            return None
        if kind == NUDGE and (valid < cfg.min_front_beams
                              or beams - valid > cfg.max_blind_share * max(beams, 1)):
            return f"front sector not measurable ({valid} of {beams} beams valid)"
        if front is not None and front < cfg.min_front_clearance_m:
            return f"front clearance {front:.2f} m < {cfg.min_front_clearance_m} m"
        return None

    def _announce(self, phase: str, run: _Run, reason: Optional[str], now: float) -> None:
        self._events.publish("localization.mission", source="localization", data={
            "phase": phase,
            "kind": run.kind,
            "reason": reason,
            "elapsed_s": round(now - run.started_at, 2),
            "travelled_m": round(run.travelled_m, 3),
            "turned_rad": round(run.turned_rad, 3),
        })
        send = self.publish
        if send is not None:
            try:
                send({"kind": run.kind, "state": "running" if phase == "started" else phase,
                      "reason": reason})
            except Exception:  # noqa: BLE001 — a lost topic message must not keep the robot moving
                _log.exception("localization/mission publish failed")
