"""Two-stage descent: faster far from the contact, today's pace over the last few mm (2026-11-13 panel round 6).

The contact guard adds an allowance that follows the streamed step (chunk_runner_guards.vel_allowance) and trips
on consecutive ticks over its bound. So the descent keeps today's single-stage pace `v_near` over the last
`near_m` above the target and arrives at that zone at exactly `v_near`. A contact is then judged as before.
Above the zone it cruises at `v_far`. Every speed change is a half cosine (peak acceleration `amax`, no
acceleration step), so the streamed path stays smooth.
"""
from __future__ import annotations

import math

from motion_profile import GUARD_ACCEL_UNITS_S2, retime


def _speeds(v_far, v_near, s_split, total, amax):
    """[(duration, v_from, v_to)] covering exactly s_split then total - s_split, or None when a zone is too short."""
    def ramp(va, vb):
        # motion_profile.eased's rule exactly (amax scales with vmax/4.25, no floor), so the near stop matches today's retime
        a = amax * min(1.0, max(va, vb) / 4.25) if amax <= GUARD_ACCEL_UNITS_S2 else amax
        t = math.pi * abs(vb - va) / (2 * a)
        return t, (va + vb) / 2 * t
    t1, d1 = ramp(0.0, v_far)
    t2, d2 = ramp(v_far, v_near)
    t3, d3 = ramp(v_near, 0.0)
    far_cruise, near_cruise = s_split - d1 - d2, total - s_split - d3
    if far_cruise < 0 or near_cruise < 0:
        return None
    return [(t1, 0.0, v_far), (far_cruise / v_far, v_far, v_far), (t2, v_far, v_near),
            (near_cruise / v_near, v_near, v_near), (t3, v_near, 0.0)]


def two_stage(frames: list, fps: int, v_far: float, v_near: float, near_index: int,
              amax: float = GUARD_ACCEL_UNITS_S2, start=None) -> list:
    """`frames` (an IK line, evenly spaced along the descent) retimed so the path up to frames[near_index] runs at
    up to `v_far` and the rest at `v_near`, entering it at `v_near`. Falls back to retime at `v_near` when
    v_far <= v_near or either zone is too short for its ramps. `start` is the pose before frames[0]."""
    path = [list(start)] + [list(f) for f in frames] if start is not None else [list(f) for f in frames]
    lengths = [0.0]
    for a, b in zip(path, path[1:]):
        lengths.append(lengths[-1] + max(abs(y - x) for x, y in zip(a, b)))
    split = near_index + (1 if start is not None else 0)
    plan = (_speeds(v_far, v_near, lengths[split], lengths[-1], amax)
            if v_far > v_near and 0 < split < len(lengths) - 1 else None)
    if plan is None:
        return retime(frames, fps, v_near, amax, start=start)
    # position along the path at time t: each piece moves (va + vb)/2 * T, eased by a half cosine
    edges, s, t = [], 0.0, 0.0
    for dur, va, vb in plan:
        edges.append((t, dur, va, vb, s))
        t, s = t + dur, s + (va + vb) / 2 * dur
    end, out, i = t, [], 0
    for k in range(1, max(1, math.ceil(end * fps)) + 1):
        tk = min(k / fps, end)
        t0, dur, va, vb, s0 = next(e for e in reversed(edges) if e[0] <= tk + 1e-12)
        u = min(tk - t0, dur)
        # integral of va + (vb - va) * (1 - cos(pi u / dur)) / 2
        target = s0 + va * u + (vb - va) * (u / 2 - (dur / (2 * math.pi)) * math.sin(math.pi * u / dur) if dur else 0.0)
        while i < len(lengths) - 2 and lengths[i + 1] < target:
            i += 1
        span = lengths[i + 1] - lengths[i]
        w = 0.0 if span <= 0 else min(1.0, (target - lengths[i]) / span)
        out.append([p + (q - p) * w for p, q in zip(path[i], path[i + 1])])
    out[-1] = list(path[-1])
    return out
