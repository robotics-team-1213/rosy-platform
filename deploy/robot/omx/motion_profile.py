"""Pure joint-space motion through waypoints under the guard's teacher-mode limits (D-872).

Straight segments joined at corners turned direction in one frame. The guard's 10 deg/s^2 then rounded
each corner on its own, lagging the frames, and the lag read like pressing on something. Here each segment
is a trapezoid synchronised to its slowest joint. At a corner marked for blending, the next segment starts
while this one is still decelerating (overlap capped at `blend_s`), so velocity never jumps and the corner
is cut by well under a unit. Unmarked waypoints are passed at rest, exactly: grasp, release and goal poses.
"""
from __future__ import annotations

import math

if __name__ != "omx_adapter.motion_profile":
    from pathlib import Path
    import sys

    _ADAPTER_SRC = str(Path(__file__).resolve().parents[3] / "middleware/devices/omx/adapter")
    if _ADAPTER_SRC not in sys.path:
        sys.path.insert(0, _ADAPTER_SRC)

# The guard ramps at 10 deg/s^2. A body unit is at most 1.8 deg, so 5 units/s^2 stays under it. At a blend
# the segments' ramps overlap; on a joint both move, one slows while the other speeds up, so the speed stays
# under vmax, and the two ramps can briefly add to at most twice this (the guard then ramps a little behind).
GUARD_ACCEL_UNITS_S2 = 5.0


def trapezoid(distance: float, vmax: float, amax: float) -> tuple[float, float]:
    """(duration, ramp time) of a rest-to-rest move of `distance` under `vmax` and `amax`."""
    if distance <= 0:
        return 0.0, 0.0
    ramp = vmax / amax
    if distance < vmax * ramp:  # never reaches vmax: a triangle
        ramp = math.sqrt(distance / amax)
        return 2 * ramp, ramp
    return distance / vmax + ramp, ramp


def progress(t: float, duration: float, ramp: float) -> float:
    """0..1 along a trapezoid of `duration` with ramps of `ramp` at time `t`."""
    if t <= 0 or duration <= 0:
        return 0.0 if duration > 0 else 1.0
    if t >= duration:
        return 1.0
    peak = 1.0 / (duration - ramp)
    accel = peak / ramp
    if t < ramp:
        return 0.5 * accel * t * t
    if t > duration - ramp:
        rest = duration - t
        return 1.0 - 0.5 * accel * rest * rest
    return 0.5 * accel * ramp * ramp + peak * (t - ramp)


def smooth(waypoints: list, fps: int, vmax: float, amax: float = GUARD_ACCEL_UNITS_S2,
           blend: list | None = None, blend_s: float = 1.0) -> list:
    """Frames at `fps` from waypoints[0] (excluded) to waypoints[-1] (included, exactly)."""
    blend = blend or [False] * len(waypoints)
    segments, start = [], 0.0
    for i, (a, b) in enumerate(zip(waypoints, waypoints[1:])):
        delta = [y - x for x, y in zip(a, b)]
        duration, ramp = trapezoid(max(abs(v) for v in delta), vmax, amax)
        if segments and blend[i]:
            start -= min(segments[-1][3], ramp, blend_s)  # begin while the previous segment slows down
        segments.append((start, duration, delta, ramp))
        start += duration
    end = max((s + d for s, d, _, _ in segments), default=0.0)
    frames = []
    for k in range(1, max(1, math.ceil(end * fps)) + 1):
        t = min(k / fps, end)
        frames.append([w + sum(delta[j] * progress(t - s, d, r) for s, d, delta, r in segments)
                       for j, w in enumerate(waypoints[0])])
    frames[-1] = list(waypoints[-1])
    return frames


