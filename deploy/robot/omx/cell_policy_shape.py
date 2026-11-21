"""Calibrated unit conversion and reviewed-envelope shaping for ACT chunks."""
import math
from pathlib import Path

import numpy as np

import cell_lerobot_shadow as lrs

MARGIN = 3.0  # units of sensor and settle noise outside the reviewed range
JOINTS = len(lrs.JOINT_NAMES)
SCALE = {name: 200.0 for name in lrs.JOINT_NAMES[:-1]} | {"gripper": 100.0}
SIM_POLICY_FPS = 15


def calibration_offset(model_cal: dict, cell_cal: dict) -> list[float]:
    """Model units minus cell units per joint: Present_Position carries the homing offset, so a different homing shifts
    every reading by (model_homing - cell_homing) ticks."""
    offset = []
    for name in lrs.JOINT_NAMES:
        m, c = model_cal[name], cell_cal[name]
        if (m["range_min"], m["range_max"], m["drive_mode"]) != (c["range_min"], c["range_max"], c["drive_mode"]):
            raise ValueError(f"{name}: range or drive mode differ, not a pure homing shift")
        span = float(m["range_max"] - m["range_min"])
        offset.append((float(m["homing_offset"]) - float(c["homing_offset"])) * SCALE[name] / span)
    return offset


def envelope(library: dict) -> tuple[list[float], list[float], float]:
    """(per-joint min, max, fastest step) over every frame of the reviewed library's chunks."""
    frames = [f for chunk in library["chunks"].values() for f in chunk if len(f) == JOINTS]
    if not frames:
        raise ValueError("reviewed library has no 6-joint frames")
    arr = np.asarray(frames, dtype=float)
    steps = [np.abs(np.diff(np.asarray(c, dtype=float)[:, :5], axis=0)).max()
             for c in library["chunks"].values() if len(c) > 1]
    return arr.min(axis=0).tolist(), arr.max(axis=0).tolist(), float(max(steps))


def demonstrated_range(policy_root: Path, offset) -> tuple[list[float], list[float]]:
    """Per-joint q01..q99 of the actions the model was trained on (recorded by a person on this arm), in cell units."""
    from safetensors.numpy import load_file

    files = sorted(Path(policy_root).glob("policy_preprocessor_step_*_normalizer_processor.safetensors"))
    if not files:
        raise ValueError("checkpoint has no normalizer statistics")
    stats = load_file(str(files[0]))
    off = np.asarray(offset, dtype=float)
    return (np.asarray(stats["action.q01"], dtype=float) - off).tolist(), (np.asarray(stats["action.q99"], dtype=float) - off).tolist()


def widen(low, high, demo_low, demo_high) -> tuple[list[float], list[float]]:
    """Union of the reviewed IK range and the range a person demonstrated on this arm, per joint."""
    return np.minimum(low, demo_low).tolist(), np.maximum(high, demo_high).tolist()


def open_before_close(chunk, open_g: float, closed: float):
    """IK help for the jaws (11-19: in a new scene the model opened only to 52 = a 30 mm gap, then closed on nothing):
    before the model's close (jaws back at closed after having been open) the jaws are at least the reviewed library's
    widest opening, then the model closes as it chose. A chunk without such a close is left as the model gave it."""
    arr = np.array(chunk, dtype=float)
    g = arr[:, 5]
    was_open = np.maximum.accumulate(g) > closed + 2.0
    closing = np.flatnonzero((g <= closed + 1.0) & was_open)
    if len(closing):
        arr[:closing[0], 5] = np.maximum(g[:closing[0]], open_g)
    return arr


def converted_closed(closed: float, rule: dict) -> float:
    from cell_act_inputs import real_grippers, sim_gripper

    return float(real_grippers([sim_gripper(closed, rule)], rule)[0])


def resample_chunk(chunk, start, library_fps: float) -> np.ndarray:
    """Sample the measured start (t=0) to each predicted row (t=1/15, 2/15, ...)."""
    path = np.vstack([start, chunk])
    ticks = np.arange(1, math.ceil(len(chunk) * library_fps / SIM_POLICY_FPS) + 1)
    times = ticks * SIM_POLICY_FPS / library_fps
    return np.column_stack([np.interp(times, np.arange(len(path)), joint) for joint in path.T])


def wrist_roll_warning(chunk, home_roll: float) -> str | None:
    from arm_status_bridge import TICKS

    # The two trained orientations are a half-turn apart. Accept within 45 degrees of either.
    half_turn = SCALE["wrist_roll"] * TICKS / (TICKS - 1) / 2
    distance = np.abs((chunk[:, 4] - home_roll + half_turn / 2) % half_turn - half_turn / 2)
    between = np.flatnonzero(distance > half_turn / 4)
    if len(between):
        i = between[0]
        return f"arm_b frame {i} wrist_roll={chunk[i, 4]:.2f} lies between trained branches (home={home_roll:.2f})"
    return None


def shape_chunk(chunk, start, low, high, fastest: float) -> list[list[float]]:
    """Cell-unit frames the runner may get: refused outside the envelope, stretched so no body step beats `fastest`."""
    arr = np.asarray(chunk, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != JOINTS or not np.isfinite(arr).all():
        raise ValueError("policy chunk is not finite (n, 6)")
    lo, hi = np.asarray(low) - MARGIN, np.asarray(high) + MARGIN
    outside = np.argwhere((arr < lo) | (arr > hi))
    if len(outside):
        i, j = outside[0]
        raise ValueError(f"frame {i} {lrs.JOINT_NAMES[j]}={arr[i, j]:.1f} outside reviewed {lo[j]:.1f}..{hi[j]:.1f}")
    path = np.vstack([np.asarray(start, dtype=float)[None, :], arr])
    out = []
    for a, b in zip(path[:-1], path[1:]):
        n = max(1, math.ceil(float(np.abs(b - a).max()) / fastest - 1e-9))  # all six joints, as the runner checks
        out.extend((a + (b - a) * k / n).tolist() for k in range(1, n + 1))
    return out
