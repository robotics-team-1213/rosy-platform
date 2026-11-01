"""Pure joint-space motion through waypoints under the guard's teacher-mode limits (D-872).

Straight segments joined at corners turned direction in one frame. The guard's 10 deg/s^2 then rounded
each corner on its own, lagging the frames, and the lag read like pressing on something. Here each segment
is a trapezoid synchronised to its slowest joint. At a corner marked for blending, the next segment starts
while this one is still decelerating (overlap capped at `blend_s`), so velocity never jumps and the corner
is cut by well under a unit. Unmarked waypoints are passed at rest, exactly: grasp, release and goal poses.
"""
from __future__ import annotations

import math

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
    """The same path (a planner's IK frames along a vertical line) at a trapezoid speed: it eases out of
    rest and into rest instead of starting and stopping at full speed. `start` is the pose before frames[0]."""
    path = [list(start)] + [list(f) for f in frames] if start is not None else [list(f) for f in frames]
    if len(path) < 2:
        return [list(f) for f in frames]
    lengths = [0.0]
    for a, b in zip(path, path[1:]):
        lengths.append(lengths[-1] + max(abs(y - x) for x, y in zip(a, b)))
    total = lengths[-1]
    if total <= 0:
        return [list(path[-1])]
    duration, ramp = trapezoid(total, vmax, amax)
    out, i = [], 0
    for k in range(1, max(1, math.ceil(duration * fps)) + 1):
        target = total * progress(min(k / fps, duration), duration, ramp)
        while i < len(lengths) - 2 and lengths[i + 1] < target:
            i += 1
        span = lengths[i + 1] - lengths[i]
        w = 0.0 if span <= 0 else (target - lengths[i]) / span
        out.append([p + (q - p) * w for p, q in zip(path[i], path[i + 1])])
    out[-1] = list(path[-1])
    return out


def eased(distance: float, vmax: float, amax: float) -> tuple[float, float]:
    """(duration, ramp time) of a rest-to-rest move whose speed rises and falls along a half cosine: the
    acceleration starts and ends at zero and peaks at `amax`. A trapezoid's acceleration steps from 0 to amax in
    one tick (jerk 110 units/s^3 at 30 fps, 12 here), a kick the guard's chaser and the servo both answer."""
    if distance <= 0:
        return 0.0, 0.0
    ramp = math.pi / 2 * vmax / amax
    if distance < vmax * ramp:  # never reaches vmax: peak speed sqrt(2 d a / pi)
        ramp = math.pi / 2 * math.sqrt(2 * distance * amax / math.pi) / amax
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
        # stretch the rising lift's distance so the shared profile moves it no faster than rise_speed
        span = max(abs(d) * (vmax / rise_speed if rise_speed and j == 1 and d < 0 and vmax > rise_speed else 1.0)
                   for j, d in enumerate(delta))
        duration, ramp = eased(span, vmax, amax)
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
