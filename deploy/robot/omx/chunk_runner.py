#!/usr/bin/env python3
"""Run taught motion chunks on the follower one at a time, holding torque between them (scripted teacher).

The follower is driven through the guard's teacher mode (guarded_native.py: passive connect, seeded
torque, 10 deg/s streaming, following-error, effort and fault stops) in LeRobot units at the recorder's
fps; chunk frames may not move faster than GUARD_UNITS_PER_S. Between chunks the last target is
held, so an extended arm never drops. A judge (an operator, an agent watching the cameras, later a
VLA) writes one command per line into the command FIFO and reads one JSON status per command:

  run <chunk> [rel]       play a chunk, then report the settled state; rel shifts its body joints by
                          the held correction (held target minus the chunk start, at most REL_MAX)
  jog <joint> <delta> ... move one or more joint targets together, each by at most JOG_MAX units
  grip <value>            set the gripper target
  state                   report the current state
  goto <chunk>            the same rise-turn-descend path to a chunk's start pose (recovery, re-approach)
  park                    close the jaws, rise, turn at that height and descend into home, slowly
  retreat                 after a contact hold, back out along the played path; settled at its start, the
                          contact is cleared like a park
  stop                    end; torque goes OFF where the arm is, so park (or run home) first

Commands apply one per control tick, and a jog may not put its target more than JOG_MAX + SETTLE_TOL
from the joint's present position, so a burst of commands cannot add up to one large step.

A grasp chunk (name starting with "grasp") reports `holding`: false when the gripper closed to within
EMPTY_MARGIN of the library's closed value, i.e. there was nothing between the jaws. The run stops by
itself on a read failure or a following error above FOLLOW_STOP for FOLLOW_STOP_S.

Outside descend/grasp/release a load-bearing joint whose lag keeps rising past STRAIN_LAG while it pushes
(PWM at STRAIN_PWM of its cap) holds the same way as a contact, before the guard's 5 degree bound drops the arm.
ROSY_CHUNK_TRACE=<file> appends one JSON line per tick (time, chunk, target, sent, present) to measure jitter.

Launched by record_session.py --chunks; never on its own (the session owns caps and cleanup).
"""
from __future__ import annotations

import argparse
import json
import os
import select
import stat
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # guarded_native, motor_health, cell_params, episode_recorder
from omx_adapter.chunk_library import (  # noqa: E402
    GUARD_UNITS_PER_S as GUARD_UNITS_PER_S,
    NAMES,
    PARK_SPEED as PARK_SPEED,
    RISE_SPEED as RISE_SPEED,
    SCHEMA as SCHEMA,
    TRANSIT as TRANSIT,
    load_library,
    park_path,
    too_fast as too_fast,
    transit_path,
)
from omx_adapter.motion_profile import GUARD_ACCEL_UNITS_S2 as GUARD_ACCEL_UNITS_S2, smooth as smooth  # noqa: E402
from cell_envelope import digest, runtime_context  # noqa: E402
import cell_params as prm  # noqa: E402
from episode_recorder import Recorder  # noqa: E402

JOG_MAX = 5.0
FOLLOW_STOP, FOLLOW_STOP_S = 25.0, 1.0   # body joints, LeRobot units; the clip alone keeps steps small
SETTLE_TOL, SETTLE_S = 3.0, 3.0
EMPTY_MARGIN = 2.0
REL_MAX = 20.0  # largest body-joint correction a relative chunk may carry
# Motor health (Present_PWM / Present_Current / Present_Temperature, raw): read once per HEALTH_PERIOD_S, and
# fresh for a grasp verdict. The guard already samples PWM about 5 times a second on the same bus; reading
# these three every 3 ticks as well doubled the traffic, and on 2026-10-25 a bus read stalled the loop past
# the guard's 0.5 s sample bound while the arm held over the box, so the guard turned torque off.
HEALTH_PERIOD_S = 1.0
# Soft contact: during a chunk that can touch something (descend, grasp, release), a body joint that lags the
# command the guard actually sent by CONTACT_LAG units for CONTACT_TICKS ticks is pressing on something.
# The runner holds where it is, with torque on, before the guard's 5 degree bound turns torque off and the
# extended arm drops (three times on 2026-10-25). A body unit is at most 1.8 degrees: 1.5 units <= 2.7.
CONTACT_LAG, CONTACT_TICKS = prm.default("runner.contact_lag"), prm.default("runner.contact_ticks")