def retime(frames: list, fps: int, vmax: float, amax: float = GUARD_ACCEL_UNITS_S2, start=None) -> list:
    """The same path (a planner's IK frames along a vertical line) at an eased speed: it eases out of
    rest and into rest along a half cosine instead of starting and stopping with an acceleration step.
    `start` is the pose before frames[0]."""
    path = [list(start)] + [list(f) for f in frames] if start is not None else [list(f) for f in frames]
    if len(path) < 2:
        return [list(f) for f in frames]
    lengths = [0.0]
    for a, b in zip(path, path[1:]):
        lengths.append(lengths[-1] + max(abs(y - x) for x, y in zip(a, b)))
    total = lengths[-1]
    if total <= 0:
        return [list(path[-1])]
    duration, ramp = eased(total, vmax, amax)
    out, i = [], 0
    for k in range(1, max(1, math.ceil(duration * fps)) + 1):
        target = total * eased_progress(min(k / fps, duration), duration, ramp)
        while i < len(lengths) - 2 and lengths[i + 1] < target:
            i += 1
        span = lengths[i + 1] - lengths[i]
        w = 0.0 if span <= 0 else (target - lengths[i]) / span
        out.append([p + (q - p) * w for p, q in zip(path[i], path[i + 1])])
    out[-1] = list(path[-1])
    return out


