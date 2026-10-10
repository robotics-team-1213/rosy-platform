"""D-407 개정 2026-10-10 ("5초 이상 같은 자리 혹은 제자리 답보"), ROS-free: one sample per issued twist (odom + twist).
Stuck = odom still (< half the URDF body length, |net yaw| < limit) over the window, or < restuck_m in restuck_s, under command."""
import math
from collections import deque

V_EPS, W_EPS, SHARE = 0.003, 0.05, 0.3  # a commanded tick moves above these; >= SHARE of ticks commanded


def _flips(values, eps):
    signs = [v > 0 for v in values if abs(v) > eps]
    return sum(a != b for a, b in zip(signs, signs[1:]))


class ProgressWatch:
    def __init__(self):
        self.reset()

    def reset(self, key=None):
        self._s, self._key, self.cause_now, self.reason = deque(), key, None, None

    def note(self, t, key, x, y, yaw, v, w, reason, keep_s):
        if key != self._key or (self._s and t <= self._s[-1][0]):
            self.reset(key)  # new odom run or clock step: travel across it is unknown
        s = self._s
        u = yaw if not s else s[-1][3] + math.remainder(yaw - s[-1][3], math.tau)  # unwrapped yaw
        s.append((t, x, y, u, v, w))
        while len(s) > 1 and s[1][0] <= t - keep_s:
            s.popleft()  # keeps one sample at or before the oldest window start
        self.reason = reason if reason and reason != "tracking" and not reason.startswith("stuck_") else self.reason

    def _still(self, now, win_s, max_m, max_yaw):
        new = self._s[-1] if self._s else None
        old = next((p for p in reversed(self._s) if p[0] <= now - win_s), None)
        if old is None or now - new[0] > 1.0:
            return False  # less odom than the window, or no recent sample: unknown, never a stuck
        return math.hypot(new[1] - old[1], new[2] - old[2]) < max_m and abs(new[3] - old[3]) < max_yaw

    def cause(self, now, win_s, max_m, deg, drift_s, drift_m):  # deg: max |net yaw|; drift_s falsy = no creep rule
        still, drift = self._still(now, win_s, max_m, math.radians(deg)), bool(drift_s) and self._still(now, drift_s, drift_m, math.inf)
        stuck = (still or drift) and self._still(now, win_s, 2 * max_m, math.inf)  # a body length per window: progress
        self.cause_now = self.cause_now if stuck else None
        if self.cause_now is None and stuck:
            win = [p for p in self._s if p[0] > now - (win_s if still else drift_s)]
            if sum(abs(p[4]) > V_EPS or abs(p[5]) > W_EPS for p in win) >= (1 if still else SHARE * len(win) or 1):
                flips = _flips((p[4] for p in win), V_EPS) + _flips((p[5] for p in win), W_EPS)
                self.cause_now = "dithering" if still and flips >= 2 else "no_progress"
        return self.cause_now
