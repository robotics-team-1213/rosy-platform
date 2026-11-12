#!/usr/bin/env python3
"""The chunk Runner (`chunk_runner_run.py`, split of `chunk_runner.py`, D-766 2).

Single Responsibility:
  - Real-time 30 Hz control loop (`Runner.tick`, `Runner.idle`, `Runner.run`): adaptive pacing,
    `TemporalChunkEnsembler` jitter damping, contact/overload/push guards, and idle auto-park.
  - Judge command parsing and queue dispatch (`Runner.command`) live in `chunk_runner_commands.py`.
"""
from __future__ import annotations

from pathlib import Path
import sys
import time

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_ADAPTER_SRC = str(Path(__file__).resolve().parents[3] / "middleware/devices/omx/adapter")
if _ADAPTER_SRC not in sys.path:
    sys.path.insert(0, _ADAPTER_SRC)
from omx_adapter.chunk_library import (  # noqa: E402, F401
    GUARD_UNITS_PER_S,
    NAMES,
    PARK_SPEED,
    RISE_SPEED,
    TRANSIT,
    TemporalChunkEnsembler,
    chain_path,
    load_library,
    park_path,
    receding_horizon_splice,
    too_fast,
    transit_path,
)
from omx_adapter.motion_profile import GUARD_ACCEL_UNITS_S2, smooth  # noqa: E402, F401
from cell_envelope import digest  # noqa: E402
import cell_params as prm  # noqa: E402
from chunk_runner_commands import EMPTY_MARGIN, dispatch_runner_command  # noqa: E402
from chunk_runner_guards import (  # noqa: E402, F401
    CONTACT_LAG,
    CONTACT_TICKS,
    JOG_MAX,
    MOTORS,
    PWM_STOP,
    PWM_STOP_S,
    REL_MAX,
    SETTLE_TOL,
    STALL_GAP,
    STALL_MOVE,
    TEMP_STOP,
    build_chain_segments,
    build_jog_target,
    build_splice_frames,
    check_motor_thermal_and_stall,
    contact_limits,
    evaluate_adaptive_contact_guard,
    read_motor_health,
)
from episode_recorder import Recorder  # noqa: E402
import joint_jitter  # noqa: E402
import joint_push  # noqa: E402
import runner_strain  # noqa: E402

FOLLOW_STOP, FOLLOW_STOP_S = 25.0, 1.0
SETTLE_S = 3.0
HEALTH_PERIOD_S = 1.0
CONTACT_CHUNKS = ("descend", "grasp", "release")
PACE_LAG, PACE_RISE, PACE_MAX_S = (prm.default(f"runner.{k}") for k in ("pace_lag", "pace_rise", "pace_max_s"))
IDLE_PARK_S, IDLE_STOP_S, IDLE_RETRY_S = (prm.default(f"runner.idle_{k}_s") for k in ("park", "stop", "retry"))

_CR_DICT_LIST: list[dict] = []


def _cr_attr(name: str, default):
    for d in _CR_DICT_LIST:
        if name in d and d[name] != default:
            return d[name]
    mod = sys.modules.get("chunk_runner")
    if mod is not None and hasattr(mod, name):
        return getattr(mod, name)
    return default


