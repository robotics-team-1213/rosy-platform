#!/usr/bin/env python3
"""The chunk Runner (`chunk_runner_run.py`, split of `chunk_runner.py`, D-766 2).

Single Responsibility:
  - Real-time 30 Hz control loop (`Runner.tick`, `Runner.run`): adaptive pacing,
    `TemporalChunkEnsembler` jitter damping, and contact/overload/push guards.
  - Judge command parsing (`chunk_runner_commands.py`) and chunk settlement / idle auto-park
    (`chunk_runner_settle.py`) are delegated to dedicated modules.
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
    GUARD_UNITS_PER_S, NAMES, PARK_SPEED, RISE_SPEED, TRANSIT, TemporalChunkEnsembler,
    chain_path, load_library, park_path, receding_horizon_splice, too_fast, transit_path,
)
from omx_adapter.motion_profile import GUARD_ACCEL_UNITS_S2, smooth  # noqa: E402, F401
from cell_envelope import digest  # noqa: E402
import cell_params as prm  # noqa: E402
from chunk_runner_commands import EMPTY_MARGIN, dispatch_runner_command  # noqa: E402
from chunk_runner_guards import (  # noqa: E402, F401
    CONTACT_LAG, CONTACT_TICKS, JOG_MAX, MOTORS, PWM_STOP, PWM_STOP_S, REL_MAX, SETTLE_TOL,
    STALL_GAP, STALL_MOVE, TEMP_STOP, build_chain_segments, build_jog_target, build_splice_frames,
    check_motor_thermal_and_stall, contact_limits, evaluate_adaptive_contact_guard, hold_runner, human_hold_ack,
    human_hold_overload, read_motor_health,
)
from chunk_runner_trace import trace_receipt  # noqa: E402
from chunk_runner_settle import (  # noqa: E402, F401
    IDLE_PARK_S, IDLE_RETRY_S, IDLE_STOP_S, SETTLE_S, check_chunk_settled, check_runner_idle,
)
from episode_recorder import Recorder  # noqa: E402
import joint_jitter  # noqa: E402
import joint_push  # noqa: E402
import runner_speed  # noqa: E402
import runner_strain  # noqa: E402

FOLLOW_STOP, FOLLOW_STOP_S = 25.0, 1.0
HEALTH_PERIOD_S = 1.0
CONTACT_CHUNKS = runner_speed.CONTACT_CHUNKS
PACE_LAG, PACE_RISE, PACE_MAX_S = (prm.default(f"runner.{k}") for k in ("pace_lag", "pace_rise", "pace_max_s"))
_BODY_NAMES = tuple(NAMES[:5])

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
        self, robot, library: dict, *, fps: int, status, clock=time.monotonic, sleep=time.sleep,
        live=None, operating_context=None, params=None, plan_check=None,
    ):
        self.params, self.plan_check = params, plan_check or (lambda library: None)
        self.robot, self.library, self.fps, self.status = robot, library, fps, status
        self.clock, self.sleep = clock, sleep
        self.target, self.queue, self.chunk, self.settle_since = None, [], None, None
        self.far_since, self.last_grip, self.last_body, self.pending = None, None, None, []
        self.ticks, self.health, self.overload_since, self.fault = 0, None, None, None
        self.human_hold_latched = self.torque_hold_commanded = self._human_hold_ack_pending = False
        self.played, self.retreat_frames, self.jog_path, self.contact_ticks, self.contact_start = [], [], [], 0, None
        self.lag, self.paced, self.paced_ticks, self.pace_floor, self.pace_last = 0.0, 0, 0, 0.0, None
        self.last_input, self.home_since, self.idle_parks, self.peak_lag, self.over_ticks = 0.0, None, 0, 0.0, 0
        self.live, self.health_present, self.samples, self.grip_from, self.holding = live, None, [], None, False
        self.recorder, self.operating_context, self._lib_digest_cache = Recorder(), operating_context, None
        self.trend, self.trace, self.jitter_buf, self.damped_ticks = [], None, [], 0
        self.trace_file, self.trace_source, self.trace_cursor, self.trace_sequence = None, None, 0, 0
        self._damp_cooldown = 0
        self._damp_cooldown, self.sway_peak, self.pitch_hold, self.speed_queue = 0, {}, 0.0, None
        self.speed, self.speed_low, self.speed_out, self.speed_base, self.speed_phase = 1.0, 1.0, None, None, 0.0
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
        reported_at = time.time()
        receipt = trace_receipt(self, fields.get("command"), reported_at, fields.get("ok"))
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
                human_hold_latched=self.human_hold_latched,
                torque_hold_commanded=self.torque_hold_commanded,
                operating_context=self.operating_context,
                library_sha256=self._library_digest(),
                t=reported_at,
                **({"trace_receipt": receipt} if receipt is not None else {}),
            )
        )

    def read_health(self):
        """Temperature, PWM and current of every motor, or None when the robot exposes no bus (tests)."""
        return read_motor_health(self.robot)

    def command(self, line: str) -> bool:
        """Apply one judge command; False means stop."""
        return dispatch_runner_command(self, line)

    def hold(self, present, reason, *, human=False) -> None:
        """Stop where the arm is with torque on (the lag closes) and keep the way back for `retreat`."""
        hold_runner(self, present, reason, human=human, empty_margin=EMPTY_MARGIN)

    def strained(self, sent, present):
        return runner_strain.strained(self, sent, present)

    def _eval_jitter(self):
        if len(self.jitter_buf) < joint_jitter.MIN_TICKS:
            return {"shaking": False, "flagged": [], "max_std": 0.0}
        if not self.jitter.get("shaking") and self.ticks % 3 != 0:
            return self.jitter
        return joint_jitter.live_window(self.jitter_buf, self.params)

    def _pitch_held(self, descending: bool) -> list:
        """The target with wrist_flex nudged to hold the jaw pitch (joint_jitter.pitch_hold_step; off by default)."""
        last = getattr(self, "last_present", None) if descending else None
        self.pitch_hold = joint_jitter.pitch_hold_step(self.pitch_hold, self.target, last, self.params)
        return [*self.target[:3], self.target[3] + self.pitch_hold, *self.target[4:]] if self.pitch_hold else self.target

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
            raw_target = runner_speed.take(self)
            if self.jitter.get("shaking") or (self.pace_last is not None and self.queue):
                if self.jitter.get("shaking") and self.queue:
                    self._damp_cooldown = 3
                self.target = joint_jitter.damp_step(
                    self.ensembler, self.target or raw_target, raw_target, self.queue[:4],
                )
                self.damped_ticks += 1
            elif self._damp_cooldown > 0 and self.queue:
                self._damp_cooldown -= 1
                self.target = joint_jitter.blend_to_raw(
                    self.ensembler, self.target, raw_target, self._damp_cooldown,
                    vmax=GUARD_UNITS_PER_S, fps=self.fps,
                )
            else:
                self._damp_cooldown = 0
                self.ensembler.reset(raw_target)
                self.target = raw_target
            self.paced, self.pace_last = 0, None
            if self.chunk is not None:
                self.played.append(list(self.target))
        self.trend = [] if self.chunk is None and not self.jog_path else self.trend
        vertical = self.chunk is not None and self.chunk.startswith(joint_jitter.SWAY_CHUNKS) and len(self.target) == 6
        sent = self.robot.send_action(dict(zip(NAMES, self._pitch_held(vertical and self.chunk.startswith("descend") and "lift" not in self.chunk))))
        present = self.present()
        full_sent = isinstance(sent, dict) and all(n in sent for n in NAMES)
        row = {
            "t": self.clock(),
            "chunk": self.chunk,
            "target": list(self.target),
            "sent": [float(sent[n]) for n in NAMES] if full_sent else None,
            "present": list(present),
        }
        if vertical:
            row["tcp"] = joint_jitter.tcp_error(self.target, present)
        self.jitter_buf.append(row)
        if len(self.jitter_buf) > max(60, round(2.0 * self.fps) + 2):
            del self.jitter_buf[: -max(60, round(2.0 * self.fps) + 2)]
        self.jitter = self._eval_jitter()
        sway = joint_jitter.sway_window(self.jitter_buf, self.params) if vertical else None
        if sway:  # observation only: recorded in the chunk receipt, does not drive damping (2026-11-13 panel)
            peak = self.sway_peak
            for key in ("radial_mm", "pitch_deg"):
                peak[key] = max(peak.get(key, 0.0), sway[key])
            peak["swaying"] = peak.get("swaying", False) or sway["swaying"]
        if self.trace:
            load = self.__dict__.pop("load_new", None)
            self.trace(
                {
                    "t": round(self.clock(), 4),
                    "chunk": self.chunk,
                    "target": [round(v, 3) for v in self.target],
                    "sent": [round(float(sent[n]), 3) for n in NAMES] if full_sent else None,
                    "present": [round(v, 3) for v in present],
                    "s": round(self.speed, 3),
                    "pwm": getattr(getattr(self.robot, "motion", None), "effort_pwm", None) or {},
                    "owner_session_id": (self.operating_context or {}).get("session_id"),
                    "library_sha256": self._library_digest(),
                    **({"load": load} if load else {}),
                }
            )
        self.recorder.tick(present, [sent.get(n, t) if isinstance(sent, dict) else t for n, t in zip(NAMES, self.target)])
        if isinstance(sent, dict):
            self.lag = max(
                (abs(present[i] - sent[name]) for i, name in enumerate(_BODY_NAMES) if name in sent),
                default=0.0,
            )
            if self.chunk is not None:
                self.peak_lag, self.over_ticks = max(self.peak_lag, self.lag), self.over_ticks + (self.lag > CONTACT_LAG)
        motion = getattr(self.robot, "motion", None)
        held = getattr(motion, "held", None) or {}
        if held:
            if self.human_hold_latched:
                human_hold_overload(self, present)
            elif not (self.fault or "").startswith("contact"):
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
            lags = [abs(present[i] - sent[name]) if name in sent else 0.0 for i, name in enumerate(_BODY_NAMES)]
            prev_sent = (self.jitter_buf[-2].get("sent") or self.jitter_buf[-2].get("target")) if len(self.jitter_buf) >= 2 else None
            step_delta_fps = (
                max(abs(float(sent[name]) - float(prev_sent[i])) for i, name in enumerate(_BODY_NAMES) if name in sent) * self.fps
                if prev_sent
                else 0.0
            )
            self.contact_start, self.contact_ticks, tripped, lag = evaluate_adaptive_contact_guard(
                lags, self.contact_start, self.contact_ticks, self.params, step_delta_units=step_delta_fps
            )
            if tripped:
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
                chunk, self.chunk, self.pitch_hold, sway, self.sway_peak = self.chunk, None, 0.0, self.sway_peak, {}
                self.speed_low = 1.0
                self.report(command=f"run {chunk}" if chunk else "fault", ok=False, error=reason, present=present,
                            **({"sway": sway} if sway else {}))
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
        check_chunk_settled(self, present, error, now, _cr_attr)
        human_hold_ack(self, present)

    def idle(self) -> bool:
        """Fold home, then end the session (True), when no command has come for a while."""
        return not self.human_hold_latched and check_runner_idle(self, _cr_attr)

    def run(self, lines) -> None:
        """`lines()` returns the commands that arrived since the last call."""
        self.target = self.present()
        period = 1.0 / self.fps
        motion = getattr(self.robot, "motion", None)
        # Wait for the guard's stationary initial alignment before admitting or reporting ready for chunks.
        while motion is not None and not getattr(motion, "tracking", True):
            started = self.clock()
            arrived = lines()
            if arrived:
                self.pending += arrived
                if "human-hold" in self.pending:
                    self.pending.clear()  # preempt even a queued stop or park
                    self.command("human-hold")
                stop = next(
                    (i for i, cmd in enumerate(self.pending) if cmd.strip() in ("stop", "stop now", "stop fold")),
                    None,
                )
                if stop is not None and all(cmd.strip() == "state" for cmd in self.pending[:stop]):
                    for cmd in self.pending[:stop]:
                        self.command(cmd)
                    self.report(command=self.pending[stop], ok=True, present=self.target)
                    return
            try:
                self.tick()
            except Exception as error:
                self.status(
                    {
                        "command": "start",
                        "ok": False,
                        "fault": f"session ended: {type(error).__name__}: {error}"[:1000],
                        "t": round(time.time(), 3),
                    }
                )
                raise
            if self.human_hold_latched or self.fault or getattr(motion, "held", None):
                self.report(
                    command="start",
                    ok=False,
                    error=self.fault or ("human hold latched" if self.human_hold_latched else "guard hold active"),
                    present=self.target,
                )
                break
            self.sleep(max(0.0, period - (self.clock() - started)))
        else:
            self.report(command="start", ok=True, present=self.target)
        self.last_input = self.clock()
        while True:
            started = self.clock()
            arrived = lines()
            if arrived:
                self.last_input, self.idle_parks = started, 0
            self.pending += arrived
            if "human-hold" in self.pending:
                self.pending.clear()  # preempt even a queued stop or park
                self.command("human-hold")
            while (
                len(self.pending) > 1
                and self.pending[0].strip().split()[:1] in (["state"], ["episode"])
                and self.pending[1].strip().split()[:1] != ["state"]
            ):
                if not self.command(self.pending.pop(0)):
                    return
            if self.pending and not getattr(self, "_stop_after_park", None) and not self.command(self.pending.pop(0)):
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
            if getattr(self, "_stopped", False) or self.idle():
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
                        "human_hold_latched": self.human_hold_latched,
                        "torque_hold_commanded": self.torque_hold_commanded,
                        "health": self.health,
                        **({"jitter": self.jitter} if self.jitter["shaking"] else {}),
                    }
                )
            self.sleep(max(0.0, period - (self.clock() - started)))
