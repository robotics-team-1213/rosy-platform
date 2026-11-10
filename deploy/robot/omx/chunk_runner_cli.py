#!/usr/bin/env python3
"""The chunk-runner command line (split of `chunk_runner.py`, D-766 2).

`Guarded`, the judge FIFO and `main()`; the runner itself stays in `chunk_runner`, which
still starts this CLI as its `__main__`. Launched by record_session.py --chunks.
"""
from __future__ import annotations

import argparse
import json
import os
import select
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
_ADAPTER_SRC = str(Path(__file__).resolve().parents[3] / "middleware/devices/omx/adapter")
if _ADAPTER_SRC not in sys.path:
    sys.path.insert(0, _ADAPTER_SRC)
from omx_adapter.chunk_library import load_library  # noqa: E402
from cell_envelope import runtime_context  # noqa: E402
import cell_params as prm  # noqa: E402
import load_predict  # noqa: E402
from chunk_runner import Runner  # noqa: E402



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
