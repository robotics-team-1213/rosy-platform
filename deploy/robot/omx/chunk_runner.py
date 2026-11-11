#!/usr/bin/env python3
"""Run taught motion chunks on the follower one at a time, holding torque between them (scripted teacher).

The follower is driven through the guard's teacher mode (guarded_native.py) in LeRobot units at the recorder's
fps, no faster than GUARD_UNITS_PER_S; between chunks the last target is held, so an extended arm never drops.
A judge writes one command per line into the command FIFO and reads one JSON status per command:

  run <chunk> [rel]       play a chunk, then report the settled state; rel shifts its body joints by
                          the held correction (held target minus the chunk start, at most REL_MAX)
  jog <joint> <delta> ... move one or more joint targets together, each by at most JOG_MAX units
  grip <value>            set the gripper target; a closing grip that catches something reopens (joint_push)
  state                   report the current state
  goto <chunk>            the same rise-turn-descend path to a chunk's start pose (recovery, re-approach)
  park                    close the jaws, rise, turn at that height and descend into home, slowly
  retreat                 after a contact hold, back out along the played path; settled at its start, the
                          contact is cleared like a park
  stop                    end; torque goes OFF where the arm is, so park (or run home) first

Commands apply one per tick, and a jog stays within JOG_MAX + SETTLE_TOL of the present position.

A grasp chunk reports `holding`: false when the jaws closed to within EMPTY_MARGIN of the closed value. The
run stops by itself on a read failure or a following error above FOLLOW_STOP for FOLLOW_STOP_S.

Elsewhere a joint whose lag rises past STRAIN_LAG at STRAIN_PWM of its cap holds like a contact (strained()).
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
_ADAPTER_SRC = str(Path(__file__).resolve().parents[3] / "middleware/devices/omx/adapter")
if _ADAPTER_SRC not in sys.path:
    sys.path.insert(0, _ADAPTER_SRC)
from omx_adapter.chunk_library import (  # noqa: E402
    GUARD_UNITS_PER_S as GUARD_UNITS_PER_S,
    NAMES,
    PARK_SPEED as PARK_SPEED,
    RISE_SPEED as RISE_SPEED,
    SCHEMA as SCHEMA,
    TRANSIT as TRANSIT,
    TemporalChunkEnsembler as TemporalChunkEnsembler,
    chain_path as chain_path,
    load_library,
    park_path,
    receding_horizon_splice as receding_horizon_splice,
    too_fast as too_fast,
    transit_path,
)
from omx_adapter.motion_profile import GUARD_ACCEL_UNITS_S2 as GUARD_ACCEL_UNITS_S2, smooth as smooth  # noqa: E402
from cell_envelope import digest, runtime_context  # noqa: E402
import cell_params as prm  # noqa: E402
from episode_recorder import Recorder  # noqa: E402
import joint_push, load_predict  # noqa: E402

JOG_MAX = 5.0
FOLLOW_STOP, FOLLOW_STOP_S = 25.0, 1.0   # body joints, LeRobot units; the clip alone keeps steps small
SETTLE_TOL, SETTLE_S, EMPTY_MARGIN = 3.0, 3.0, 2.0
REL_MAX = 20.0  # largest body-joint correction a relative chunk may carry
# Motor health (Present_PWM/Current/Temperature, raw): once per HEALTH_PERIOD_S, and fresh for a grasp verdict.
# The guard samples PWM ~5 Hz on the same bus; reading these every 3 ticks too doubled the traffic and on
# 2026-10-25 stalled the loop past the guard's 0.5 s sample bound over the box, so it turned torque off.
HEALTH_PERIOD_S = 1.0
# Soft contact: in a chunk that can touch something, a body joint CONTACT_LAG units (<= 2.7 deg) behind the sent
# command for CONTACT_TICKS ticks presses on something; hold with torque on before the guard's 5 degree bound
# turns torque off and the extended arm drops (three times on 2026-10-25).
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

# Pacing: a body joint PACE_LAG units (2.9 of the guard's 5 deg) behind the sent command holds the next frame
# until it catches up: arm S's XL330 wrist grew 0.2 -> 5 deg at PWM 135-165 of 300 and the guard cut torque (12 sessions,
# 2026-10-25..27). A hold lasts only while the lag shrinks; where it stops it is the pose's droop (`pace_floor`) and
# frames go on until the lag grows PACE_RISE past it. Contact chunks reach CONTACT_LAG first and keep their response.
PACE_LAG, PACE_RISE, PACE_MAX_S = (prm.default(f"runner.{k}") for k in ("pace_lag", "pace_rise", "pace_max_s"))
# Nobody sent a command for IDLE_PARK_S (a lost link, a crashed caller): fold home. IDLE_STOP_S more at home ends the
# session, so record_session turns torque OFF instead of holding for hours (6 h on 2026-10-27/28). `state` holds.
# A fold a hold stopped (a blocked joint) is tried once more after IDLE_RETRY_S; a second hold keeps the arm where it is.
IDLE_PARK_S, IDLE_STOP_S, IDLE_RETRY_S = (prm.default(f"runner.idle_{k}_s") for k in ("park", "stop", "retry"))
from runner_strain import (  # noqa: E402  the strain and shed holds, with their constants (tests read them here)
    ROLL_BLOCK_LAG as ROLL_BLOCK_LAG, STRAIN_LAG as STRAIN_LAG, STRAIN_PWM as STRAIN_PWM, STRAIN_RISE as STRAIN_RISE)
import runner_strain  # noqa: E402
TEMP_STOP = 65  # deg C; motors' own limits 70-72
# Stalled = at its cap, short of its target and still (the cap alone is normal: an elbow lifting out of home).
PWM_STOP, PWM_STOP_S, STALL_GAP, STALL_MOVE = 285, 0.5, 4.0, 0.3
MOTORS = [n.split(".")[0] for n in NAMES]


import chunk_runner_run as _crr  # noqa: E402
_crr._CR_DICT_LIST.append(globals())
Runner = _crr.Runner


class Guarded:
    """The follower as Runner sees it, with every action sent through the guard."""

    def __init__(self, robot, motion):
        self.robot, self.motion, self.bus = robot, motion, robot.bus

    def send_action(self, action):
        return self.motion.send(action)

    def get_observation(self):
        present = getattr(self.motion, "last_present", None)
        if present is not None:
            self.motion.last_present = None
            return present
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
    parser.add_argument("--load-model", type=Path, help="load-model.json (load_model.py): refuse a library whose holds are predicted risky")
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
    motion.shed_load = True  # a guard hold freezes only the held joint: runner_strain.shed moves lift and elbow
    guarded = Guarded(robot, motion)
    try:
        caps = (robot.bus.sync_read("PWM_Limit", list(load_predict.BODY[1:]), normalize=False, num_retry=2)
                if "read" not in vars(robot.bus) and hasattr(robot.bus, "model_ctrl_table")
                else {j: robot.bus.read("PWM_Limit", j) for j in load_predict.BODY[1:]}) if args.load_model else None
        check = load_predict.plan_check(args.load_model, robot_cfg.get("port"), params, library, caps) if args.load_model else None
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
                        operating_context=context, params=params, plan_check=check)
        trace_file = open(path, "a") if (path := os.environ.get("ROSY_CHUNK_TRACE")) else None  # buffered: no write call per tick
        if trace_file:
            runner.trace = __import__("cell_why").flushing_trace(trace_file)
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
