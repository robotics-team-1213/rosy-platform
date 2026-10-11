"""D-407 개정 / D-607 (2026-10-10): "5초 이상 같은 자리 혹은 제자리 답보".

ROS-free. The manager notes one sample per issued twist (odom pose + that twist). ``cause`` says whether
odom stood still over the report window (net move < half the URDF body length, |net yaw| < a limit) while
motion was commanded, or, with the creep rule on, crept < restuck_m in restuck_s.
"""
import math
from collections import deque

V_EPS, W_EPS = 0.003, 0.05  # an issued tick above either counts as commanded motion (|w| > 0.05 rad/s)
SHARE = 0.3                 # creep rule: commanded on at least this share of ticks


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
        if reason and reason != "tracking" and not reason.startswith("stuck_"):
            self.reason = reason  # the last HOLD / strategy reason, for the stuck detail

    def _still(self, now, win_s, max_m, max_yaw):
        new = self._s[-1] if self._s else None
        old = next((p for p in reversed(self._s) if p[0] <= now - win_s), None)
        if old is None or now - new[0] > 1.0:
            return False  # less odom than the window, or no recent sample: unknown, never a stuck
        moved = math.hypot(new[1] - old[1], new[2] - old[2])
        return moved < max_m and abs(new[3] - old[3]) < max_yaw

    def cause(self, now, win_s, max_m, max_yaw_deg, creep_s, creep_m):
        """None | "no_progress" | "dithering"; once fired it holds until odom shows progress again.

        creep_s None turns the creep rule off. One body length (2 * max_m) in the window is progress.
        """
        still = self._still(now, win_s, max_m, math.radians(max_yaw_deg))
        creep = creep_s is not None and self._still(now, creep_s, creep_m, math.inf)
        stuck = (still or creep) and self._still(now, win_s, 2 * max_m, math.inf)
        if not stuck:
            self.cause_now = None
        elif self.cause_now is None:
            win = [p for p in self._s if p[0] > now - (win_s if still else creep_s)]
            commanded = sum(abs(p[4]) > V_EPS or abs(p[5]) > W_EPS for p in win)
            if win and commanded >= (1 if still else SHARE * len(win)):
                flips = _flips((p[4] for p in win), V_EPS) + _flips((p[5] for p in win), W_EPS)
                self.cause_now = "dithering" if still and flips >= 2 else "no_progress"
        return self.cause_now
