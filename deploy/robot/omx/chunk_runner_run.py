#!/usr/bin/env python3
"""The chunk Runner (`chunk_runner_run.py`, split of `chunk_runner.py`, D-766 2).

30 Hz control, adaptive pacing, jitter damping and contact/overload/push guards.
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
    CONTACT_LAG, CONTACT_TICKS, JOG_MAX, MOTORS, PWM_STOP, PWM_STOP_S, RECOVERY_PARKS, REL_MAX, SETTLE_TOL,
    STALL_GAP, STALL_MOVE, TEMP_STOP, build_chain_segments, build_jog_target, build_splice_frames,
    check_motor_thermal_and_stall, contact_limits, evaluate_adaptive_contact_guard, halt_thermal_or_stall, hold_runner,
    human_hold_ack, human_hold_overload, read_motor_health, shed_interrupt_hold,
)
from chunk_runner_trace import trace_receipt  # noqa: E402
from chunk_policy_playback import _hold_and_report, _is_holding, absorb_telemetry_error, active_jaw_gate, check_runner_jaw_gate, finish_tick, halt_policy_gate, read_present_or_hold, report_policy_halt, send_with_jaw_gate, tick_ready  # noqa: E402
from chunk_runner_loop import run  # noqa: E402
from chunk_runner_settle import (  # noqa: E402, F401
    IDLE_PARK_S, IDLE_RETRY_S, IDLE_STOP_S, SETTLE_S,
    check_chunk_settled, check_runner_idle, confirm_grip_release, confirm_post_write_present, tick_or_report, wait_aligned_before_start,
)
from episode_recorder import Recorder  # noqa: E402
from guarded_native_effort import enforce_temperatures, probe_runner_limits  # noqa: E402
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
        live=None, operating_context=None, params=None, plan_check=None, rim_z_m: float | None = None,
    ):
        self.params, self.plan_check, self.rim_z_m = params, plan_check or (lambda library: None), rim_z_m
        self.robot, self.library, self.fps, self.status = robot, library, fps, status
        self.clock, self.sleep = clock, sleep
        self.target, self.queue, self.chunk, self.settle_since = None, [], None, None
        self.far_since, self.last_grip, self.last_body, self.pending = None, None, None, []
        self.ticks, self.health, self.overload_since, self.fault = 0, None, None, None
        self.policy_playback = self.jaw_gate = self._trailing_jaw_gate = None
        self.shed_clear = self._shed_seen_at = self.last_present = self._release_until = self._release_floor = self._committed_grip = self._stop_after_park = self._held_jaw = self._last_sent_grip = self._off_approved = None
        self._fresh_present = False
        self.human_hold_latched = self.torque_hold_commanded = self._human_hold_ack_pending = False
        self.played, self.retreat_frames, self.jog_path, self.contact_ticks, self.contact_start = [], [], [], 0, None
        self.lag, self.paced, self.paced_ticks, self.pace_floor, self.pace_last = 0.0, 0, 0, 0.0, None
        self.last_input, self.home_since, self.idle_parks, self.peak_lag, self.over_ticks = 0.0, None, 0, 0.0, 0
        self.live, self.health_present, self.samples, self.grip_from, self.holding = live, None, [], None, False
        self.recorder, self.operating_context, self._lib_digest_cache = Recorder(), operating_context, None
        self.trend, self.trace, self.jitter_buf, self.damped_ticks = [], None, [], 0
        self.trace_file, self.trace_source, self.trace_cursor, self.trace_sequence = None, None, 0, 0
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
        self._fresh_present = True
        return self.last_present

    def report(self, *, present=None, **fields) -> None:
        was_guarded = self.human_hold_latched or bool(getattr(self, "signals", None))
        if hasattr(self.trace, "flush"):
            try:
                self.trace.flush()
            except OSError as error:
                if not absorb_telemetry_error(self, present, "trace flush failed", error):
                    raise
                if not was_guarded:
                    return
        reported_at = time.time()
        receipt = trace_receipt(self, fields.get("command"), reported_at, fields.get("ok"))
        state, ok = (present, True) if present is not None else read_present_or_hold(self, "encoder read failed")
        if not ok:
            return
        if self.jitter["shaking"] and "jitter" not in fields:
            fields["jitter"] = self.jitter
        fields.setdefault("holding", _is_holding(self))  # return home refuses an arm whose state does not say it is empty
        row = dict(
            fields, state=[round(v, 2) for v in state], target=[round(v, 2) for v in self.target],
            health=self.health, fault=self.fault, human_hold_latched=self.human_hold_latched,
            torque_hold_commanded=self.torque_hold_commanded, operating_context=self.operating_context,
            library_sha256=self._library_digest(), t=reported_at,
            **({"trace_receipt": receipt} if receipt is not None else {}),
        )
        try:
            self.status(row)
        except OSError as error:
            if (self.human_hold_latched or getattr(self, "signals", None)
                    or not absorb_telemetry_error(self, state, "status write failed", error)):
                raise

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
        play = self.policy_playback if self.chunk == "policy" else None
        ready = bool(self.queue) and (play is None or tick_ready(self, play))
        gate = None if self.human_hold_latched else active_jaw_gate(self, play)
        prev_target, advanced, consumed = list(self.target), False, False
        pace_lag, pace_rise = (
            prm.get(self.params, "runner.pace_lag", _cr_attr("PACE_LAG", PACE_LAG)),
            prm.get(self.params, "runner.pace_rise", _cr_attr("PACE_RISE", PACE_RISE)),
        )
        if self.lag < pace_lag:
            self.pace_floor = 0.0
        shrinking = self.pace_last is None or self.lag < self.pace_last - 0.01
        if (
            ready
            and self.lag > max(pace_lag, self.pace_floor + pace_rise)
            and shrinking
            and self.paced < prm.get(self.params, "runner.pace_max_s", PACE_MAX_S) * self.fps
        ):
            self.paced, self.paced_ticks, self.pace_last = self.paced + 1, self.paced_ticks + 1, self.lag
            if gate is not None and not check_runner_jaw_gate(self, gate, list(self.target), play.receipt() if play else None):
                play = gate = None
        elif ready:
            if self.pace_last is not None:
                self.pace_floor = max(self.pace_floor, self.lag)
            queued = len(self.queue)
            raw_target = runner_speed.take(self)
            if play is None and gate is None and (self.jitter.get("shaking") or (self.pace_last is not None and self.queue)):
                if self.jitter.get("shaking") and self.queue:
                    self._damp_cooldown = 3
                candidate = joint_jitter.damp_step(
                    self.ensembler, self.target or raw_target, raw_target, self.queue[:4],
                )
                self.damped_ticks += 1
            elif play is None and gate is None and self._damp_cooldown > 0 and self.queue:
                self._damp_cooldown -= 1
                candidate = joint_jitter.blend_to_raw(
                    self.ensembler, self.target, raw_target, self._damp_cooldown,
                    vmax=GUARD_UNITS_PER_S, fps=self.fps,
                )
            else:
                self._damp_cooldown = 0
                self.ensembler.reset(raw_target)
                candidate = raw_target
            if gate is not None and not check_runner_jaw_gate(self, gate, candidate, play.receipt() if play else None):
                play = gate = None
            else:
                self.target, self.paced, self.pace_last = candidate, 0, None
                advanced, consumed = True, len(self.queue) < queued
        elif gate is not None:
            if not check_runner_jaw_gate(self, gate, list(self.target), play.receipt() if play else None):
                play = gate = None
        self.trend = [] if self.chunk is None and not self.jog_path else self.trend
        vertical = self.chunk is not None and self.chunk.startswith(joint_jitter.SWAY_CHUNKS) and len(self.target) == 6
        cmd_target = self._pitch_held(vertical and self.chunk.startswith("descend") and "lift" not in self.chunk)
        if gate is not None and cmd_target != self.target and not check_runner_jaw_gate(
                self, gate, cmd_target, play.receipt() if play else None):
            play = gate = None
            advanced, cmd_target = False, self.target
        sent, committed = send_with_jaw_gate(self, dict(zip(NAMES, cmd_target)), gate, play, prev_target)
        hold_sent = self.human_hold_latched and (committed or sent is not None)
        if not committed:
            play = gate = None
        elif advanced:
            if self.chunk is not None:
                self.played.append(list(self.target))
            if play:
                play.sent(self.clock(), consumed=consumed)
        present, _ = confirm_post_write_present(self, sent, committed, read_present_or_hold, EMPTY_MARGIN)
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
            try:
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
            except OSError as error:
                if not absorb_telemetry_error(self, present, "trace write failed", error):
                    raise
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
            if (not self.human_hold_latched
                    and (self.chunk is not None or self.queue or getattr(self, "_stop_after_park", None)
                         or not (self.fault or "").startswith("contact (overload-hold"))):
                self.hold(present, f"contact (overload-hold on {', '.join(held)} by the guard): lift and elbow shed its load")
            self.retreat_frames = []
            shed_interrupt_hold(self, sent, present, fresh=bool(committed and self._fresh_present))
            return
        if isinstance(sent, dict) and not self.fault and self.chunk is not None and self.chunk.startswith(CONTACT_CHUNKS):
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
        elif isinstance(sent, dict) and (not self.fault or self.chunk in ("park", *RECOVERY_PARKS)) and (self.chunk is not None or self.jog_path):
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
            try:
                self.health = self.load_new = self.read_health()
            except Exception as read_error:  # noqa: BLE001
                motion = getattr(self.robot, "motion", None)
                keep_hold = bool(_is_holding(self) or play is not None or gate is not None or getattr(self, "_stop_after_park", None) or self.chunk in RECOVERY_PARKS or getattr(self, "_recovery_active", False))
                if getattr(motion, "failed", False) or not (self.human_hold_latched or keep_hold):
                    raise
                probe_runner_limits(motion)
                if self.human_hold_latched:
                    fresh = False
                elif self.chunk in RECOVERY_PARKS or getattr(self, "_recovery_active", False):
                    return self.hold(present, f"motor health unavailable: {read_error}")
                else:
                    _hold_and_report(self, present, f"motor health unavailable: {read_error}", play.receipt() if play else None)
                    return
        if self.health and fresh:
            motion = getattr(self.robot, "motion", None)
            if isinstance(self.health, dict) and isinstance(self.health.get("temp_c"), (list, tuple)):
                enforce_temperatures(motion, dict(zip(MOTORS, self.health["temp_c"])))
            probe_runner_limits(motion)
            thermal_only = bool(self.fault and not self.fault.startswith(("contact", "temperature"))
                                and max(self.health.get("temp_c") or (0,)) >= TEMP_STOP)
            if not self.fault or self.fault.startswith("contact") or thermal_only:
                reason, self.health_present, self.overload_since = check_motor_thermal_and_stall(
                    self.health, self.target, present, self.health_present, self.overload_since, now
                )
                if reason:
                    return halt_thermal_or_stall(self, present, reason, empty_margin=EMPTY_MARGIN)
                if not thermal_only:
                    self.samples = (self.samples + [(list(self.target), present, self.health["pwm"])])[-4:]
                    push = joint_push.pushing(
                        self.samples,
                        getattr(getattr(self.robot, "motion", None), "pwm_limits", None),
                        (self.chunk in ("park", *RECOVERY_PARKS) and not _is_holding(self)) or self.grip_from is not None,
                        self.params,
                    )
                    if push and push[0] == "gripper" and self.chunk is None:
                        self.target[5], self.grip_from = self.grip_from, None
                        return self.report(command="grip", ok=False, caught=True, error=f"{push[1]}; reopened", present=present)
                    if push and self.chunk is not None:
                        return self.hold(present, f"contact in {self.chunk}: {push[1]}")
                    if push and not self.human_hold_latched:
                        self.fault, self.target = f"pushing at rest: {push[1]}", present[:5] + [self.target[5]]
                        return report_policy_halt(self, present, halt_policy_gate(self), command="fault",
                                                  ok=False, error=self.fault, person_needed=True)
        if loaded > FOLLOW_STOP:
            self.far_since = self.far_since if self.far_since is not None else now
            if now - self.far_since >= FOLLOW_STOP_S:
                msg = f"following error {loaded:.1f} for {FOLLOW_STOP_S} s: blocked or colliding"
                if self.chunk in RECOVERY_PARKS or getattr(self, "_recovery_active", False):
                    return self.hold(present, msg)
                if getattr(self, "_stop_after_park", None):
                    return _hold_and_report(self, present, msg)
                raise RuntimeError(msg)
        else:
            self.far_since = None
        if play and self.chunk == "policy":
            if play.times:
                finish_tick(self, play, present, error, SETTLE_TOL)
        else:
            check_chunk_settled(self, present, error, now, _cr_attr)
        if self.chunk is None and self.jaw_gate is not None:
            self._trailing_jaw_gate, self.jaw_gate = (None if self.human_hold_latched else self.jaw_gate), None
        human_hold_ack(self, present, hold_sent=hold_sent)

    def idle(self) -> bool:
        """Fold home, then end the session (True), when no command has come for a while."""
        return not self.human_hold_latched and not getattr(self, "signals", None) and check_runner_idle(self, _cr_attr)

    run = run
