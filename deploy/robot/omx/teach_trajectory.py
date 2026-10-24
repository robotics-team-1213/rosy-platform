#!/usr/bin/env python3
"""Build a two-episode replay trajectory from one taught leader demonstration (scripted teacher, T1).

The taught cycle is split at --split seconds into A (load: Pinky to conveyor) and B (return: conveyor
to Pinky and home). The trajectory holds A, a reset hold at A's last pose (torque stays on, so the
extended arm never drops), then B; both episodes are padded to the same length because lerobot-record
has one episode_time_s. Values stay in the leader's LeRobot units, so record_session --replay feeds
them to the follower exactly as a hand on the leader would, under the same max_relative_target clip.

  teach_trajectory.py build --dataset <teach root> --split 28 --end 50 --reset 2 --out cycle.json
  teach_trajectory.py standard --dataset <root with several taught cycles> --dwell 1 --out cycle.json
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


GRIPPER = 5
TRANSITIONS = 6  # open, grasp on Pinky, release on belt, grasp on belt, release on Pinky, close at home


def gripper_events(actions, fps: int, hold_s: float = 0.5) -> list:
    """Frames where the gripper changes between closed and open and stays there for `hold_s`."""
    grip = [frame[GRIPPER] for frame in actions]
    low, high = min(grip), max(grip)
    if high - low < 3:
        return []
    middle, hold = (low + high) / 2, max(1, round(hold_s * fps))
    state, events, i = grip[0] > middle, [], 0
    while i < len(grip):
        if (grip[i] > middle) != state and all((g > middle) != state for g in grip[i:i + hold]):
            state = not state
            events.append(i)
            i += hold
        else:
            i += 1
    return events


def _resample(segment, length: int) -> list:
    if len(segment) == 1 or length == 1:
        return [list(segment[0])] * length
    out = []
    for k in range(length):
        x = k * (len(segment) - 1) / (length - 1)
        i = min(int(x), len(segment) - 2)
        w = x - i
        out.append([(1 - w) * p + w * q for p, q in zip(segment[i], segment[i + 1])])
    return out


def standard(demos: list, fps: int, dwell_s: float = 1.0) -> tuple[list, int, list]:
    """One standard cycle from several taught cycles: each demonstration is cut at its six gripper
    events, every phase is resampled to the median phase length, and each frame is the per-joint
    median. Before each grasp the pose is held `dwell_s` so the follower settles under the
    max_relative_target clip before the jaws close. Returns (actions, split frame, used demo indices);
    the split is the middle of the release-on-belt phase (end of A, start of B)."""
    cut, used = [], []
    for index, actions in enumerate(demos):
        events = gripper_events(actions, fps)
        if len(events) != TRANSITIONS:
            continue
        moving = [i for i in range(1, len(actions)) if max(abs(p - q) for p, q in zip(actions[i], actions[i - 1])) * fps > 3]
        end = max(events[-1] + 1, min(len(actions), (moving[-1] if moving else len(actions)) + fps // 2))
        bounds = [0, *events, end]
        cut.append([actions[a:b] for a, b in zip(bounds, bounds[1:]) if b > a])
        used.append(index)
    if len(cut) < 2 or any(len(phases) != TRANSITIONS + 1 for phases in cut):
        raise SystemExit(f"need at least two demonstrations with {TRANSITIONS} gripper events; usable: {used}")
    result, split = [], 0
    for phase in range(TRANSITIONS + 1):
        length = sorted(len(phases[phase]) for phases in cut)[len(cut) // 2]
        columns = [_resample(phases[phase], length) for phases in cut]
        frames = [[sorted(c[k][j] for c in columns)[len(columns) // 2] for j in range(len(NAMES))] for k in range(length)]
        if phase in (1, 3):  # the phase that ends with a grasp: hold its last open pose first
            frames += [frames[-1]] * round(dwell_s * fps)
        if phase == 3:
            split = len(result) + length // 2
        result += frames
    return [[round(v, 3) for v in frame] for frame in result], split, used


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


def read_demonstrations(root: Path) -> tuple[list, int]:
    """Leader actions per episode, in episode order."""
    import numpy as np
    import pandas as pd

    info = json.loads((root / "meta/info.json").read_text())
    if info["features"]["action"]["names"] != NAMES:
        raise SystemExit("the demonstration's action names are not the OMX leader's")
    frame = pd.concat(pd.read_parquet(p, columns=["episode_index", "action"]) for p in sorted(root.glob("data/**/*.parquet")))
    return [np.stack(rows["action"].to_numpy()).round(3).tolist()
            for _, rows in sorted(frame.groupby("episode_index"), key=lambda item: item[0])], info["fps"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["build", "standard"],
                        help="build: one episode cut at --split/--end; standard: median of every episode's cycle")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--split", type=float, help="build: seconds, end of A and start of B")
    parser.add_argument("--end", type=float, help="build: seconds, end of B (arm home)")
    parser.add_argument("--episode", type=int, default=0, help="build: which taught episode")
    parser.add_argument("--dwell", type=float, default=1.0, help="standard: seconds held before each grasp")
    parser.add_argument("--reset", type=float, default=2.0, help="seconds held between A and B")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    demos, fps = read_demonstrations(args.dataset)
    if args.command == "standard":
        actions, split, used = standard(demos, fps, args.dwell)
        source = {"dataset": str(args.dataset), "method": "median of gripper-event phases", "episodes": used,
                  "dwell_s": args.dwell}
        trajectory = compose(actions, fps, split / fps, len(actions) / fps, args.reset, source)
    else:
        if args.split is None or args.end is None:
            parser.error("build needs --split and --end")
        source = {"dataset": str(args.dataset), "episode": args.episode, "split_s": args.split, "end_s": args.end}
        trajectory = compose(demos[args.episode], fps, args.split, args.end, args.reset, source)
    args.out.write_text(json.dumps(trajectory))
    load(args.out, fps=fps)
    print(json.dumps({"out": str(args.out), "segments": trajectory["segments"], "fps": fps}))


if __name__ == "__main__":
    main()
