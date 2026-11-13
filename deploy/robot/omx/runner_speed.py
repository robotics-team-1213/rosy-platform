"""How fast the chunk runner reads its queued frames (2026-11-13 speed/jitter panel).

`speed` is in [runner.speed_min, 1]; 1 is the compiled nominal speed. It only slows, so every streamed step stays
within what the plan, the guard (10 deg/s, 10 deg/s^2, D-911) and the contact allowance already accepted. Its signal is the
body tracking lag (present minus sent) against runner.pace_lag. The lag is what speed changes; jaw sway on the
2026-11-12/13 traces was uncorrelated with Z speed (r = +0.04..+0.13 arm_b), so sway does not drive it. Under half
the pace lag it reads at full speed, and at the pace lag at speed_min. It slews 0.02 per tick.

runner.speed_adapt 0 (default) is shadow mode: the speed is computed and reported (trace `s`, receipt `speed_low`)
but frames are read one per tick as before. A recording episode and the contact chunks (descend, grasp, release)
always read at nominal timing.
"""
from __future__ import annotations

import cell_params as prm

SLEW = 0.02  # per tick: 1 -> 0.4 in 1 s at 30 Hz, no step in the streamed speed
CONTACT_CHUNKS = ("descend", "grasp", "release")


def target_speed(lag: float, params=None) -> float:
    pace, low = prm.get(params, "runner.pace_lag"), prm.get(params, "runner.speed_min")
    ratio = lag / pace if pace > 0 else 0.0
    return max(low, min(1.0, 1.0 - (ratio - 0.5) * 2.0 * (1.0 - low)))


def take(runner) -> list:
    """The next raw target from `runner.queue` (non-empty) at the runner's adaptive speed; pops frames as it passes
    them. Updates runner.speed/speed_low and, between frames, returns the straight blend toward the next one."""
    want = target_speed(runner.lag, runner.params)
    runner.speed += max(-SLEW, min(SLEW, want - runner.speed))
    runner.speed_low = min(runner.speed_low, runner.speed)
    # contact chunks keep nominal timing: the contact allowance follows the sent step, so reading slower there
    # would move where a contact is detected (2026-11-13 panel round 5)
    contact = any(part.startswith(CONTACT_CHUNKS) for part in (runner.chunk or "").split(" -> "))  # splices too
    applied = prm.get(runner.params, "runner.speed_adapt") and not contact and not runner.recorder.active()
    if not applied:
        runner.speed_out = None
        return runner.queue.pop(0)
    # a new queue (run, goto, splice) or a target moved elsewhere (hold, damping): restart the blend from here
    if runner.speed_out is None or runner.target != runner.speed_out or runner.queue is not runner.speed_queue:
        runner.speed_base, runner.speed_phase, runner.speed_queue = list(runner.target or runner.queue[0]), 0.0, runner.queue
    runner.speed_phase += runner.speed
    while runner.speed_phase >= 1.0 and runner.queue:
        runner.speed_base, runner.speed_phase = runner.queue.pop(0), runner.speed_phase - 1.0
    if not runner.queue:
        runner.speed_out = None  # the last frame is reached exactly; the next chunk starts from the arm's target
        return list(runner.speed_base)
    f, nxt = runner.speed_phase, runner.queue[0]
    runner.speed_out = [b + f * (n - b) for b, n in zip(runner.speed_base, nxt)]
    return list(runner.speed_out)