def contact_limits(start_lags: list, params=None) -> list:
    """Per joint: the old limit, raised only for a joint that starts the chunk already loaded (a held box left the
    elbow 1.5-2.0 behind, 2026-10-28), and then only to start + contact_rise, never past contact_loaded_max (well under
    the guard's ~2.8 units). An unloaded joint keeps exactly the old limit: raising every joint toward the guard let a
    descent press until the guard dropped the arm (incident 2026-10-28 23:59)."""
    base = prm.get(params, "runner.contact_lag", CONTACT_LAG)
    rise, top = prm.get(params, "runner.contact_rise"), prm.get(params, "runner.contact_loaded_max")
    return [max(base, min(s + rise, top)) for s in start_lags]
CONTACT_CHUNKS = ("descend", "grasp", "release")
# Pacing: a body joint behind the guard's sent command by PACE_LAG units holds the next frame until it catches
# up. On arm S the wrist_flex (XL330) gives ~35 PWM per degree, so a lift or goto grew its lag 0.2 -> 2.6 -> 5
# degrees at PWM 135-165 of 300 and the guard turned torque off (12 sessions, 2026-10-25..27). 1.6 units is 2.9
# degrees of the guard's 5. A hold lasts only while the lag shrinks: reached over the conveyor, the wrist sat
# 2.08 units low with no motion at all (2026-10-28), and waiting for 1.6 there moved one frame per PACE_MAX_S.
# Where the lag stops shrinking it is the pose's droop (`pace_floor`); frames go on, and hold again only when the
# lag grows PACE_RISE past it. Contact chunks reach CONTACT_LAG first and keep their contact response.
PACE_LAG, PACE_RISE, PACE_MAX_S = (prm.default(f"runner.{k}") for k in ("pace_lag", "pace_rise", "pace_max_s"))
# Nobody sent a command for IDLE_PARK_S (a lost link, a crashed caller): fold home. IDLE_STOP_S more at home ends
# the session, so record_session turns torque OFF and the motors rest instead of holding for hours (a session
# held home 6 h on 2026-10-27/28 until its health log ran out). A caller that wants the arm held sends `state`.
IDLE_PARK_S, IDLE_STOP_S = prm.default("runner.idle_park_s"), prm.default("runner.idle_stop_s")
# Strain, in every other chunk (goto, park, lift): normal travel lags up to about 2.6 units, so CONTACT_LAG would
# hold there. A shoulder lifting from a reach (2026-10-27) went 2.4 -> 3.1 -> 4.0 -> 4.7 deg at PWM 263 -> 516 of
# 600 in 0.7 s before the guard's 5 degree stop; a wrist against the wall 2.6 -> 3.6 -> 4.7 deg at PWM 93 -> 165
# of 300. Hold when a load-bearing joint lags STRAIN_LAG units (3.1 deg), its lag rose by STRAIN_RISE over the
# last STRAIN_TICKS ticks and the guard's last PWM sample (5 Hz) is at STRAIN_PWM of its cap. Holding needs room:
# the guard brakes at 10 deg/s^2, so its command still runs v^2/20 deg on (1.5 deg at RISE_SPEED).
# STRAIN_PWM 0.35 held a normal park out of a sagged reach (lag 1.8 at 263 of 600 = 44 %, 2026-10-27); the
# real strains were at 55-86 %.
# STRAIN_LAG 1.7 held every rise out of the container reach (2026-10-27): lifting the extended arm takes 400-500
# PWM, and P x error builds that only near 1.7-1.9 units, at P 1200 and 1600 alike. At RISE_SPEED 2 the guard
# runs on v^2/20 = 0.65 deg after a hold, so holding at 2.2 units (4.0 deg) still stops short of 5.
STRAIN_LAG, STRAIN_RISE, STRAIN_TICKS, STRAIN_PWM = 2.2, 0.25, 6, 0.5
# Stalled = pushing at its session cap (300) while short of its target and not moving: blocked or colliding.
# At the cap alone is normal: the elbow saturates while lifting the arm out of home (2026-10-25).
PWM_STOP, PWM_STOP_S, STALL_GAP, STALL_MOVE = 285, 0.5, 4.0, 0.3
TEMP_STOP = 65                    # degrees C; the motors' own limits are 70-72
MOTORS = [n.split(".")[0] for n in ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos",
                                    "wrist_roll.pos", "gripper.pos"]]


