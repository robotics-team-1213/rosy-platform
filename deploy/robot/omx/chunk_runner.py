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
  stop                    end; torque goes OFF where the arm is, so park (or run home) first

Commands apply one per control tick, and a jog may not put its target more than JOG_MAX + SETTLE_TOL
from the joint's present position, so a burst of commands cannot add up to one large step.

A grasp chunk (name starting with "grasp") reports `holding`: false when the gripper closed to within
EMPTY_MARGIN of the library's closed value, i.e. there was nothing between the jaws. The run stops by
itself on a read failure or a following error above FOLLOW_STOP for FOLLOW_STOP_S.

Launched by record_session.py --chunks; never on its own (the session owns caps and cleanup).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import select
import stat
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # teach_trajectory, guarded_native, motor_health
from teach_trajectory import GUARD_UNITS_PER_S, too_fast  # noqa: E402
from motion_profile import smooth  # noqa: E402

NAMES = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos",
         "gripper.pos"]
JOG_MAX = 5.0
FOLLOW_STOP, FOLLOW_STOP_S = 25.0, 1.0   # body joints, LeRobot units; the clip alone keeps steps small
SETTLE_TOL, SETTLE_S = 3.0, 3.0
EMPTY_MARGIN = 2.0
REL_MAX = 20.0  # largest body-joint correction a relative chunk may carry
# park: lift/elbow/wrist of the taught carry (high and clear) and a slow, even speed. Turning low first
# scraped the jaws on the table on 2026-10-24.
TRANSIT = {1: -27.0, 2: 18.0, 3: 46.0}
PARK_SPEED = GUARD_UNITS_PER_S  # units per second for every joint: what the guard's teacher mode streams
# Motor health (Present_PWM / Present_Current / Present_Temperature, raw): read once per HEALTH_PERIOD_S, and
# fresh for a grasp verdict. The guard already samples PWM about 5 times a second on the same bus; reading
# these three every 3 ticks as well doubled the traffic, and on 2026-10-25 a bus read stalled the loop past
# the guard's 0.5 s sample bound while the arm held over the box, so the guard turned torque off.
HEALTH_PERIOD_S = 1.0
# Soft contact: during a chunk that can touch something (descend, grasp, release), a body joint that lags the
# command the guard actually sent by CONTACT_LAG units for CONTACT_TICKS ticks is pressing on something.
# The runner holds where it is, with torque on, before the guard's 5 degree bound turns torque off and the
# extended arm drops (three times on 2026-10-25). A body unit is at most 1.8 degrees: 1.5 units <= 2.7.
CONTACT_LAG, CONTACT_TICKS = 1.5, 2
CONTACT_CHUNKS = ("descend", "grasp", "release")
# Stalled = pushing at its session cap (300) while short of its target and not moving: blocked or colliding.
# At the cap alone is normal: the elbow saturates while lifting the arm out of home (2026-10-25).
PWM_STOP, PWM_STOP_S, STALL_GAP, STALL_MOVE = 285, 0.5, 4.0, 0.3
TEMP_STOP = 65                    # degrees C; the motors' own limits are 70-72
MOTORS = [n.split(".")[0] for n in ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos",
                                    "wrist_roll.pos", "gripper.pos"]]


def transit_path(start: list, goal: list, grip_transit: float, fps: int, transit: dict | None = None) -> list:
    """From anywhere to `goal` without sweeping low: jaws to `grip_transit`, rise to the transit height,
    turn pan/roll to the goal there, descend into the goal body pose, then set the goal's jaws.
    `transit` maps joint indexes to values (a cell profile's transit); default TRANSIT (arm S)."""
    transit = TRANSIT if transit is None else transit
    waypoints = [list(start)]
    waypoints.append(waypoints[-1][:5] + [grip_transit])
    waypoints.append([transit.get(i, v) for i, v in enumerate(waypoints[-1])])
    waypoints.append([goal[i] if i in (0, 4) else v for i, v in enumerate(waypoints[-1])])
    waypoints.append(list(goal[:5]) + [grip_transit])
    waypoints.append(list(goal[:6]))
    # One flowing move: the turn starts as the rise ends and the descent as the turn ends (blended corners);
    # the jaws' changes and the goal are reached at rest. 85 % of the guard speed leaves room for the moment
    # two blended segments overlap on one joint.
    # The overlap is capped at 0.6 s: the rise has at most 0.5 * 5 * 0.6^2 = 0.9 units left when the turn begins.
    return smooth(waypoints, fps, 0.85 * PARK_SPEED, blend=[False, False, True, True, False, False], blend_s=0.6)


def park_path(start: list, home: list, closed: float, fps: int, transit: dict | None = None) -> list:
    """Close the jaws, rise, turn at that height, then descend into home (jaws stay closed)."""
    return transit_path(start, list(home[:5]) + [closed], closed, fps, transit)


SCHEMA = "rosy.omx-chunk-library.v1"


