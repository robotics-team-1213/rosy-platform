#!/usr/bin/env python3
"""Build a two-episode replay trajectory from one taught leader demonstration (scripted teacher, T1).

The taught cycle is split at --split seconds into A (load: Pinky to conveyor) and B (return: conveyor
to Pinky and home). The trajectory holds A, a reset hold at A's last pose (torque stays on, so the
extended arm never drops), then B; both episodes are padded to the same length because lerobot-record
has one episode_time_s. Values stay in the leader's LeRobot units, so record_session --replay feeds
them to the follower exactly as a hand on the leader would, under the same max_relative_target clip.

  teach_trajectory.py build --dataset <teach root> --split 28 --end 50 --reset 2 --out cycle.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

SCHEMA = "rosy.omx-replay-trajectory.v1"
NAMES = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos",
         "gripper.pos"]


def compose(actions: list, fps: int, split_s: float, end_s: float, reset_s: float, source: dict) -> dict:
    split, end, reset = round(split_s * fps), round(end_s * fps), round(reset_s * fps)
    if not 0 < split < end <= len(actions) or reset < 1:
        raise ValueError("need 0 < split < end <= demonstration length and a positive reset")
    a, b = actions[:split], actions[split:end]
    length = max(len(a), len(b))
    a, b = a + [a[-1]] * (length - len(a)), b + [b[-1]] * (length - len(b))
    frames = a + [a[-1]] * reset + b
    return {"schema": SCHEMA, "fps": fps, "names": NAMES, "frames": frames, "source": source,
            "segments": {"A": [0, length], "reset": [length, length + reset], "B": [length + reset, len(frames)]}}


def load(path: Path, *, fps: int) -> dict:
    """A validated trajectory; record_session refuses anything else before the follower is touched."""
    trajectory = json.loads(Path(path).read_text())
    if trajectory.get("schema") != SCHEMA or trajectory.get("names") != NAMES or trajectory.get("fps") != fps:
        raise SystemExit(f"replay trajectory needs schema {SCHEMA}, the six follower names and fps {fps}")
    frames, segments = trajectory.get("frames"), trajectory.get("segments", {})
    if not frames or any(len(f) != len(NAMES) or not all(isinstance(v, (int, float)) and math.isfinite(v)
                                                         and -100 <= v <= 100 for v in f) for f in frames):
        raise SystemExit("replay frames must be six finite values within -100..100")
    (a0, a1), (r0, r1), (b0, b1) = (segments.get(k, [0, 0]) for k in ("A", "reset", "B"))
    if not (a0 == 0 < a1 == r0 < r1 == b0 < b1 == len(frames) and a1 - a0 == b1 - b0):
        raise SystemExit("replay segments must be A, reset, B of equal-length episodes covering every frame")
    trajectory["sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return trajectory


def read_demonstration(root: Path) -> tuple[list, int]:
    import numpy as np
    import pandas as pd

    info = json.loads((root / "meta/info.json").read_text())
    if info["features"]["action"]["names"] != NAMES:
        raise SystemExit("the demonstration's action names are not the OMX leader's")
    frame = pd.concat(pd.read_parquet(p, columns=["action"]) for p in sorted(root.glob("data/**/*.parquet")))
    return np.stack(frame["action"].to_numpy()).round(3).tolist(), info["fps"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["build"])
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--split", required=True, type=float, help="seconds: end of A, start of B")
    parser.add_argument("--end", required=True, type=float, help="seconds: end of B (arm home)")
    parser.add_argument("--reset", type=float, default=2.0, help="seconds held between A and B")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    actions, fps = read_demonstration(args.dataset)
    source = {"dataset": str(args.dataset), "split_s": args.split, "end_s": args.end}
    trajectory = compose(actions, fps, args.split, args.end, args.reset, source)
    args.out.write_text(json.dumps(trajectory))
    load(args.out, fps=fps)
    print(json.dumps({"out": str(args.out), "segments": trajectory["segments"], "fps": fps}))


if __name__ == "__main__":
    main()
