"""Pure taught-library parsing and joint-space transit paths shared by native callers."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .motion_profile import TemporalChunkEnsembler, blend_chunks, flow, receding_horizon_splice

# The guard streams at most 10 deg/s; 5 native units/s keeps every joint under 9 deg/s.
GUARD_UNITS_PER_S = 5.0
NAMES = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos", "gripper.pos"]
# Taught carry height: turning low first scraped the jaws on the table on 2026-10-24.
TRANSIT = {1: -27.0, 2: 18.0, 3: 46.0}
PARK_SPEED = GUARD_UNITS_PER_S
FOLDED_ROLL_LIFT = (10.0, -10.0)  # wrist camera clearance lift before rotating wrist_roll when folded
FOLDED_UNFOLD_ELBOW = 43.0  # open elbow_flex first from folded home so jaws lift outward/upward clear of base tab
# Rise lag logs (10/26-27): 2 units/s (3.6 deg/s) keeps lag under the 5-unit strain limit across arm loads.
RISE_SPEED = 2.0
# Above closed + this threshold jaws are open (empty; box holds 51.6-54.1 vs open_max 56): rise before closing.
OPEN_JAW_MARGIN = 8.0
SCHEMA = "rosy.omx-chunk-library.v1"


def too_fast(frames: list, fps: int) -> bool:
    limit = GUARD_UNITS_PER_S / fps + 1e-3  # frames are stored rounded to 3 decimals
    return any(abs(a - b) > limit for p, q in zip(frames, frames[1:]) for a, b in zip(p, q))


def transit_path(start: list, goal: list, grip_transit: float, fps: int, transit: dict | None = None, speed: float = 0.85) -> list:
    """Move anywhere -> `goal` without sweeping low: open jaws rise before closing at transit; held boxes close first."""
    if (start[1] >= -35.0 and goal[1] >= -35.0 and abs(start[0] - goal[0]) <= 15.0
            and max(abs(a - b) for a, b in zip(start[:4], goal[:4])) <= 24.0 and abs(start[4] - goal[4]) <= 45.0):
        return flow([list(start), list(goal[:6])], fps, speed * PARK_SPEED, blend=[False, False], blend_s=0.25, rise_speed=RISE_SPEED)
    if transit is None:
        transit = {1: max(TRANSIT[1], min(start[1], goal[1], -16.0) - 5.0), 2: TRANSIT[2], 3: TRANSIT[3]} if (
            start[1] > -22.0 and goal[1] > -22.0 and abs(start[0] - goal[0]) <= 15.0) else TRANSIT
    rise_first = start[5] > grip_transit + OPEN_JAW_MARGIN
    waypoints = [list(start)] + ([] if rise_first else [list(start[:5]) + [grip_transit]])
    unfold = start[1] <= -50.0 and start[2] > FOLDED_UNFOLD_ELBOW + 0.5 and transit.get(2, start[2]) < FOLDED_UNFOLD_ELBOW
    if unfold:
        waypoints.append(waypoints[-1][:2] + [FOLDED_UNFOLD_ELBOW] + waypoints[-1][3:])
    waypoints.append([transit.get(i, v) for i, v in enumerate(waypoints[-1])])
    if rise_first:
        waypoints.append(list(waypoints[-1][:5]) + [grip_transit])
    turn = [goal[i] if i in (0, 4) else v for i, v in enumerate(waypoints[-1])]
    skip_turn = goal[1] <= waypoints[-1][1] and max(abs(turn[i] - waypoints[-1][i]) for i in (0, 4)) <= 8.0
    if not skip_turn:
        waypoints.append(turn)
    waypoints.extend([list(goal[:5]) + [grip_transit], list(goal[:6])])
    # Eased flow capped at RISE_SPEED, corners blended up to 0.6 s; open jaws skip blend before closing at transit.
    blend = [False, False, not rise_first, not skip_turn, False] + ([] if skip_turn else [False])
    if unfold:
        blend.insert(1 if rise_first else 2, False)  # the unfold waypoint (index 1, 2 after the grip close) is passed at rest
    return flow(waypoints, fps, speed * PARK_SPEED, blend=blend, blend_s=0.6, rise_speed=RISE_SPEED)


def chain_path(steps: list[list], fps: int, blend_s: float = 0.25) -> list:
    """Blend a list of non-empty frame sequences so consecutive body chunks flow without dead stops."""
    out: list = []
    for frames in steps:
        if not frames:
            continue
        out = blend_chunks(out, frames, fps, blend_s=blend_s, vmax=GUARD_UNITS_PER_S) if out else [list(f) for f in frames]
    return out


def park_path(start: list, home: list, closed: float, fps: int, transit: dict | None = None, speed: float = 0.85) -> list:
    """Close jaws, rise, turn, then descend into home; stay folded for near-home/folded/tucked starts instead of unfolding."""
    goal = list(home[:5]) + [closed]
    near_home = max(abs(a - b) for a, b in zip(start[:5], goal[:5])) <= 5.0 and abs(start[5] - closed) <= 5.0
    folded_pose = (start[1] <= -50.0 and goal[1] <= -50.0 and max(abs(a - b) for a, b in zip(start[1:4], goal[1:4])) <= 10.0 and abs(start[0] - goal[0]) <= 70.0 and abs(start[4] - goal[4]) <= 45.0)
    if near_home or folded_pose:
        waypoints = [list(start)] + ([list(start[:5]) + [closed]] if abs(start[5] - closed) > 5.0 else [])
        if abs(start[4] - goal[4]) > FOLDED_ROLL_LIFT[0]:
            waypoints += [[*w[:2], w[2] + FOLDED_ROLL_LIFT[1], *w[3:]] for w in (waypoints[-1], goal)]
        waypoints.append(goal)
        rate = (0.5 if abs(start[0] - goal[0]) <= 12.0 else 1.0) * speed * PARK_SPEED
        return flow(waypoints, fps, rate, blend=[False] * len(waypoints), blend_s=0.2, rise_speed=RISE_SPEED)
    if -50.0 < start[1] <= -15.0 and goal[1] <= -50.0 and start[2] >= 35.0 and goal[2] >= 35.0 and abs(start[0] - goal[0]) <= 45.0 and abs(start[4] - goal[4]) <= 45.0:
        el_clear, lift_mid = min(start[2], 43.0), min(start[1], -42.0)
        waypoints = [list(start)] + ([list(start[:5]) + [closed]] if abs(start[5] - closed) > 5.0 else [])
        if start[2] > el_clear + 0.5: waypoints.append([start[0], start[1], el_clear, start[3], start[4], closed])
        if start[1] > lift_mid + 0.5: waypoints.append([start[0], lift_mid, el_clear, start[3], start[4], closed])
        waypoints.extend(([start[0], goal[1], goal[2], start[3], start[4], closed], goal))
        return flow(waypoints, fps, speed * PARK_SPEED, blend=[False] * len(waypoints), blend_s=0.2, rise_speed=RISE_SPEED)
    return transit_path(start, goal, closed, fps, transit, speed)


def _finite_in(val, lo: float, hi: float) -> bool:
    try:
        f = float(val) if not isinstance(val, bool) and isinstance(val, (int, float)) else math.nan
    except OverflowError:
        return False
    return math.isfinite(f) and lo <= f <= hi


def load_library(path: Path) -> dict:
    library = json.loads(Path(path).read_text())
    if not isinstance(library, dict) or library.get("schema") != SCHEMA or library.get("names") != NAMES:
        raise SystemExit(f"chunk library needs schema {SCHEMA} and the six follower names")
    fps = library.get("fps")
    if type(fps) is not int or not 1 <= fps <= 1000:
        raise SystemExit("chunk library needs its fps")
    chunks = library.get("chunks")
    if not isinstance(chunks, dict) or not chunks:
        raise SystemExit("chunk library has no chunks")
    for name, frames in chunks.items():
        if not isinstance(frames, list) or not frames or any(not isinstance(f, (list, tuple)) or len(f) != 6 or not all(_finite_in(v, -100.0, 100.0) for v in f) for f in frames):
            raise SystemExit(f"chunk {name}: frames must be six finite values within -100..100")
        if too_fast(frames, fps):
            raise SystemExit(f"chunk {name}: frames move faster than the guard streams ({GUARD_UNITS_PER_S} units/s); regenerate the library with grasp_planner.py or teach_trajectory.py")
    if not _finite_in(library.get("gripper_closed"), -100.0, 100.0):
        raise SystemExit("chunk library needs gripper_closed (finite value in -100..100)")
    speed = library.get("transit_speed", 0.85)
    if not _finite_in(speed, 0.1, 0.85):
        raise SystemExit(f"transit_speed {speed!r} must be 0.1..0.85 of the guard speed (blended corners need the rest)")
    if (transit := library.get("transit")) is not None and (not isinstance(transit, dict) or any(k not in (*NAMES, *"012345") or not _finite_in(v, -100.0, 100.0) for k, v in transit.items())):
        raise SystemExit("chunk library transit joints must be finite values within -100..100")
    if library.get("jaw_empty_stop") is not None and not _finite_in(library["jaw_empty_stop"], -100.0, 100.0):
        raise SystemExit("chunk library jaw_empty_stop must be finite within -100..100")
    return library