def load_library(path: Path) -> dict:
    library = json.loads(Path(path).read_text())
    if library.get("schema") != SCHEMA or library.get("names") != NAMES:
        raise SystemExit(f"chunk library needs schema {SCHEMA} and the six follower names")
    if not isinstance(library.get("fps"), int) or library["fps"] <= 0:
        raise SystemExit("chunk library needs its fps")
    chunks = library.get("chunks")
    if not isinstance(chunks, dict) or not chunks:
        raise SystemExit("chunk library has no chunks")
    for name, frames in chunks.items():
        if not frames or any(len(f) != 6 or not all(isinstance(v, (int, float)) and math.isfinite(v)
                                                    and -100 <= v <= 100 for v in f) for f in frames):
            raise SystemExit(f"chunk {name}: frames must be six finite values within -100..100")
        if too_fast(frames, library["fps"]):
            raise SystemExit(f"chunk {name}: frames move faster than the guard streams ({GUARD_UNITS_PER_S} units/s); "
                             "regenerate the library with grasp_planner.py or teach_trajectory.py")
    if not isinstance(library.get("gripper_closed"), (int, float)):
        raise SystemExit("chunk library needs gripper_closed (the taught fully closed value)")
    return library


class Runner:
    def __init__(self, robot, library: dict, *, fps: int, status, clock=time.monotonic, sleep=time.sleep,
                 live=None):
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
        self.played, self.retreat_frames, self.contact_ticks = [], [], 0
        self.live = live  # called about twice a second with the current state (Fleet observation bridge)
        self.health_present = None

    def present(self) -> list:
        observation = self.robot.get_observation()
        return [float(observation[name]) for name in NAMES]

    def report(self, **fields) -> None:
        self.status(dict(fields, state=[round(v, 2) for v in self.present()],
                         target=[round(v, 2) for v in self.target], health=self.health, fault=self.fault,
                         t=round(time.time(), 3)))

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
        try:
            if verb == "stop":
                self.report(command=line, ok=True)
                return False
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
                self.queue = transit_path(self.target, frames[0], self.library["gripper_closed"], self.fps, transit)
                self.chunk, self.settle_since = f"goto {words[1]}", None
                return True
            elif verb == "park" and len(words) == 1:
                home = self.library["chunks"].get("home")
                if not home:
                    raise ValueError("park needs a home chunk in the library")
                transit = {NAMES.index(k): float(v) for k, v in self.library.get("transit", {}).items()} or None
                self.queue = park_path(self.target, home[-1], self.library["gripper_closed"], self.fps, transit)
                self.chunk, self.settle_since = "park", None
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
                except SystemExit as exc:
                    raise ValueError(str(exc)) from None
                if library["fps"] != self.fps:
                    raise ValueError(f"library fps {library['fps']} differs from the runner fps {self.fps}")
                self.library = library
            elif verb != "state":
                raise ValueError("commands: run <chunk> [rel] | jog <joint> <delta> [...] | grip <value> | goto <chunk> | load <library> | park | state | stop")
            self.report(command=line, ok=True)
        except ValueError as error:
            self.report(command=line, ok=False, error=str(error))
        return True

    def tick(self) -> None:
        if self.queue:
            self.target = self.queue.pop(0)
            if self.chunk is not None:
                self.played.append(list(self.target))
        sent = self.robot.send_action(dict(zip(NAMES, self.target)))
        present = self.present()
        if (isinstance(sent, dict) and not self.fault and self.chunk is not None
                and self.chunk.startswith(CONTACT_CHUNKS)):
            lag = max((abs(present[i] - sent[name]) for i, name in enumerate(NAMES[:5]) if name in sent), default=0.0)
            self.contact_ticks = self.contact_ticks + 1 if lag > CONTACT_LAG else 0
            if self.contact_ticks >= CONTACT_TICKS:
                chunk = self.chunk
                self.queue, self.retreat_frames = [], self.played[::-1]
                self.target = list(present[:5]) + [self.target[5]]  # hold here: the lag closes, torque stays on
                self.fault = f"contact in {chunk}: a joint lagged the command by {lag:.1f} units"
                self.chunk, self.played = None, []
                self.report(command=f"run {chunk}", ok=False, error=self.fault, contact=True)
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
                fields = dict(command=f"run {self.chunk}", ok=True, settled=error <= SETTLE_TOL)
                if self.chunk == "park" and (self.fault or "").startswith("contact"):
                    self.fault = None  # folded home after a soft contact: the next attempt may start
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

    def run(self, lines) -> None:
        """`lines()` returns the commands that arrived since the last call."""
        self.target = self.present()
        self.report(command="start", ok=True)
        period = 1.0 / self.fps
        while True:
            started = self.clock()
            self.pending += lines()
            # one command per tick: a burst of jogs must not move the target by more than one jog at once
            if self.pending and not self.command(self.pending.pop(0)):
                return
            self.tick()
            if self.live and self.ticks % max(1, self.fps // 2) == 0:
                self.live({"t": round(time.time(), 3), "state": [round(v, 2) for v in self.present()],
                           "target": [round(v, 2) for v in self.target], "chunk": self.chunk,
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
    args = parser.parse_args(argv)
    library = load_library(args.library)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
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
        live_path = args.io / "live.json"

        def live(row):  # replaced atomically so a reader never sees half a file
            tmp = live_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(row))
            os.replace(tmp, live_path)

        Runner(guarded, library, fps=config["dataset"]["fps"], status=status, live=live).run(lines)
    finally:
        lines.close()
        try:
            close_device(robot)  # torque OFF before the bus closes
        finally:
            if motion.monitor is not None:
                motion.monitor.end()


if __name__ == "__main__":
    main()