class Runner:
    def __init__(
        self,
        robot,
        library: dict,
        *,
        fps: int,
        status,
        clock=time.monotonic,
        sleep=time.sleep,
        live=None,
        operating_context=None,
        params=None,
        plan_check=None,
    ):
        self.params, self.plan_check = params, plan_check or (lambda library: None)
        self.robot, self.library, self.fps, self.status = robot, library, fps, status
        self.clock, self.sleep = clock, sleep
        self.target = None
        self.queue: list = []
        self.chunk = None
        self.settle_since = None
        self.far_since, self.last_grip, self.last_body = None, None, None
        self.pending: list = []
        self.ticks, self.health, self.overload_since, self.fault = 0, None, None, None
        self.played, self.retreat_frames, self.jog_path, self.contact_ticks, self.contact_start = [], [], [], 0, None
        self.lag, self.paced, self.paced_ticks = 0.0, 0, 0
        self.pace_floor, self.pace_last = 0.0, None
        self.last_input, self.home_since = 0.0, None
        self.idle_parks = 0
        self.peak_lag, self.over_ticks = 0.0, 0
        self.live = live
        self.health_present, self.samples, self.grip_from, self.holding = None, [], None, False
        self.recorder = Recorder()
        self.operating_context = operating_context
        self._lib_digest_cache: tuple[int, str] | None = None
        self.trend: list = []
        self.trace = None
        self.jitter_buf, self.damped_ticks = [], 0
        self.jitter = {"shaking": False, "max_std": 0.0, "max_flips_hz": 0.0, "max_p2p": 0.0, "flagged": []}
        self.ensembler = TemporalChunkEnsembler(coeff=0.08, vmax=GUARD_UNITS_PER_S, fps=fps)

    def _library_digest(self) -> str:
        lib = self.library
        cached = self._lib_digest_cache
        if cached is None or cached[0] != id(lib):
            cached = (id(lib), digest(lib))
            self._lib_digest_cache = cached
        return cached[1]

    def present(self) -> list:
        observation = self.robot.get_observation()
        self.last_present = [float(observation[name]) for name in NAMES]
        return self.last_present

    def report(self, *, present=None, **fields) -> None:
        if hasattr(self.trace, "flush"):
            self.trace.flush()
        state = self.present() if present is None else present
        if self.jitter["shaking"] and "jitter" not in fields:
            fields["jitter"] = self.jitter
        self.status(
            dict(
                fields,
                state=[round(v, 2) for v in state],
                target=[round(v, 2) for v in self.target],
                health=self.health,
                fault=self.fault,
                operating_context=self.operating_context,
                library_sha256=self._library_digest(),
                t=time.time(),
            )
        )

    def read_health(self):
        """Temperature, PWM and current of every motor, or None when the robot exposes no bus (tests)."""
        return read_motor_health(self.robot)

    def command(self, line: str) -> bool:
        """Apply one judge command; False means stop."""
        return dispatch_runner_command(self, line)

    def hold(self, present, reason) -> None:
        """Stop where the arm is with torque on (the lag closes) and keep the way back for `retreat`."""
        chunk, jogging = self.chunk, bool(self.jog_path)
        self.queue, self.retreat_frames = [], (self.played or self.jog_path[:-1])[::-1]
        self.target = list(present[:5]) + [self.target[5]]
        self.fault, self.holding = reason, bool(self.holding and present[5] > self.target[5] + EMPTY_MARGIN)
        self.chunk, self.played, self.jog_path = None, [], []
        if chunk == "park":
            self.last_input = self.clock()
        self.report(
            command=f"run {chunk or 'jog'}" if chunk or jogging else "fault",
            ok=False,
            error=self.fault,
            contact=True,
            present=present,
        )

    def strained(self, sent, present):
        return runner_strain.strained(self, sent, present)

    def tick(self) -> None:
        pace_lag, pace_rise = (
            prm.get(self.params, "runner.pace_lag", _cr_attr("PACE_LAG", PACE_LAG)),
            prm.get(self.params, "runner.pace_rise", _cr_attr("PACE_RISE", PACE_RISE)),
        )
        if self.lag < pace_lag:
            self.pace_floor = 0.0
        shrinking = self.pace_last is None or self.lag < self.pace_last - 0.01
        if (
            self.queue
            and self.lag > max(pace_lag, self.pace_floor + pace_rise)
            and shrinking
            and self.paced < prm.get(self.params, "runner.pace_max_s", PACE_MAX_S) * self.fps
        ):
            self.paced, self.paced_ticks, self.pace_last = self.paced + 1, self.paced_ticks + 1, self.lag
        elif self.queue:
            if self.pace_last is not None:
                self.pace_floor = max(self.pace_floor, self.lag)
            raw_target = self.queue.pop(0)
            if self.jitter["shaking"] or (self.pace_last is not None and self.queue):
                self.target = joint_jitter.damp_step(self.ensembler, self.target or raw_target, raw_target, self.queue)
                self.damped_ticks += 1
            else:
                self.ensembler.reset(raw_target)
                self.target = raw_target
            self.paced, self.pace_last = 0, None
            if self.chunk is not None:
                self.played.append(list(self.target))
        self.trend = [] if self.chunk is None and not self.jog_path else self.trend
        sent = self.robot.send_action(dict(zip(NAMES, self.target)))
        present = self.present()
        full_sent = isinstance(sent, dict) and all(n in sent for n in NAMES)
        self.jitter_buf.append(
            {
                "t": self.clock(),
                "chunk": self.chunk,
                "target": list(self.target),
                "sent": [float(sent[n]) for n in NAMES] if full_sent else None,
                "present": list(present),
            }
        )
        if len(self.jitter_buf) > max(60, round(2.0 * self.fps) + 2):
            del self.jitter_buf[: -max(60, round(2.0 * self.fps) + 2)]
        self.jitter = joint_jitter.live_window(self.jitter_buf, self.params)
        if self.trace:
            load = self.__dict__.pop("load_new", None)
            self.trace(
                {
                    "t": round(self.clock(), 4),
                    "chunk": self.chunk,
                    "target": [round(v, 3) for v in self.target],
                    "sent": [round(float(sent[n]), 3) for n in NAMES] if full_sent else None,
                    "present": [round(v, 3) for v in present],
                    "pwm": getattr(getattr(self.robot, "motion", None), "effort_pwm", None) or {},
                    **({"load": load} if load else {}),
                }
            )
        self.recorder.tick(present, [sent.get(n, t) if isinstance(sent, dict) else t for n, t in zip(NAMES, self.target)])
        if isinstance(sent, dict):
            self.lag = max(
                (abs(present[i] - sent[name]) for i, name in enumerate(NAMES[:5]) if name in sent),
                default=0.0,
            )
            if self.chunk is not None:
                self.peak_lag, self.over_ticks = max(self.peak_lag, self.lag), self.over_ticks + (self.lag > CONTACT_LAG)
        motion = getattr(self.robot, "motion", None)
        held = getattr(motion, "held", None) or {}
        if held:
            if not (self.fault or "").startswith("contact"):
                self.hold(
                    present, f"contact (overload-hold on {', '.join(held)} by the guard): lift and elbow shed its load"
                )
            self.retreat_frames = []
            home = self.library["chunks"].get("home")
            if home:
                self.target = runner_strain.shed(
                    self.target,
                    present,
                    sent if isinstance(sent, dict) else {},
                    home[-1],
                    0.5 * GUARD_UNITS_PER_S / self.fps,
                )
            runner_strain.release_when_clear(self, motion, held, self.clock())
            return
        if (
            isinstance(sent, dict)
            and not self.fault
            and self.chunk is not None
            and self.chunk.startswith(CONTACT_CHUNKS)
        ):
            lags = [abs(present[i] - sent[name]) if name in sent else 0.0 for i, name in enumerate(NAMES[:5])]
            if self.contact_start is None:
                self.contact_start = contact_limits(lags, self.params)
            lag = max(lags)
            over = any(v > limit for v, limit in zip(lags, self.contact_start))
            self.contact_ticks = self.contact_ticks + 1 if over else 0
            if self.contact_ticks >= prm.get(self.params, "runner.contact_ticks", CONTACT_TICKS):
                self.hold(present, f"contact in {self.chunk}: a joint lagged the command by {lag:.1f} units")
        elif (
            isinstance(sent, dict)
            and (not self.fault or self.chunk == "park")
            and (self.chunk is not None or self.jog_path)
        ):
            strain = self.strained(sent, present)
            if strain:
                motor, lag, pwm, limit = strain
                others = ", ".join(
                    f"{n} {abs(present[i] - sent[f'{n}.pos']):.1f}"
                    for i, n in enumerate(MOTORS[:5])
                    if n != motor and f"{n}.pos" in sent
                )
                self.hold(
                    present,
                    f"contact in {self.chunk or 'jog'}: {motor} lag rose to {lag:.1f} units at PWM {pwm} of {limit}"
                    f" (lags: {others})",
                )
                return
        error = max(abs(a - b) for a, b in zip(present[:5], self.target[:5]))
        loaded = max(abs(a - b) for a, b in zip(present[:4], self.target[:4]))
        now = self.clock()
        self.ticks += 1
        fresh = self.ticks % max(1, round(self.fps * HEALTH_PERIOD_S)) == 0
        if fresh:
            self.health = self.load_new = self.read_health()
        if self.health and fresh and not self.fault:
            reason, self.health_present, self.overload_since = check_motor_thermal_and_stall(
                self.health, self.target, present, self.health_present, self.overload_since, now
            )
            if reason:
                self.fault, self.queue, self.target = reason, [], present[:5] + [self.target[5]]
                chunk, self.chunk = self.chunk, None
                self.report(command=f"run {chunk}" if chunk else "fault", ok=False, error=reason, present=present)
                return
            self.samples = (self.samples + [(list(self.target), present, self.health["pwm"])])[-4:]
            push = joint_push.pushing(
                self.samples,
                getattr(getattr(self.robot, "motion", None), "pwm_limits", None),
                (self.chunk == "park" and not self.holding) or self.grip_from is not None,
                self.params,
            )
            if push and push[0] == "gripper" and self.chunk is None:
                self.target[5], self.grip_from = self.grip_from, None
                return self.report(command="grip", ok=False, caught=True, error=f"{push[1]}; reopened", present=present)
            if push and self.chunk is not None:
                return self.hold(present, f"contact in {self.chunk}: {push[1]}")
            if push:
                self.fault, self.target = f"pushing at rest: {push[1]}", present[:5] + [self.target[5]]
                return self.report(command="fault", ok=False, error=self.fault, person_needed=True, present=present)
        if loaded > FOLLOW_STOP:
            self.far_since = self.far_since if self.far_since is not None else now
            if now - self.far_since >= FOLLOW_STOP_S:
                raise RuntimeError(f"following error {loaded:.1f} for {FOLLOW_STOP_S} s: blocked or colliding")
        else:
            self.far_since = None
        if self.chunk is not None and not self.queue:
            self.settle_since = self.settle_since if self.settle_since is not None else now
            grasp = self.chunk.startswith("grasp")
            gripper_still = self.last_grip is not None and abs(present[5] - self.last_grip) < 0.3
            self.last_grip = present[5]
            body_still = (
                self.last_body is not None
                and max(abs(a - b) for a, b in zip(present[:5], self.last_body)) < 0.08
                and error <= SETTLE_TOL + min(self.pace_floor, 0.8)
            )
            self.last_body = list(present[:5])
            settled = (error <= SETTLE_TOL or body_still) and not self.jitter["shaking"]
            if (settled and (gripper_still or not grasp)) or now - self.settle_since >= SETTLE_S:
                fields = dict(
                    command=f"run {self.chunk}",
                    ok=True,
                    settled=settled,
                    paced_ticks=self.paced_ticks,
                    peak_lag=round(self.peak_lag, 2),
                    over_ticks=self.over_ticks,
                    **({"damped_ticks": self.damped_ticks} if self.damped_ticks else {}),
                )
                self.paced_ticks, self.pace_floor, self.peak_lag, self.over_ticks, self.damped_ticks = 0, 0.0, 0.0, 0, 0
                if (self.chunk == "park" or self.chunk.endswith("; park")) and settled:
                    self.home_since = now
                backed_out = self.chunk == "retreat" and settled
                if (self.chunk == "park" or self.chunk.endswith("; park") or backed_out) and (
                    self.fault or ""
                ).startswith("contact"):
                    self.fault = None
                if grasp:
                    by_position = present[5] > self.target[5] + EMPTY_MARGIN
                    fields["holding"] = by_position
                    health = self.read_health()
                    if health:
                        self.health = health
                        current = abs(health["current_ma"][5])
                        fields["gripper_current_ma"] = current
                        threshold = self.library.get("hold_current_ma")
                        if threshold is not None:
                            fields["holding"] = by_position and current >= threshold
                    self.holding = bool(fields["holding"])
                elif self.holding and self.chunk in ("lift_pick", "park", "goto above_place", "descend_place"):
                    self.holding = present[5] > self.target[5] + EMPTY_MARGIN
                    fields["holding"] = self.holding
                self.chunk, self.last_grip, self.last_body = None, None, None
                self.report(**fields, present=present)

    def idle(self) -> bool:
        """Fold home, then end the session (True), when no command has come for a while."""
        if self.chunk is not None or self.queue or self.pending:
            return False
        quiet = self.clock() - self.last_input
        if self.home_since is None:
            if self.idle_parks >= 2:
                if self.idle_parks == 2:
                    self.idle_parks, self.fault = 3, f"idle fold held twice ({self.fault}): a person must free the arm"
                    self.report(command="park", ok=False, error=self.fault, person_needed=True)
                return False
            wait = (
                prm.get(self.params, "runner.idle_retry_s", IDLE_RETRY_S)
                if self.idle_parks
                else prm.get(self.params, "runner.idle_park_s", IDLE_PARK_S)
            )
            if quiet >= wait:
                self.last_input = self.clock()
                self.idle_parks += 1
                self.command("park")
            return False
        pushed = (self.fault or "").startswith("pushing at rest")
        if pushed or min(quiet, self.clock() - self.home_since) >= prm.get(self.params, "runner.idle_stop_s", IDLE_STOP_S):
            self.report(
                command="stop",
                ok=True,
                reason=f"{self.fault if pushed else f'no command for {quiet:.0f} s'}; folded home, torque goes OFF",
            )
            return True
        return False

    def run(self, lines) -> None:
        """`lines()` returns the commands that arrived since the last call."""
        self.target = self.present()
        self.report(command="start", ok=True, present=self.target)
        period = 1.0 / self.fps
        self.last_input = self.clock()
        while True:
            started = self.clock()
            arrived = lines()
            if arrived:
                self.last_input, self.idle_parks = started, 0
            self.pending += arrived
            while (
                len(self.pending) > 1
                and self.pending[0].strip().split()[:1] in (["state"], ["episode"])
                and self.pending[1].strip().split()[:1] != ["state"]
            ):
                if not self.command(self.pending.pop(0)):
                    return
            if self.pending and not self.command(self.pending.pop(0)):
                return
            try:
                self.tick()
            except Exception as error:
                self.status(
                    {
                        "command": f"run {self.chunk}" if self.chunk else "tick",
                        "ok": False,
                        "fault": f"session ended: {type(error).__name__}: {error}"[:1000],
                        "t": round(time.time(), 3),
                    }
                )
                raise
            if self.idle():
                return
            if self.live and self.ticks % max(1, self.fps // 10) == 0:
                self.live(
                    {
                        "t": round(time.time(), 3),
                        "state": [round(v, 2) for v in (getattr(self, "last_present", None) or self.present())],
                        "target": [round(v, 2) for v in self.target],
                        "chunk": self.chunk,
                        "lag": round(self.lag, 2),
                        "fault": self.fault,
                        "health": self.health,
                        **({"jitter": self.jitter} if self.jitter["shaking"] else {}),
                    }
                )
            self.sleep(max(0.0, period - (self.clock() - started)))
