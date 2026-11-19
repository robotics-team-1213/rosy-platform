#!/usr/bin/env python3
"""CLI Argument Parser & Frame-Grabbing Runner for OMX Joint Tuning (`joint_tune_cli.py`).

Single Responsibility:
  - Validate joint tuning CLI arguments and safety bounds (`parse`).
  - Run `joint_tune` session with camera frame capture (`grab`) and session locking (`main`).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import urllib.request

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from joint_tune_lock import protect_signals, session_lock  # noqa: E402

GRIPPER = 16
FOLLOWER = {11: (1060, 4), 12: (1060, 4), 13: (1060, 4), 14: (1200, 4), 15: (1200, 4), 16: (1200, 5)}
LEADER_WRIST = 5
TUNABLE = {LEADER_WRIST: (1200, 4), **FOLLOWER}
CAP_MAX = 400
BASELINE = {"pwm_limit": 20, "current_limit": 50}


_PARENT_GLOBALS: dict | None = None


def _parent_attr(name: str, default=None, _globals: dict | None = None):
    g = _globals if _globals is not None else _PARENT_GLOBALS
    if g is not None and name in g:
        return g[name]
    mod = sys.modules.get("joint_tune")
    if mod is not None and hasattr(mod, name):
        return getattr(mod, name)
    return default



def parse(argv=None, *, doc: str = ""):
    parser = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", required=True)
    parser.add_argument("--id", type=int, default=GRIPPER, choices=sorted(TUNABLE))
    parser.add_argument("--viewer", default="http://127.0.0.1:8767", help="local camera viewer ('' to skip frames)")
    parser.add_argument("command", choices=("hold", "move", "sweep"))
    parser.add_argument("--to", type=int)
    parser.add_argument("--delta", type=int)
    parser.add_argument("--pwm", type=int, default=BASELINE["pwm_limit"])
    parser.add_argument("--current-limit", type=int, default=BASELINE["current_limit"], help="XL330 only")
    parser.add_argument("--goal-current", type=int, default=BASELINE["current_limit"], help="gripper only")
    parser.add_argument("--p-gain", type=int)
    parser.add_argument("--i-gain", type=int)
    parser.add_argument("--velocity", type=int, default=1)
    parser.add_argument("--acceleration", type=int, default=1)
    parser.add_argument("--hold", type=float, default=1.0, help="seconds to hold the start at torque ON")
    parser.add_argument("--sag", type=int, default=20, help="ticks the start may drift while holding")
    parser.add_argument("--max-delta", type=int, default=200, help="non-gripper move limit in ticks")
    parser.add_argument("--reach", type=int, default=1700, help="gripper sweep: push this far each way")
    args = parser.parse_args(argv)
    if args.id == LEADER_WRIST:
        args.velocity = args.acceleration = 1
    if not (
        1 <= args.pwm <= CAP_MAX
        and 1 <= args.current_limit <= CAP_MAX
        and 1 <= args.goal_current <= args.current_limit
    ):
        parser.error(f"caps must be 1..{CAP_MAX} and the goal current at most the current limit")
    if any(gain is not None and not 0 <= gain <= 2000 for gain in (args.p_gain, args.i_gain)):
        parser.error("gains must be 0..2000")
    if not (1 <= args.velocity <= 32767 and 1 <= args.acceleration <= 32767 and 1 <= args.reach <= 4095):
        parser.error("profile velocity/acceleration must be 1..32767 and sweep reach 1..4095")
    if not (0 < args.hold <= 5 and 0 < args.sag <= 100 and 0 < args.max_delta <= 400):
        parser.error("--hold 0..5 s, --sag 1..100, --max-delta 1..400")
    if args.command == "sweep" and args.id != GRIPPER:
        parser.error("sweep pushes to mechanical ends: gripper (16) only")
    if args.command == "hold" and (
        args.id != GRIPPER
        or args.to is not None
        or args.delta is not None
        or args.pwm != BASELINE["pwm_limit"]
        or args.current_limit != BASELINE["current_limit"]
        or args.p_gain is not None
        or args.i_gain is not None
        or args.velocity != 1
        or args.acceleration != 1
    ):
        parser.error("hold requires gripper (16), baseline caps, 1/1 profiles and no target or gain changes")
    if args.command == "move":
        if (args.to is None) == (args.delta is None):
            parser.error("move needs exactly one of --to / --delta")
        if args.to is not None and not 0 <= args.to <= 4095:
            parser.error("--to must be 0..4095")
    return args


def main(argv=None, *, _globals: dict | None = None):
    attr = lambda name, default=None: _parent_attr(name, default, _globals)
    args = parse(argv, doc=attr("__doc__", "") or "")
    out = Path("tune.jsonl")

    def log(**row):
        row["t"] = round(time.monotonic(), 3)
        with out.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)

    def grab(label):
        if not args.viewer:
            return
        Path("frames").mkdir(exist_ok=True)
        saved = {}
        for camera in ("top", "front"):
            name = f"frames/tune-{time.strftime('%H%M%S')}-id{args.id}-{label}-{camera}.jpg"
            try:
                host = args.viewer.split("//", 1)[-1]
                request = urllib.request.Request(f"{args.viewer}/frame/{camera}.jpg", headers={"Host": host})
                Path(name).write_bytes(urllib.request.urlopen(request, timeout=2).read())
                saved[camera] = name
            except Exception as exc:
                saved[camera] = f"unavailable: {exc}"
        log(step="frames", label=label, **saved)

    ps_fn = attr("protect_signals", protect_signals)
    sl_fn = attr("session_lock", session_lock)
    bus_cls = attr("SerialBus")
    run_cls = attr("Run")
    ps_fn()
    lock = sl_fn()
    try:
        bus = bus_cls(args.device, args.id)
        try:
            result = run_cls(bus, args.id, log=log, grab=grab).execute(args)
        finally:
            bus.close()
    finally:
        lock.close()
    if args.command == "sweep":
        Path("gripper-profile.json").write_text(json.dumps(result, indent=2))
