"""Pure taught-library parsing and joint-space transit paths shared by native callers."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .motion_profile import smooth

# The guard streams at most 10 deg/s; 5 native units/s keeps every joint under 9 deg/s.
GUARD_UNITS_PER_S = 5.0
NAMES = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos",
         "gripper.pos"]
# Taught carry height: turning low first scraped the jaws on the table on 2026-10-24.
TRANSIT = {1: -27.0, 2: 18.0, 3: 46.0}
PARK_SPEED = GUARD_UNITS_PER_S
SCHEMA = "rosy.omx-chunk-library.v1"


def too_fast(frames: list, fps: int) -> bool:
    limit = GUARD_UNITS_PER_S / fps + 1e-3  # frames are stored rounded to 3 decimals
    return any(abs(a - b) > limit for p, q in zip(frames, frames[1:]) for a, b in zip(p, q))


def transit_path(start: list, goal: list, grip_transit: float, fps: int, transit: dict | None = None,
                 speed: float = 0.85) -> list:
    """From anywhere to `goal` without sweeping low: jaws to `grip_transit`, rise to the transit height,
    turn pan/roll to the goal there, descend into the goal body pose, then set the goal's jaws.
    `transit` maps joint indexes to values (a cell profile's transit); default TRANSIT (arm S).
    `speed` is the fraction of the guard speed (a plan's transit_speed)."""
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
    return smooth(waypoints, fps, speed * PARK_SPEED, blend=[False, False, True, True, False, False], blend_s=0.6)


def park_path(start: list, home: list, closed: float, fps: int, transit: dict | None = None,
              speed: float = 0.85) -> list:
    """Close the jaws, rise, turn at that height, then descend into home (jaws stay closed)."""
    return transit_path(start, list(home[:5]) + [closed], closed, fps, transit, speed)


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
    speed = library.get("transit_speed", 0.85)
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not 0.1 <= speed <= 0.85:
        raise SystemExit(f"transit_speed {speed!r} must be 0.1..0.85 of the guard speed (blended corners need the rest)")
    return library