class Runner:
    def __init__(self, robot, library: dict, *, fps: int, status, clock=time.monotonic, sleep=time.sleep,
                 live=None, operating_context=None, params=None):
        self.params = params  # cell_params values (None = the constants above)
        self.robot, self.library, self.fps, self.status = robot, library, fps, status
        self.clock, self.sleep = clock, sleep
        self.target = None
        self.queue: list = []
        self.chunk = None
        self.settle_since = None
        self.far_since = None
        self.last_grip = None
        self.pending: list = []
        self.ticks, self.health, self.overload_since, self.fault = 0, None, None, None
        self.played, self.retreat_frames, self.contact_ticks, self.contact_start = [], [], 0, None
        self.lag, self.paced, self.paced_ticks = 0.0, 0, 0  # paced_ticks: frames held in the current chunk
        self.pace_floor, self.pace_last = 0.0, None
        self.last_input, self.home_since = 0.0, None  # home_since: a park settled and nothing moved since
        # per chunk: the largest lag behind the command the guard sent, and the ticks it spent over CONTACT_LAG;
        # the contact margin a real run leaves, which live.json's chunk target does not show (2026-10-26)
        self.peak_lag, self.over_ticks = 0.0, 0
        self.live = live  # called about twice a second with the current state (Fleet observation bridge)
        self.health_present = None
        self.recorder = Recorder()  # raw training episodes: rows here, encoding after the session
        self.operating_context = operating_context
        self.trend: list = []  # load-bearing joints' lags over the last STRAIN_TICKS ticks of a chunk
        self.trace = None      # called every tick with what was commanded and where the arm was (jitter)

    def present(self) -> list:
        observation = self.robot.get_observation()
        return [float(observation[name]) for name in NAMES]

    def report(self, **fields) -> None:
        self.status(dict(fields, state=[round(v, 2) for v in self.present()],
                         target=[round(v, 2) for v in self.target], health=self.health, fault=self.fault,
                         operating_context=self.operating_context, library_sha256=digest(self.library),
                         t=time.time()))

    def read_health(self):
        """Temperature, PWM and current of every motor, or None when the robot exposes no bus (tests)."""
        bus = getattr(self.robot, "bus", None)
        if bus is None:
            return None
        def signed(v):
            return int(v) - 65536 if int(v) > 32767 else int(v)
        pwm, current, temp = (bus.sync_read(name) for name in ("Present_PWM", "Present_Current", "Present_Temperature"))
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
                if verb != "load" and digest(self.library) != expected_library:
                    raise ValueError("checked command targets another library")
            if verb == "stop":
                self.report(command=line, ok=True)
                return False
            if verb == "episode":  # bookkeeping only: allowed between chunks and after a fault (to drop the episode)
                self.report(command=line, ok=True, **self.recorder.command(words[1:]))
                return True
            if self.chunk is not None:
                raise ValueError(f"chunk {self.chunk} is still running")
            soft = (self.fault or "").startswith("contact")
            if self.fault and verb not in ("park", "state") and not (soft and verb in ("retreat", "jog")):
                raise ValueError(f"fault ({self.fault}): only park, state or stop"
                                 + (", or retreat/jog after a contact" if soft else ""))
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
                self.target = moved
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
            elif verb == "grip" and len(words) == 2:
                # never below the taught closed value: past the jaws' stop the gripper only pushes at its PWM
                # cap, and the guard's teacher mode does not bound the gripper (2026-10-25: 40 asked, stuck at 48.4)
                self.target[5] = max(float(self.library["gripper_closed"]), min(100.0, float(words[1])))
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
                if expected_library is not None and digest(library) != expected_library:
                    raise ValueError("checked load content differs from the reviewed library")
                self.library = library
            elif verb != "state":
                raise ValueError("commands: run <chunk> [rel] | jog <joint> <delta> [...] | grip <value> | goto <chunk> | load <library> | park | state | stop")
            self.report(command=line, ok=True)
        except ValueError as error:
            self.report(command=line, ok=False, error=str(error))
        return True

    def hold(self, present, reason) -> None:
        """Stop where the arm is with torque on (the lag closes) and keep the way back for `retreat`."""
        chunk = self.chunk
        self.queue, self.retreat_frames = [], self.played[::-1]
        self.target = list(present[:5]) + [self.target[5]]
        self.fault = reason
        self.chunk, self.played = None, []
        self.report(command=f"run {chunk}", ok=False, error=self.fault, contact=True)

    def strained(self, sent, present):
        """(motor, lag, pwm, cap) of a load-bearing joint whose lag keeps rising while it pushes, or None."""
        lags = [abs(present[i] - sent[n]) if n in sent else 0.0 for i, n in enumerate(NAMES[:4])]
        self.trend = (self.trend + [lags])[-(STRAIN_TICKS + 1):]
        if len(self.trend) <= STRAIN_TICKS:
            return None
        motion = getattr(self.robot, "motion", None)  # the guard's own PWM sample: no extra bus read
        pwm, limits = getattr(motion, "effort_pwm", None) or {}, getattr(motion, "pwm_limits", None) or {}
        first, middle = self.trend[0], self.trend[STRAIN_TICKS // 2]
        for i, motor in enumerate(MOTORS[:4]):
            rising = first[i] < middle[i] < lags[i] and lags[i] - first[i] >= STRAIN_RISE
            pushing = motor not in pwm or motor not in limits or abs(pwm[motor]) >= STRAIN_PWM * limits[motor]
            if lags[i] >= STRAIN_LAG and rising and pushing:
                return motor, lags[i], pwm.get(motor), limits.get(motor)
        return None

    def tick(self) -> None:
        pace_lag, pace_rise = prm.get(self.params, "runner.pace_lag", PACE_LAG), prm.get(self.params, "runner.pace_rise", PACE_RISE)
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
        if self.chunk is None:
            self.trend = []
        sent = self.robot.send_action(dict(zip(NAMES, self.target)))
        present = self.present()
        if self.trace:
            full = isinstance(sent, dict) and all(n in sent for n in NAMES)
            self.trace({"t": round(self.clock(), 4), "chunk": self.chunk, "target": [round(v, 3) for v in self.target],
                        "sent": [round(float(sent[n]), 3) for n in NAMES] if full else None,
                        "present": [round(v, 3) for v in present]})
        self.recorder.tick(present, [sent.get(n, t) if isinstance(sent, dict) else t for n, t in zip(NAMES, self.target)])
        if isinstance(sent, dict):
            self.lag = max((abs(present[i] - sent[name]) for i, name in enumerate(NAMES[:5]) if name in sent),
                           default=0.0)
            if self.chunk is not None:
                self.peak_lag, self.over_ticks = max(self.peak_lag, self.lag), self.over_ticks + (self.lag > CONTACT_LAG)
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
        elif isinstance(sent, dict) and not self.fault and self.chunk is not None:
            strain = self.strained(sent, present)
            if strain:  # named a contact: the judge may retreat or jog, and park clears it
                motor, lag, pwm, limit = strain
                self.hold(present, f"contact in {self.chunk}: {motor} lag rose to {lag:.1f} units at PWM {pwm} of {limit}")
                return
        error = max(abs(a - b) for a, b in zip(present[:5], self.target[:5]))
        # Load-bearing joints only: the taught wrist roll lagged its leader by 66 units (2026-10-24 teach r2).
        loaded = max(abs(a - b) for a, b in zip(present[:4], self.target[:4]))
        now = self.clock()
        self.ticks += 1
        fresh = self.ticks % max(1, round(self.fps * HEALTH_PERIOD_S)) == 0
        if fresh:
            self.health = self.read_health()
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
                self.report(command=f"run {chunk}" if chunk else "fault", ok=False, error=reason)
                return
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
            if (error <= SETTLE_TOL and (gripper_still or not grasp)) or now - self.settle_since >= SETTLE_S:
                fields = dict(command=f"run {self.chunk}", ok=True, settled=error <= SETTLE_TOL,
                              paced_ticks=self.paced_ticks, peak_lag=round(self.peak_lag, 2), over_ticks=self.over_ticks)
                self.paced_ticks, self.pace_floor, self.peak_lag, self.over_ticks = 0, 0.0, 0.0, 0
                if self.chunk == "park":
                    self.home_since = now
                backed_out = self.chunk == "retreat" and error <= SETTLE_TOL
                if (self.chunk == "park" or backed_out) and (self.fault or "").startswith("contact"):
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
                self.chunk, self.last_grip = None, None
                self.report(**fields)

    def idle(self) -> bool:
        """Fold home, then end the session (True), when no command has come for a while."""
        if self.chunk is not None or self.queue or self.pending:
            return False
        quiet = self.clock() - self.last_input
        if self.home_since is None and quiet >= prm.get(self.params, "runner.idle_park_s", IDLE_PARK_S):
            self.last_input = self.clock()  # the stop's quiet time starts once the arm is folded
            self.command("park")
            return False
        if self.home_since is not None and min(quiet, self.clock() - self.home_since) >= prm.get(self.params, "runner.idle_stop_s", IDLE_STOP_S):
            self.report(command="stop", ok=True, reason=f"no command for {quiet:.0f} s; folded home, torque goes OFF")
            return True
        return False

    def run(self, lines) -> None:
        """`lines()` returns the commands that arrived since the last call."""
        self.target = self.present()
        self.report(command="start", ok=True)
        period = 1.0 / self.fps
        self.last_input = self.clock()
        while True:
            started = self.clock()
            arrived = lines()
            if arrived:
                self.last_input = started
            self.pending += arrived
            # one command per tick: a burst of jogs must not move the target by more than one jog at once
            if self.pending and not self.command(self.pending.pop(0)):
                return
            try:
                self.tick()
            except Exception as error:
                # a guard stop or a bus error ends the session; without this row the caller waited 300 s for a
                # status that never came (2026-10-25..27). No bus read here: after a bus error it would raise again
                self.status({"command": f"run {self.chunk}" if self.chunk else "tick", "ok": False,
                             "fault": f"session ended: {type(error).__name__}: {error}"[:300], "t": round(time.time(), 3)})
                raise
            if self.idle():
                return
            if self.live and self.ticks % max(1, self.fps // 2) == 0:
                self.live({"t": round(time.time(), 3), "state": [round(v, 2) for v in self.present()],
                           "target": [round(v, 2) for v in self.target], "chunk": self.chunk,
                           "lag": round(self.lag, 2),
                           "fault": self.fault, "health": self.health})
            self.sleep(max(0.0, period - (self.clock() - started)))


class Guarded:
    """The follower as Runner sees it, with every action sent through the guard."""

    def __init__(self, robot, motion):
        self.robot, self.motion, self.bus = robot, motion, robot.bus

    def send_action(self, action):
        return self.motion.send(action)

    def get_observation(self):
        return self.robot.get_observation()


def fifo_lines(path: Path):
    if not path.exists():
        os.mkfifo(path, 0o600)
    if not stat.S_ISFIFO(os.stat(path).st_mode):  # a stale regular file would replay old commands
        raise SystemExit(f"{path} exists and is not a FIFO")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    keep = os.open(path, os.O_WRONLY | os.O_NONBLOCK)  # stays open so readers never see EOF between writers
    buffer = b""

    def lines():
        nonlocal buffer
        out = []
        while select.select([fd], [], [], 0)[0]:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            out.append(line.decode(errors="replace").strip())  # a bad byte is a refused command, not an exit
        return out

    lines.close = lambda: (os.close(fd), os.close(keep))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, type=Path, help="record config (robot section is used)")
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--io", required=True, type=Path, help="directory for chunk-cmd (FIFO) and chunk-status.jsonl")
    parser.add_argument("--operating-profile", type=Path, help="per-device operating profile; unbound sessions cannot auto-pick")
    parser.add_argument("--params", type=Path, help="cell-params.json (rosy.omx-cell-params.v1); default: the built-in values")
    args = parser.parse_args(argv)
    library = load_library(args.library)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    params = prm.load(args.params)["values"]
    from cell_robot_profile import load as load_operating_profile

    profile = load_operating_profile(args.operating_profile, robot_config=config["robot"]) if args.operating_profile else None
    if library.get("fps") != config["dataset"]["fps"]:  # one frame per tick: another fps replays at another speed
        raise SystemExit(f"chunk library fps {library.get('fps')} differs from the recorder fps {config['dataset']['fps']}")
    from lerobot.robots.omx_follower import OmxFollower, OmxFollowerConfig

    robot_cfg = {k: v for k, v in config["robot"].items() if k not in ("type", "cameras")}
    # LeRobot's ensure_safe_goal_position accepts only float/dict; draccus converts it for lerobot-record, JSON keeps 5 an int
    robot_cfg["max_relative_target"] = float(robot_cfg["max_relative_target"])
    robot = OmxFollower(OmxFollowerConfig(**robot_cfg, cameras={}))  # the camera services keep the cameras
    args.io.mkdir(parents=True, exist_ok=True)
    status_path = args.io / "chunk-status.jsonl"

    def status(row):
        with status_path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)

    from guarded_native import NativeJointMotion, close_device, connect_passive
    from motor_health import MotorHealth

    lines = fifo_lines(args.io / "chunk-cmd")
    # The guard owns the hardware lifecycle and every goal (D-872): passive connect (no vendor
    # configure), seeded torque ON, 10 deg/s streaming, following-error, effort and fault stops.
    connect_passive(robot, follower=True)
    motion = NativeJointMotion(robot.bus, None, teacher=True, monitor=MotorHealth())
    guarded = Guarded(robot, motion)
    try:
        import bus_watchdog  # the motors stop by themselves if this PC goes silent (off unless the params set it)

        print(json.dumps({"bus_watchdog": bus_watchdog.arm(robot.bus, prm.get(params, "safety.bus_watchdog_ms"))}), flush=True)
        live_path = args.io / "live.json"

        def live(row):  # replaced atomically so a reader never sees half a file
            tmp = live_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(row))
            os.replace(tmp, live_path)

        context = runtime_context(config["robot"], robot.bus, config["dataset"]["fps"],
                                  operating_profile=profile, params=params)
        runner = Runner(guarded, library, fps=config["dataset"]["fps"], status=status, live=live,
                        operating_context=context, params=params)
        trace_path = os.environ.get("ROSY_CHUNK_TRACE")
        trace_file = open(trace_path, "a") if trace_path else None  # buffered: no write call per tick
        if trace_file:
            runner.trace = lambda row: trace_file.write(json.dumps(row) + "\n")
        try:
            runner.run(lines)
        finally:
            if trace_file:
                trace_file.close()
    finally:
        lines.close()
        try:
            close_device(robot)  # torque OFF before the bus closes
        finally:
            if motion.monitor is not None:
                motion.monitor.end()


if __name__ == "__main__":
    main()
