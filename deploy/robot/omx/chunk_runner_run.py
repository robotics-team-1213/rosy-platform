#!/usr/bin/env python3
"""The chunk Runner (split of `chunk_runner.py`, D-766 2).

Plays taught chunks/jogs one command per tick under the guard. The tests patch
`chunk_runner.PACE_LAG`, so the pace constants stay there and this module reads them
late through `_cr` (attribute access at call time), never at import time.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import sys

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_ADAPTER_SRC = str(Path(__file__).resolve().parents[3] / "middleware/devices/omx/adapter")
if _ADAPTER_SRC not in sys.path:
    sys.path.insert(0, _ADAPTER_SRC)
from omx_adapter.chunk_library import (  # noqa: E402
    GUARD_UNITS_PER_S, NAMES, PARK_SPEED, RISE_SPEED, TRANSIT, TemporalChunkEnsembler, chain_path,
    load_library, park_path, receding_horizon_splice, too_fast, transit_path,
)
from omx_adapter.motion_profile import GUARD_ACCEL_UNITS_S2, smooth  # noqa: E402
from cell_envelope import digest  # noqa: E402
import cell_params as prm  # noqa: E402
from episode_recorder import Recorder  # noqa: E402
import joint_push  # noqa: E402
import runner_strain  # noqa: E402

JOG_MAX = 5.0
FOLLOW_STOP, FOLLOW_STOP_S = 25.0, 1.0
SETTLE_TOL, SETTLE_S, EMPTY_MARGIN = 3.0, 3.0, 2.0
REL_MAX = 20.0
HEALTH_PERIOD_S = 1.0
CONTACT_LAG, CONTACT_TICKS = prm.default("runner.contact_lag"), prm.default("runner.contact_ticks")
CONTACT_CHUNKS = ("descend", "grasp", "release")
PACE_LAG, PACE_RISE, PACE_MAX_S = (prm.default(f"runner.{k}") for k in ("pace_lag", "pace_rise", "pace_max_s"))
IDLE_PARK_S, IDLE_STOP_S, IDLE_RETRY_S = (prm.default(f"runner.idle_{k}_s") for k in ("park", "stop", "retry"))
TEMP_STOP = 65
PWM_STOP, PWM_STOP_S, STALL_GAP, STALL_MOVE = 285, 0.5, 4.0, 0.3
MOTORS = [n.split(".")[0] for n in NAMES]


def contact_limits(start_lags: list, params=None) -> list:
    base = prm.get(params, "runner.contact_lag", CONTACT_LAG)
    rise, top = prm.get(params, "runner.contact_rise"), prm.get(params, "runner.contact_loaded_max")
    return [max(base, min(s + rise, top)) for s in start_lags]


def _cr_attr(name: str, default):
    mod = sys.modules.get("chunk_runner")
    if isinstance(mod, dict):
        return mod.get(name, default)
    return getattr(mod, name, default) if mod is not None else default


class Runner:
    def __init__(self, robot, library: dict, *, fps: int, status, clock=time.monotonic, sleep=time.sleep,
                 live=None, operating_context=None, params=None, plan_check=None):
        self.params, self.plan_check = params, plan_check or (lambda library: None)  # cell_params (None = constants); load_predict
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
        self.lag, self.paced, self.paced_ticks = 0.0, 0, 0  # paced_ticks: frames held in the current chunk
        self.pace_floor, self.pace_last = 0.0, None
        self.last_input, self.home_since = 0.0, None  # home_since: a park settled and nothing moved since
        self.idle_parks = 0  # folds started by idle() since the last command
        # per chunk: the largest lag behind the command the guard sent, and the ticks it spent over CONTACT_LAG;
        # the contact margin a real run leaves, which live.json's chunk target does not show (2026-10-26)
        self.peak_lag, self.over_ticks = 0.0, 0
        self.live = live  # called about twice a second with the current state (Fleet observation bridge)
        self.health_present, self.samples, self.grip_from, self.holding = None, [], None, False  # joint_push's samples and reopen point
        self.recorder = Recorder()  # raw training episodes: rows here, encoding after the session
        self.operating_context = operating_context
        self._lib_digest_cache: tuple[int, str] | None = None
        self.trend: list = []  # load-bearing joints' lags over the last STRAIN_TICKS ticks of a chunk
        self.trace = None      # called every tick with what was commanded and where the arm was (jitter)

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
        self.status(dict(fields, state=[round(v, 2) for v in state],
                         target=[round(v, 2) for v in self.target], health=self.health, fault=self.fault,
                         operating_context=self.operating_context, library_sha256=self._library_digest(),
                         t=time.time()))

    def read_health(self):
        """Temperature, PWM and current of every motor, or None when the robot exposes no bus (tests)."""
        bus = getattr(self.robot, "bus", None)
        if bus is None:
            return None
        def signed(v):
            return int(v) - 65536 if int(v) > 32767 else int(v)
        kw = {"normalize": False, "num_retry": 2} if "read" not in vars(bus) and hasattr(bus, "model_ctrl_table") else {}
        pwm, current, temp = (bus.sync_read(name, **kw) for name in ("Present_PWM", "Present_Current", "Present_Temperature"))
        return {"pwm": [signed(pwm[m]) for m in MOTORS], "current_ma": [signed(current[m]) for m in MOTORS],
                "temp_c": [int(temp[m]) for m in MOTORS]}

    def command(self, line: str) -> bool:
        """Apply one judge command; False means stop."""
        words = line.split()
        if not words:
            return True
        verb = words[0]
        expected_library = None
        if verb not in ("state", "stop", "park"):
            self.home_since = None
        try:
            if verb not in ("checked", "state", "stop") and self.operating_context:
                self.operating_context = {**self.operating_context, "session_id": uuid.uuid4().hex}
            if verb == "checked":
                if len(words) < 4:
                    raise ValueError("checked requires session, library digest and command")
                session, expected_library, words = words[1], words[2], words[3:]
                line, verb = " ".join(words), words[0]
                if not self.operating_context or self.operating_context.get("session_id") != session:
                    raise ValueError("checked command targets another session")
                if verb != "load" and self._library_digest() != expected_library:
                    raise ValueError("checked command targets another library")
            self.grip_from = self.grip_from if verb in ("state", "grip", "episode") else None
            self.jog_path = self.jog_path if verb in ("jog", "state", "episode") else []
            if verb == "stop":
                self.report(command=line, ok=True)
                return False
            if verb == "episode":  # bookkeeping only: allowed between chunks and after a fault (to drop the episode)
                self.report(command=line, ok=True, **self.recorder.command(words[1:]))
                return True
            if self.chunk is not None and verb != "splice":
                raise ValueError(f"chunk {self.chunk} is still running")
            if getattr(getattr(self.robot, "motion", None), "held", None) and verb != "state":
                raise ValueError("the guard holds an overloaded joint: the runner is shedding its load first")
            soft = (self.fault or "").startswith("contact")
            if self.fault and verb not in ("park", "state") and not (soft and verb in ("retreat", "jog")):
                raise ValueError(f"fault ({self.fault}): only park, state or stop"
                                 + (", or retreat/jog after a contact" if soft else ""))
            if verb == "splice" and len(words) in (2, 3) and words[2:] in ([], ["rel"]):
                frames = self.library["chunks"].get(words[1])
                if frames is None:
                    raise ValueError(f"unknown chunk {words[1]}")
                window = max(1, min(len(self.queue), round(0.25 * self.fps))) if self.queue else 0
                anchor = self.queue[window - 1] if window else self.target
                offset = [0.0] * 6
                if words[2:] == ["rel"]:
                    offset = [t - s for t, s in zip(anchor[:5], frames[0][:5])] + [0.0]
                    if max(abs(v) for v in offset) > REL_MAX:
                        raise ValueError(f"relative offset {max(abs(v) for v in offset):.1f} exceeds {REL_MAX}")
                next_frames = [[max(-100.0, min(100.0, v + o)) for v, o in zip(f, offset)] for f in frames]
                gap = max(abs(a - b) for a, b in zip(next_frames[0][:5], anchor[:5]))
                if gap > JOG_MAX * 2:
                    raise ValueError(f"chunk {words[1]} starts {gap:.1f} away from the splice anchor")
                self.queue = receding_horizon_splice(self.queue, self.target, next_frames, self.fps,
                                                     blend_s=0.25, vmax=GUARD_UNITS_PER_S)
                if words[1].startswith("release"):
                    self.holding = False
                self.chunk = words[1] if self.chunk is None else f"{self.chunk} -> {words[1]}"
                self.settle_since, self.contact_ticks, self.contact_start = None, 0, None
                return True
            if verb == "run" and len(words) in (2, 3) and words[2:] in ([], ["rel"]):
                frames = self.library["chunks"].get(words[1])
                if frames is None:
                    raise ValueError(f"unknown chunk {words[1]}")
                start = frames[0]
                offset = [0.0] * 6
                if words[2:] == ["rel"]:  # keep the judge's corrections: shift the body joints, never the jaws
                    offset = [t - s for t, s in zip(self.target[:5], start[:5])] + [0.0]
                    if max(abs(v) for v in offset) > REL_MAX:
                        raise ValueError(f"relative offset {max(abs(v) for v in offset):.1f} exceeds {REL_MAX}")
                gap = max(abs(a + o - b) for a, o, b in zip(start[:5], offset, self.target[:5]))
                if gap > JOG_MAX * 2:  # chunks chain end to start; a big jump means the wrong order
                    raise ValueError(f"chunk {words[1]} starts {gap:.1f} away from the held target")
                self.queue = [[max(-100.0, min(100.0, v + o)) for v, o in zip(f, offset)] for f in frames]
                if words[1].startswith("release"):
                    self.holding = False
                self.chunk, self.settle_since, self.played, self.contact_ticks = words[1], None, [], 0
                self.contact_start = None
                return True
            if verb == "jog" and len(words) >= 3 and len(words) % 2 == 1:
                # jog <joint> <delta> [<joint> <delta> ...]: one coordinated step (e.g. a forward reach),
                # validated as a whole before any joint moves
                present, moved = self.present(), list(self.target)
                pairs = list(zip(words[1::2], words[2::2]))
                if len({name for name, _ in pairs}) != len(pairs) or any(name not in NAMES for name, _ in pairs):
                    raise ValueError("jog takes distinct follower joint names")
                for name, value in pairs:
                    delta, index = float(value), NAMES.index(name)
                    if not abs(delta) <= JOG_MAX:
                        raise ValueError(f"jog is limited to {JOG_MAX}")
                    moved[index] = max(-100.0, min(100.0, moved[index] + delta))
                    if abs(moved[index] - present[index]) > JOG_MAX + SETTLE_TOL:
                        raise ValueError(f"jog would put the target more than {JOG_MAX + SETTLE_TOL} from the joint")
                self.jog_path, self.target = (self.jog_path or [list(self.target)]) + [list(moved)], moved
            elif verb == "goto" and len(words) == 2:
                frames = self.library["chunks"].get(words[1])
                if frames is None:
                    raise ValueError(f"unknown chunk {words[1]}")
                transit = {NAMES.index(k): float(v) for k, v in self.library.get("transit", {}).items()} or None
                self.queue = transit_path(self.target, frames[0], self.library["gripper_closed"], self.fps, transit,
                                          self.library.get("transit_speed", 0.85))
                self.chunk, self.settle_since, self.played = f"goto {words[1]}", None, []
                return True
            elif verb == "park" and len(words) == 1:
                home = self.library["chunks"].get("home")
                if not home:
                    raise ValueError("park needs a home chunk in the library")
                transit = {NAMES.index(k): float(v) for k, v in self.library.get("transit", {}).items()} or None
                self.queue = park_path(self.target, home[-1], self.library["gripper_closed"], self.fps, transit,
                                       self.library.get("transit_speed", 0.85))
                self.chunk, self.settle_since, self.played = "park", None, []
                return True
            elif verb == "chain" and len(words) >= 2:
                parts = [part.strip().split() for part in " ".join(words[1:]).split(";") if part.strip()]
                if not parts:
                    raise ValueError("chain requires at least one step")
                cursor, segments, release = list(self.target), [], False
                transit = {NAMES.index(k): float(v) for k, v in self.library.get("transit", {}).items()} or None
                speed = self.library.get("transit_speed", 0.85)
                closed = self.library["gripper_closed"]
                for step in parts:
                    if step[0] == "run" and len(step) == 2:
                        frames = self.library["chunks"].get(step[1])
                        if frames is None:
                            raise ValueError(f"unknown chunk {step[1]}")
                        gap = max(abs(a - b) for a, b in zip(frames[0][:5], cursor[:5]))
                        if gap > JOG_MAX * 2:
                            raise ValueError(f"chunk {step[1]} starts {gap:.1f} away from the held target")
                        seg = [list(f) for f in frames]
                        if step[1].startswith("release"):
                            release = True
                    elif step[0] == "goto" and len(step) == 2:
                        frames = self.library["chunks"].get(step[1])
                        if frames is None:
                            raise ValueError(f"unknown chunk {step[1]}")
                        seg = transit_path(cursor, frames[0], closed, self.fps, transit, speed)
                    elif step == ["park"]:
                        home = self.library["chunks"].get("home")
                        if not home:
                            raise ValueError("park needs a home chunk in the library")
                        seg = park_path(cursor, home[-1], closed, self.fps, transit, speed)
                    else:
                        raise ValueError(f"chain step {step!r} must be 'run <chunk>', 'goto <chunk>' or 'park'")
                    segments.append(seg)
                    cursor = list(seg[-1])
                if release:
                    self.holding = False
                self.queue = chain_path(segments, self.fps)
                self.chunk = " ; ".join(" ".join(s) for s in parts)
                self.settle_since, self.played, self.contact_ticks, self.contact_start = None, [], 0, None
                return True
            elif verb == "grip" and len(words) == 2:
                # never below the taught closed value: past the jaws' stop the gripper only pushes at its PWM
                # cap, and the guard's teacher mode does not bound the gripper (2026-10-25: 40 asked, stuck at 48.4)
                to = max(float(self.library["gripper_closed"]), min(100.0, float(words[1])))
                if to > self.target[5]:
                    self.holding = False
                present = self.present() if to < self.target[5] else None
                free = present is not None and abs(present[5] - self.target[5]) <= EMPTY_MARGIN  # not holding
                self.grip_from, self.target[5] = (self.target[5] if free else None), to  # reopen point
            elif verb == "retreat" and len(words) == 1:
                if not self.retreat_frames:
                    raise ValueError("nothing to retreat along")
                self.queue, self.retreat_frames = self.retreat_frames, []
                self.chunk, self.settle_since, self.played = "retreat", None, []
                return True
            elif verb == "load" and len(words) == 2:
                # a new plan (cell_pipeline: the box was found elsewhere) without ending the session and
                # folding the arm; the held target stays, and the library is checked before it replaces the old one
                try:
                    library = load_library(Path(words[1]))
                except (SystemExit, OSError) as exc:  # a missing file ended the whole session (2026-10-27)
                    raise ValueError(str(exc)) from None
                if library["fps"] != self.fps:
                    raise ValueError(f"library fps {library['fps']} differs from the runner fps {self.fps}")
                lib_digest = digest(library)
                if expected_library is not None and lib_digest != expected_library:
                    raise ValueError("checked load content differs from the reviewed library")
                self.plan_check(library)  # raises: a plan the arm's own load data says it cannot hold is refused here
                self.library = library
                self._lib_digest_cache = (id(library), lib_digest)
            elif verb != "state":
                raise ValueError("commands: run <chunk> [rel] | jog <joint> <delta> [...] | grip <value> | goto <chunk> | load <library> | park | state | stop")
            self.report(command=line, ok=True, present=locals().get("present"))
        except ValueError as error:
            self.report(command=line, ok=False, error=str(error), present=locals().get("present"))
        return True

    def hold(self, present, reason) -> None:
        """Stop where the arm is with torque on (the lag closes) and keep the way back for `retreat`."""
        chunk, jogging = self.chunk, bool(self.jog_path)
        self.queue, self.retreat_frames = [], (self.played or self.jog_path[:-1])[::-1]  # a jog's own target pushed
        self.target = list(present[:5]) + [self.target[5]]
        self.fault, self.holding = reason, bool(self.holding and present[5] > self.target[5] + EMPTY_MARGIN)
        self.chunk, self.played, self.jog_path = None, [], []
        if chunk == "park":
            self.last_input = self.clock()  # an idle fold's retry waits idle_retry_s from the hold, not from its start
        self.report(command=f"run {chunk or 'jog'}" if chunk or jogging else "fault", ok=False, error=self.fault, contact=True, present=present)

    def strained(self, sent, present):
        return runner_strain.strained(self, sent, present)

    def tick(self) -> None:
        pace_lag, pace_rise = (prm.get(self.params, "runner.pace_lag", _cr_attr("PACE_LAG", PACE_LAG)),
                            prm.get(self.params, "runner.pace_rise", _cr_attr("PACE_RISE", PACE_RISE)))
        if self.lag < pace_lag:
            self.pace_floor = 0.0
        shrinking = self.pace_last is None or self.lag < self.pace_last - 0.01
        if (self.queue and self.lag > max(pace_lag, self.pace_floor + pace_rise) and shrinking
                and self.paced < prm.get(self.params, "runner.pace_max_s", PACE_MAX_S) * self.fps):
            self.paced, self.paced_ticks, self.pace_last = self.paced + 1, self.paced_ticks + 1, self.lag
        elif self.queue:
            if self.pace_last is not None:  # the hold ended: what is left is this pose's droop
                self.pace_floor = max(self.pace_floor, self.lag)
            self.target, self.paced, self.pace_last = self.queue.pop(0), 0, None
            if self.chunk is not None:
                self.played.append(list(self.target))
        self.trend = [] if self.chunk is None and not self.jog_path else self.trend
        sent = self.robot.send_action(dict(zip(NAMES, self.target)))
        present = self.present()
        if self.trace:  # load: the 1 Hz health reading, once, on the tick after it (cell_why: what a stop pressed with)
            full, load = isinstance(sent, dict) and all(n in sent for n in NAMES), self.__dict__.pop("load_new", None)
            self.trace({"t": round(self.clock(), 4), "chunk": self.chunk, "target": [round(v, 3) for v in self.target],
                        "sent": [round(float(sent[n]), 3) for n in NAMES] if full else None, "present": [round(v, 3) for v in present],
                        "pwm": getattr(getattr(self.robot, "motion", None), "effort_pwm", None) or {}, **({"load": load} if load else {})})
        self.recorder.tick(present, [sent.get(n, t) if isinstance(sent, dict) else t for n, t in zip(NAMES, self.target)])
        if isinstance(sent, dict):
            self.lag = max((abs(present[i] - sent[name]) for i, name in enumerate(NAMES[:5]) if name in sent),
                           default=0.0)
            if self.chunk is not None:
                self.peak_lag, self.over_ticks = max(self.peak_lag, self.lag), self.over_ticks + (self.lag > CONTACT_LAG)
        motion = getattr(self.robot, "motion", None)
        held = getattr(motion, "held", None) or {}
        if held:  # the guard froze an overloaded joint (2026-11-09): stop pushing, shed its load
            if not (self.fault or "").startswith("contact"):
                self.hold(present, f"contact (overload-hold on {', '.join(held)} by the guard): lift and elbow shed its load")
            self.retreat_frames = []  # the way back puts the load back on: park once the guard lets go
            home = self.library["chunks"].get("home")
            if home:
                self.target = runner_strain.shed(self.target, present, sent if isinstance(sent, dict) else {}, home[-1], 0.5 * GUARD_UNITS_PER_S / self.fps)
            runner_strain.release_when_clear(self, motion, held, self.clock())
            return
        if (isinstance(sent, dict) and not self.fault and self.chunk is not None
                and self.chunk.startswith(CONTACT_CHUNKS)):
            lags = [abs(present[i] - sent[name]) if name in sent else 0.0 for i, name in enumerate(NAMES[:5])]
            if self.contact_start is None:
                self.contact_start = contact_limits(lags, self.params)
            lag = max(lags)
            over = any(v > limit for v, limit in zip(lags, self.contact_start))
            self.contact_ticks = self.contact_ticks + 1 if over else 0
            if self.contact_ticks >= prm.get(self.params, "runner.contact_ticks", CONTACT_TICKS):
                self.hold(present, f"contact in {self.chunk}: a joint lagged the command by {lag:.1f} units")
        elif isinstance(sent, dict) and (not self.fault or self.chunk == "park") and (self.chunk is not None or self.jog_path):
            # a fold out of a hold watches too (2026-11-03), and jogs: arm_a dropped at the guard's cut on a jog path (11-09)
            strain = self.strained(sent, present)
            if strain:  # named a contact: the judge may retreat or jog, and park clears it
                motor, lag, pwm, limit = strain
                others = ", ".join(f"{n} {abs(present[i] - sent[f'{n}.pos']):.1f}" for i, n in enumerate(MOTORS[:5])
                                   if n != motor and f"{n}.pos" in sent)  # a joint lagging with it points outside
                self.hold(present, f"contact in {self.chunk or 'jog'}: {motor} lag rose to {lag:.1f} units at PWM {pwm} of {limit}"
                                   f" (lags: {others})")
                return
        error = max(abs(a - b) for a, b in zip(present[:5], self.target[:5]))
        # Load-bearing joints only: the taught wrist roll lagged its leader by 66 units (2026-10-24 teach r2).
        loaded = max(abs(a - b) for a, b in zip(present[:4], self.target[:4]))
        now = self.clock()
        self.ticks += 1
        fresh = self.ticks % max(1, round(self.fps * HEALTH_PERIOD_S)) == 0
        if fresh:
            self.health = self.load_new = self.read_health()
        if self.health and fresh and not self.fault:
            hot = max(self.health["temp_c"])
            moved = self.health_present or present
            stalled = [i for i in range(4) if abs(self.health["pwm"][i]) >= PWM_STOP
                       and abs(self.target[i] - present[i]) > STALL_GAP and abs(present[i] - moved[i]) < STALL_MOVE]
            self.health_present = present
            pushing = max((abs(self.health["pwm"][i]) for i in stalled), default=0)
            if not stalled:
                self.overload_since = None
            elif self.overload_since is None:
                self.overload_since = now
            reason = (f"temperature {hot} C" if hot >= TEMP_STOP else
                      f"load-bearing joint stalled at PWM {pushing} for {PWM_STOP_S} s"
                      if self.overload_since is not None and now - self.overload_since >= PWM_STOP_S else None)
            if reason:  # stop pushing where the arm is; the judge may only park or stop
                self.fault, self.queue, self.target = reason, [], present[:5] + [self.target[5]]
                chunk, self.chunk = self.chunk, None
                self.report(command=f"run {chunk}" if chunk else "fault", ok=False, error=reason, present=present)
                return
            self.samples = (self.samples + [(list(self.target), present, self.health["pwm"])])[-4:]
            push = joint_push.pushing(self.samples, getattr(getattr(self.robot, "motion", None), "pwm_limits", None),
                                      (self.chunk == "park" and not self.holding) or self.grip_from is not None, self.params)
            if push and push[0] == "gripper" and self.chunk is None:  # a closing grip caught something: let it go
                self.target[5], self.grip_from = self.grip_from, None
                return self.report(command="grip", ok=False, caught=True, error=f"{push[1]}; reopened", present=present)
            if push and self.chunk is not None:
                return self.hold(present, f"contact in {self.chunk}: {push[1]}")
            if push:  # at rest: stop the wind-up where the arm is; folded home, idle() ends the session (torque OFF)
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
            body_still = (self.last_body is not None
                          and max(abs(a - b) for a, b in zip(present[:5], self.last_body)) < 0.08
                          and error <= SETTLE_TOL + min(self.pace_floor, 0.8))
            self.last_body = list(present[:5])
            settled = error <= SETTLE_TOL or body_still
            if (settled and (gripper_still or not grasp)) or now - self.settle_since >= SETTLE_S:
                fields = dict(command=f"run {self.chunk}", ok=True, settled=settled,
                              paced_ticks=self.paced_ticks, peak_lag=round(self.peak_lag, 2), over_ticks=self.over_ticks)
                self.paced_ticks, self.pace_floor, self.peak_lag, self.over_ticks = 0, 0.0, 0.0, 0
                if (self.chunk == "park" or self.chunk.endswith("; park")) and settled:  # torque goes OFF from here: only when really home
                    self.home_since = now
                backed_out = self.chunk == "retreat" and settled
                if (self.chunk == "park" or self.chunk.endswith("; park") or backed_out) and (self.fault or "").startswith("contact"):
                    # folded home, or back where the held chunk began: the next attempt may start. A touch grid
                    # otherwise parks between every point (2026-10-27).
                    self.fault = None
                if grasp:  # jaws stopped short of this chunk's closed target: something is between them
                    by_position = present[5] > self.target[5] + EMPTY_MARGIN
                    fields["holding"] = by_position
                    health = self.read_health()  # the jaws just stopped: the 1 s sample may predate it
                    if health:
                        self.health = health
                        current = abs(health["current_ma"][5])
                        fields["gripper_current_ma"] = current
                        threshold = self.library.get("hold_current_ma")
                        if threshold is not None:  # both must agree once the cell has a measured threshold
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
            if self.idle_parks >= 2:  # both folds held: dropping the arm is worse than holding it
                if self.idle_parks == 2:
                    self.idle_parks, self.fault = 3, f"idle fold held twice ({self.fault}): a person must free the arm"
                    self.report(command="park", ok=False, error=self.fault, person_needed=True)
                return False
            wait = (prm.get(self.params, "runner.idle_retry_s", IDLE_RETRY_S) if self.idle_parks else
                    prm.get(self.params, "runner.idle_park_s", IDLE_PARK_S))
            if quiet >= wait:
                self.last_input = self.clock()  # the stop's quiet time starts once the arm is folded
                self.idle_parks += 1
                self.command("park")
            return False
        pushed = (self.fault or "").startswith("pushing at rest")
        if pushed or min(quiet, self.clock() - self.home_since) >= prm.get(self.params, "runner.idle_stop_s", IDLE_STOP_S):
            self.report(command="stop", ok=True, reason=f"{self.fault if pushed else f'no command for {quiet:.0f} s'}"
                                                        "; folded home, torque goes OFF")
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
            # one motion command per tick: a burst of jogs must not move the target by more than one jog at once;
            # read-only state/episode queries ahead of a non-state command do not consume the motion slot
            while (len(self.pending) > 1
                   and self.pending[0].strip().split()[:1] in (["state"], ["episode"])
                   and self.pending[1].strip().split()[:1] != ["state"]):
                if not self.command(self.pending.pop(0)):
                    return
            if self.pending and not self.command(self.pending.pop(0)):
                return
            try:
                self.tick()
            except Exception as error:
                # a guard stop or a bus error ends the session; without this row the caller waited 300 s for a
                # status that never came (2026-10-25..27). No bus read here: after a bus error it would raise again
                self.status({"command": f"run {self.chunk}" if self.chunk else "tick", "ok": False,
                             # 1000: the guard's alignment stop ends with command={...}, which software_stop reads (cut at 300, 11-09)
                             "fault": f"session ended: {type(error).__name__}: {error}"[:1000], "t": round(time.time(), 3)})
                raise
            if self.idle():
                return
            if self.live and self.ticks % max(1, self.fps // 10) == 0:
                self.live({"t": round(time.time(), 3), "state": [round(v, 2) for v in (getattr(self, "last_present", None) or self.present())],
                           "target": [round(v, 2) for v in self.target], "chunk": self.chunk,
                           "lag": round(self.lag, 2),
                           "fault": self.fault, "health": self.health})
            self.sleep(max(0.0, period - (self.clock() - started)))