def blend_chunks(a: list, b: list, fps: int, blend_s: float = 0.25, vmax: float = 5.0) -> list:
    """Overlap the decelerating tail of chunk `a` with the accelerating head of chunk `b` around `a[-1]`
    so consecutive body chunks flow through their shared waypoint without coming to a dead stop."""
    if not a or not b:
        return [list(f) for f in (a or b)]
    corner = a[-1]
    if any(abs(x - y) > vmax / fps + 1e-3 for x, y in zip(corner[:5], b[0][:5])):
        return [list(f) for f in a] + [list(f) for f in b]
    limit = vmax / fps + 1e-3
    max_m = min(round(blend_s * fps), len(a) // 2, len(b) // 2)
    for m in range(max_m, 0, -1):
        middle = [[av + (bv - cv) for av, bv, cv in zip(af, bf, corner)] for af, bf in zip(a[-m:], b[:m])]
        candidate = [list(f) for f in a[:-m]] + middle + [list(f) for f in b[m:]]
        if all(abs(x - y) <= limit for p, q in zip(candidate, candidate[1:]) for x, y in zip(p, q)):
            candidate[-1] = list(b[-1])
            return candidate
    return [list(f) for f in a] + [list(f) for f in b]


def eased(distance: float, vmax: float, amax: float) -> tuple[float, float]:
    """(duration, ramp time) of a rest-to-rest move whose speed rises and falls along a half cosine: the
    acceleration starts and ends at zero and peaks at `amax` (average ramp acceleration `2/pi * amax`; when
    `vmax` is tightened below the default cruise speed, `amax` scales down with `vmax` so the ramp does not
    dominate a slow descent/lift). A trapezoid's acceleration steps from 0 to amax in one tick (jerk 110 units/s^3
    at 30 fps, 12 here), a kick the guard's chaser and the servo both answer."""
    if distance <= 0:
        return 0.0, 0.0
    eff_amax = amax * min(1.0, max(0.75, vmax / 4.25)) if amax <= GUARD_ACCEL_UNITS_S2 else amax
    ramp = math.pi / 2 * vmax / eff_amax
    if distance < vmax * ramp:  # never reaches vmax: peak speed sqrt(2 d a / pi)
        ramp = math.pi / 2 * math.sqrt(2 * distance * eff_amax / math.pi) / eff_amax
        return 2 * ramp, ramp
    return distance / vmax + ramp, ramp


def eased_progress(t: float, duration: float, ramp: float) -> float:
    """0..1 along an `eased` move at time `t`."""
    if duration <= 0 or t >= duration:
        return 1.0
    if t <= 0:
        return 0.0
    peak = 1.0 / (duration - ramp)

    def ramped(x):  # distance covered x seconds into a ramp
        return 0.5 * peak * (x - ramp / math.pi * math.sin(math.pi * x / ramp))
    if t < ramp:
        return ramped(t)
    if t > duration - ramp:
        return 1.0 - ramped(duration - t)
    return 0.5 * peak * ramp + peak * (t - ramp)


def flow(waypoints: list, fps: int, vmax: float, blend: list, blend_s: float,
         amax: float = GUARD_ACCEL_UNITS_S2, rise_speed: float | None = None) -> list:
    """Frames at `fps` through `waypoints` (the first excluded, the last exact). Each segment is synchronised
    to its slowest joint, shoulder_lift (index 1) rising at most `rise_speed`; a blended segment begins while the
    previous one eases out (at most `blend_s`, never before the one before that has ended, so at most two
    segments move at once). Unblended waypoints are passed at rest."""
    segments, start = [], 0.0
    for i, (a, b) in enumerate(zip(waypoints, waypoints[1:])):
        delta = [y - x for x, y in zip(a, b)]
        # stretch the rising lift's distance so the shared profile moves it no faster than rise_speed;
        # once at/above transit (a[1] <= -16), the arm is clear for a faster high-crane rise,
        # and from hover poses (-16 < a[1] <= 0) the arm is already clear of deep reach torque.
        eff_rise = (
            max(rise_speed, min(vmax, 3.8))
            if rise_speed and a[1] <= -16.0 and b[1] < a[1]
            else max(rise_speed, min(vmax, 2.8))
            if rise_speed and -16.0 < a[1] <= 0.0 and b[1] < a[1]
            else rise_speed
        )
        span = max(abs(d) * (vmax / eff_rise if eff_rise and j == 1 and d < 0 and vmax > eff_rise else 1.0)
                   for j, d in enumerate(delta))
        if span <= 1e-9:
            continue
        seg_amax = max(amax, 25.0) if all(abs(d) <= 1e-9 for d in delta[:5]) else amax
        duration, ramp = eased(span, vmax, seg_amax)
        if segments and blend[i]:
            start -= min(segments[-1][3], ramp, blend_s)
            if len(segments) > 1:
                start = max(start, segments[-2][0] + segments[-2][1])
        segments.append((start, duration, delta, ramp))
        start += duration
    end = max((s + d for s, d, _, _ in segments), default=0.0)
    frames = []
    for k in range(1, max(1, math.ceil(end * fps)) + 1):
        t = min(k / fps, end)
        frames.append([w + sum(delta[j] * eased_progress(t - s, d, r) for s, d, delta, r in segments)
                       for j, w in enumerate(waypoints[0])])
    frames[-1] = list(waypoints[-1])
    return frames


def compile_smooth_chunk(waypoints, fps=30, vmax=4.25, blend_s=0.45,
                         rise_speed=2.6, amax=GUARD_ACCEL_UNITS_S2) -> list[list[float]]:
    """Compile pose or waypoint dictionaries into one eased, blended joint trajectory."""
    poses = []
    for waypoint in waypoints:
        if isinstance(waypoint, dict):
            pose = list(waypoint.get("pose", waypoint.get("pose_units", [])))
            if "gripper" in waypoint:
                pose = pose[:5] + [waypoint["gripper"]]
        else:
            pose = list(waypoint)
        if len(pose) != 6:
            raise ValueError("each waypoint must contain six joint units")
        if not poses or max(abs(a - b) for a, b in zip(poses[-1], pose)) > 1e-4:
            poses.append(pose)
    if len(poses) < 2:
        return [list(poses[-1])] if poses else []
    # Grasp and release corners must finish before the next body move starts.
    blend = [False] + [poses[i - 1][5] == poses[i][5] == poses[i + 1][5]
                       for i in range(1, len(poses) - 1)] + [False]
    return flow(poses, fps=fps, vmax=vmax, blend=blend,
                blend_s=blend_s, rise_speed=rise_speed, amax=amax)


def upgrade_linear_chunk(frames, fps=30, vmax=4.25, blend_s=0.40,
                         rise_speed=2.6, amax=GUARD_ACCEL_UNITS_S2) -> list[list[float]]:
    """Find direction changes in a dense linear chunk and recompile its corners."""
    if len(frames) < 2:
        return [list(frame) for frame in frames]
    corners = [frames[0]]
    previous = [b - a for a, b in zip(frames[0], frames[1])]
    for i in range(1, len(frames) - 1):
        step = [b - a for a, b in zip(frames[i], frames[i + 1])]
        prev_size, size = max(map(abs, previous)), max(map(abs, step))
        if prev_size and size and (
            max(abs(a / prev_size - b / size) for a, b in zip(previous, step)) > 0.15
            or abs(size - prev_size) > 0.25 * max(size, prev_size)
        ):
            corners.append(frames[i])
        previous = step
    corners.append(frames[-1])
    return compile_smooth_chunk(corners, fps=fps, vmax=vmax, blend_s=blend_s,
                                rise_speed=rise_speed, amax=amax)


def receding_horizon_splice(active_queue: list, current_pose: list, next_frames: list, fps: int,
                            blend_s: float = 0.25, vmax: float = 5.0) -> list:
    """Splice `next_frames` into an in-flight `active_queue` over a receding window of `blend_s` seconds
    without decelerating to a dead stop at the switch point (D-1014)."""
    if not next_frames:
        return [list(f) for f in active_queue]
    if not active_queue:
        return [list(f) for f in next_frames]
    window = max(1, min(len(active_queue), round(blend_s * fps)))
    head = [list(f) for f in active_queue[:window]]
    anchor = head[-1]
    step_limit = vmax / fps
    if any(abs(a - b) > step_limit + 1e-3 for a, b in zip(anchor[:5], next_frames[0][:5])):
        bridge = retime([list(f) for f in next_frames], fps, vmax=min(vmax, 4.5), start=anchor)
        return blend_chunks([list(current_pose)] + head, bridge, fps, blend_s=blend_s, vmax=vmax)[1:]
    return blend_chunks([list(current_pose)] + head, [list(f) for f in next_frames], fps,
                        blend_s=blend_s, vmax=vmax)[1:]


class TemporalChunkEnsembler:
    """Exponential temporal action ensembler (w_i = exp(-coeff * i), ACT policy parity, D-1014)
    with per-tick kinodynamic velocity clamping under the native guard limit."""

    def __init__(self, coeff: float = 0.01, vmax: float = 5.0, fps: int = 30) -> None:
        self.coeff = float(coeff)
        self.vmax = float(vmax)
        self.fps = int(fps)
        self._chunks: list[tuple[int, list[list[float]]]] = []
        self._last: list[float] | None = None

    def reset(self, pose: list[float] | None = None) -> None:
        self._chunks.clear()
        self._last = list(pose) if pose is not None else None

    def push(self, chunk: list[list[float]]) -> None:
        if chunk:
            self._chunks.append((0, [list(f) for f in chunk]))

    def step(self, fallback: list[float] | None = None) -> list[float]:
        active: list[tuple[int, list[list[float]]]] = []
        samples: list[tuple[float, list[float]]] = []
        for age, frames in self._chunks:
            if age < len(frames):
                weight = math.exp(-self.coeff * age)
                samples.append((weight, frames[age]))
                if age + 1 < len(frames):
                    active.append((age + 1, frames))
        self._chunks = active
        if not samples:
            out = list(fallback if fallback is not None else (self._last or [0.0] * 6))
            self._last = list(out)
            return out
        total_w = sum(w for w, _ in samples)
        blended = [sum(w * frame[j] for w, frame in samples) / total_w for j in range(len(samples[0][1]))]
        if self._last is not None and self.fps > 0:
            max_step = self.vmax / self.fps
            blended = [
                prev + max(-max_step, min(max_step, target - prev)) if j < 5 else target
                for j, (prev, target) in enumerate(zip(self._last, blended))
            ]
        self._last = list(blended)
        return blended


__all__ = [
    "GUARD_ACCEL_UNITS_S2", "TemporalChunkEnsembler", "blend_chunks",
    "compile_smooth_chunk", "eased", "eased_progress", "flow", "progress",
    "receding_horizon_splice", "retime", "smooth", "trapezoid",
    "upgrade_linear_chunk",
]

if __name__ != "omx_adapter.motion_profile":
    from omx_adapter import motion_profile as _installed

    globals().update({name: getattr(_installed, name) for name in __all__})

