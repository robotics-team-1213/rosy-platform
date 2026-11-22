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
  human-hold              latch present pose with torque commanded ON; supervised recovery required

Commands apply one per tick, and a jog stays within JOG_MAX + SETTLE_TOL of the present position.

A grasp chunk reports `holding`: false when the jaws closed to within EMPTY_MARGIN of the closed value. The
run stops by itself on a read failure or a following error above FOLLOW_STOP for FOLLOW_STOP_S.

Elsewhere a joint whose lag rises past STRAIN_LAG at STRAIN_PWM of its cap holds like a contact (strained()).
ROSY_CHUNK_TRACE=<file> appends one JSON line per tick (time, chunk, target, sent, present) to measure jitter.

SIGINT/SIGTERM never cut torque with the arm out: the runner folds home and reads the fold back, then torque goes OFF;
a fold that cannot finish leaves a human hold (torque ON) until a person sends SIGUSR2 (chunk_runner_interrupt.py).
`gated_close` (final_gate, interrupts blocked through close_device) is the last word: an interrupt recorded without a confirmed fold or an approved
exception waits (nothing sent) for SIGUSR2, whichever path ended the run.

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
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # guarded_native, motor_health, cell_params, episode_recorder
if __name__ == "__main__":  # before any import that may start threads: interrupts reach the main thread only
    import main_thread_signals

    main_thread_signals.quiet_blas()  # one BLAS thread: the runner's per-tick math is a few 6-vectors
    main_thread_signals.route()
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

    def send_action_checked(self, action, goal_check, *, hold_on_read_error=False, allow_stale_hold=False):
        return self.motion.send(
            action, goal_check=goal_check, hold_on_read_error=hold_on_read_error, allow_stale_hold=allow_stale_hold,
        )

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


def bind_trace_source(runner, trace_path: Path, trace_file, io: Path) -> bool:
    """Expose a receipt only for the trace beside this owner's FIFO directory."""
    if trace_path.parent != io.resolve().parent:
        return False
    runner.trace_file = trace_file
    runner.trace_source = trace_path.name
    runner.trace_cursor = os.fstat(trace_file.fileno()).st_size
    return True


def _finite_rim(raw, label: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{label} must be a finite number in [-0.05, 0.5], got {raw!r}")
    try:
        val = float(raw)
    except OverflowError:
        raise ValueError(f"{label} must be a finite number in [-0.05, 0.5], got {raw!r}") from None
    if not math.isfinite(val) or not -0.05 <= val <= 0.5:
        raise ValueError(f"{label} must be a finite number in [-0.05, 0.5], got {raw!r}")
    return val


def resolve_runner_rim_z(library: dict | None, *, params=None, rim_z_m: float | None = None) -> float | None:
    """Collect runner-owned source rim height (m) from CLI arg, params, and startup library."""
    vals = []
    if rim_z_m is not None:
        vals.append(_finite_rim(rim_z_m, "rim_z_m"))
    if params and "policy.source_rim_z_m" in params:
        p_rim = _finite_rim(params["policy.source_rim_z_m"], "policy.source_rim_z_m")
        if p_rim > 0.0:
            vals.append(p_rim)
    if isinstance(library, dict):
        src = library.get("source")
        if src is not None and not isinstance(src, dict):
            raise ValueError("startup library source must be a dict")
        pick = src.get("pick") if isinstance(src, dict) else None
        if pick is not None and not isinstance(pick, dict):
            raise ValueError("startup library source.pick must be a dict")
        for name, mapping in (("source", src), ("source.pick", pick)):
            if isinstance(mapping, dict):
                for key in ("rim_z_m", "rim_z"):
                    if mapping.get(key) is not None:
                        vals.append(_finite_rim(mapping[key], f"startup {name}.{key}"))
        pb = library.get("policy_playback")
        if pb is not None and not isinstance(pb, dict):
            raise ValueError("startup policy_playback must be a dict")
        for name, gate in (("jaw_gate", library.get("jaw_gate")),
                           ("policy_playback.jaw_gate", pb.get("jaw_gate") if isinstance(pb, dict) else None)):
            if isinstance(gate, dict) and "rim_z_m" in gate:
                vals.append(_finite_rim(gate["rim_z_m"], f"startup {name}.rim_z_m"))
    return max(vals) if vals else None


def startup_grasp_ref(library: dict | None, *, tcp_x_m: float | None = None) -> dict | None:
    """Snapshot trusted startup grasp_pick geometry so later `load` cannot drop or shift it."""
    if not isinstance(library, dict) or "grasp_pick" not in (library.get("chunks") or {}):
        return None
    ref = {"chunks": {"grasp_pick": [list(library["chunks"]["grasp_pick"][-1])]}}
    if isinstance(library.get("source"), dict):
        ref["source"] = dict(library["source"])
    eff_tcp = library["tcp_x_m"] if library.get("tcp_x_m") is not None else tcp_x_m
    if eff_tcp is not None:
        ref["tcp_x_m"] = eff_tcp
    return ref


def startup_tcp_x_m(library: dict | None) -> float:
    from omx_tcp import ENV, RANGE_M

    lib_raw = library.get("tcp_x_m") if isinstance(library, dict) else None
    raw = lib_raw if lib_raw is not None else (os.environ.get(ENV) or None)
    if raw is None:
        from grasp_planner import load_kinematics

        val = float(load_kinematics(None)[0].tcp_offset[0])
        if not (math.isfinite(val) and RANGE_M[0] <= val <= RANGE_M[1]):
            raise ValueError(f"invalid stock tcp_x_m: {val!r}")
        return val
    label = "startup tcp_x_m" if lib_raw is not None else ENV
    if isinstance(raw, bool) or (lib_raw is not None and not isinstance(raw, (int, float))):
        raise ValueError(f"invalid {label}: {raw!r}")
    try:
        val = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"invalid {label}: {raw!r}") from None
    if not (math.isfinite(val) and RANGE_M[0] <= val <= RANGE_M[1]):
        raise ValueError(f"invalid {label}: {raw!r}")
    return val


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, type=Path, help="record config (robot section is used)")
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--io", required=True, type=Path, help="directory for chunk-cmd (FIFO) and chunk-status.jsonl")
    parser.add_argument("--operating-profile", type=Path, help="per-device operating profile; unbound sessions cannot auto-pick")
    parser.add_argument("--params", type=Path, help="cell-params.json (rosy.omx-cell-params.v1); default: the built-in values")
    parser.add_argument("--load-model", type=Path, help="load-model.json (load_model.py): refuse a library whose holds are predicted risky")
    parser.add_argument("--rim-z-m", type=float, help="configured source rim height (m) enforced on policy jaw_gate")
    args = parser.parse_args(argv)
    signals: list = []  # recorded, not raised: an interrupt folds or holds (chunk_runner_interrupt), never drops the arm
    __import__("chunk_runner_interrupt").install(signals)
    library = load_library(args.library)
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    params = prm.load(args.params)["values"]
    try:
        rim_z_m = resolve_runner_rim_z(library, params=params, rim_z_m=args.rim_z_m)
        trusted_tcp = startup_tcp_x_m(library)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    trusted_grasp = startup_grasp_ref(library, tcp_x_m=trusted_tcp)
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

    from chunk_runner_guards import safe_stderr

    def status(row):
        protect = bool(signals or getattr(runner, "human_hold_latched", False)
                       or getattr(runner, "_stop_after_park", None))
        try:
            with status_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
        except OSError as error:  # interrupted: a full disk is reported, the fold or hold goes on (no torque OFF)
            if not protect:
                raise
            safe_stderr({"status_write_failed": str(error)[:300], "row": row})
        try:
            print(json.dumps(row), flush=True)
        except (OSError, ValueError) as error:
            if not protect:
                raise OSError(str(error)) from error

    from guarded_native import NativeJointMotion, close_device, connect_passive
    from motor_health import MotorHealth

    lines = fifo_lines(args.io / "chunk-cmd")
    # The guard owns the hardware lifecycle and every goal (D-872): passive connect (no vendor
    # configure), seeded torque ON, 10 deg/s streaming, following-error, effort and fault stops.
    connect_passive(robot, follower=True)
    motion = NativeJointMotion(robot.bus, None, teacher=True, monitor=MotorHealth())
    motion.shed_load = True  # a guard hold freezes only the held joint: runner_strain.shed moves lift and elbow
    guarded = Guarded(robot, motion)
    runner = None
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
            try:
                tmp.write_text(json.dumps(row))
                os.replace(tmp, live_path)
            except OSError:
                if not signals and not getattr(runner, "human_hold_latched", False):
                    raise

        context = runtime_context(config["robot"], robot.bus, config["dataset"]["fps"],
                                  operating_profile=profile, params=params)
        runner = Runner(guarded, library, fps=config["dataset"]["fps"], status=status, live=live,
                        operating_context=context, params=params, plan_check=check, rim_z_m=rim_z_m)
        runner.trusted_grasp, runner.trusted_tcp = trusted_grasp, trusted_tcp
        runner.signals, runner.hold_file = signals, args.io / "hold.json"  # hold.json: record_session reads it
        # heavy imports (lerobot, numpy, torch), the robot and the bus are up: only now may the main thread take signals
        # (one sent during start-up was pending and is recorded now, the handlers being installed above)
        runner.signal_routing = __import__("main_thread_signals").unblock_main()
        if runner.signal_routing:  # another thread can take them: gated_close's re-check right before close_device
            safe_stderr({"signal_routing": "threads accept SIGTERM", "tids": runner.signal_routing})
        trace_path = Path(path).expanduser().resolve() if (path := os.environ.get("ROSY_CHUNK_TRACE")) else None
        trace_file = trace_path.open("a") if trace_path else None  # buffered: no write call per tick
        if trace_file:
            runner.trace = __import__("cell_why").flushing_trace(trace_file)
            bind_trace_source(runner, trace_path, trace_file, args.io)
        try:
            runner.run(lines)
        except Exception as error:
            if (not signals and not getattr(runner, "human_hold_latched", False)
                    and not getattr(runner, "_stop_after_park", None)
                    and getattr(runner, "_release_until", None) is None
                    and not getattr(motion, "failed", False)):
                raise  # no interrupt, no latched HOLD, no pending fold, no unconfirmed release, and no failed guard: torque OFF in finally
            __import__("chunk_runner_interrupt").last_resort_hold(runner, signals, error)  # returns on SIGUSR2 only
        finally:
            if trace_file:
                try:
                    trace_file.close()
                except OSError:
                    pass
    finally:
        lines.close()
        try:
            # the single place torque goes OFF: interrupts blocked from the gate's verdict until close_device returns;
            # after an interrupt, no torque OFF without a confirmed fold or an approved exception (else SIGUSR2 first)
            __import__("chunk_runner_interrupt").gated_close(runner, signals, args.io / "hold.json",
                                                             lambda: close_device(robot))
        finally:
            if motion.monitor is not None:
                motion.monitor.end()


if __name__ == "__main__":
    main()
