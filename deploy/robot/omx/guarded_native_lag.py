"""Servo lag model of a full-arm Leader teleop session with a speed stage (W17), and the follow checks that use it.

Why: "the command never leads the arm by more than 3 degrees" and "5 degree following error against the last command" read the servo's normal lag
(speed x tau) as an error, so the real speed could never pass 3/tau (about 10 deg/s at tau 0.27 s) whatever the stage said, and a Leader moved at a human's
speed ran 100 degrees ahead and cut the torque of an extended arm.

Model (per joint, in motor ticks): the servo answers the goal it was last given as a first-order lag with time constant tau, its speed limited by the
session's profile velocity:  x += clip((goal - x) * (1 - exp(-dt / tau)), +-vmax * dt),  goal = the integer last written, x seeded at the present position.
tau: measured 0.27 s with profile velocity 20 / acceleration 8 (2026-11-21 22:10 session); for the stages' profiles it is NOT yet fitted: the estimate
tau = 0.27 * sqrt(8 / profile_acc_raw) (the servo's own acceleration dominates the lag) is in teleop_speed.STAGES and must be refitted from per-tick
command/present logs of a staged session (the 0.9 s samples of session1953-lag.txt cannot resolve it). A wrong tau is not dangerous: the allowed gap
below is 5 degrees, a model 30 % off is only 0.3 x speed x tau (about 3 degrees at 60 deg/s) and the tests run with +-30 %.

Checks (staged full-arm sessions only; every other session keeps the legacy checks):
  - following error: a present position more than 5 degrees behind the model's path (a blocked, jammed or pushed-back joint), or more than 5 degrees past
    the goal, stops as before; between the path and the goal is fine (an arm with less lag than tau); and |present - last command| keeps a hard bound of FOLLOW_HARD_DEG;
  - lead: the command may lead the PRESENT position by LEAD_DEG + tau * |measured speed|. Moving freely at v the lag is v * tau, so the 3 degrees of slack stay;
    a blocked joint measures 0 deg/s, the allowed lead is 3 degrees again and the push is Kp * 3 degrees exactly as before (not Kp * (3 + v * tau)).
  - a Leader more than 100 degrees ahead while following is not a torque cut (see follows_far).
"""
from __future__ import annotations

import math

from guarded_device import BODY, TICKS_PER_DEGREE

FOLLOW_DEG = 5.0  # |present - expected|
FOLLOW_HARD_DEG = 15.0  # |present - last command|, whatever the model says


class LagModel:
    def __init__(self, tau_s: float, vmax_deg_s: float):
        self.tau_s, self.vmax = tau_s, vmax_deg_s * TICKS_PER_DEGREE
        self.hard_deg = max(FOLLOW_HARD_DEG, 3.0 + tau_s * vmax_deg_s + 2.0)
        self.x, self.t, self.prev, self.speed, self.delta, self.blocked_since = {}, None, {}, {}, {}, {}

    def seed(self, present: dict, now: float) -> None:
        self.x, self.t, self.prev, self.speed, self.delta, self.blocked_since = {n: float(v) for n, v in present.items()}, now, dict(present), {}, {}, {}

    def advance(self, goals: dict, now: float) -> dict:
        dt = 0.0 if self.t is None else now - self.t
        if dt > 0:
            gain = 1.0 - math.exp(-dt / self.tau_s)
            for name, goal in goals.items():
                step = (goal - self.x[name]) * gain
                limit = self.vmax * dt
                self.x[name] += max(-limit, min(limit, step))
            self.t = now
        return self.x

    def measure(self, present: dict, now: float, dt: float) -> None:
        """Speed of the arm from two successive samples, in deg/s (unsmoothed: a blocked arm reads 0 at once)."""
        if self.prev:
            self.delta = {n: present[n] - self.prev[n] for n in present if n in self.prev}
        if dt > 0 and self.prev:
            self.speed = {n: abs(present[n] - self.prev[n]) / dt / TICKS_PER_DEGREE for n in present if n in self.prev}
        self.prev = dict(present)

    def lead_ticks(self, name: str, lead_deg: float) -> float:
        return (lead_deg + self.tau_s * self.speed.get(name, 0.0)) * TICKS_PER_DEGREE


def check_following(motion, current: dict, now: float) -> None:
    """The following-error stop of prepare(): the model's for a staged full-arm session, otherwise the legacy |present - last written integer| > 5 degrees."""
    lag = motion.lag
    expected = None
    if lag is not None:
        expected = lag.advance({n: (motion.sent[n] if motion.sent is not None and n in motion.sent else int(motion.command[n])) for n in motion.active}, now)
        lag.measure(current, now, 0.0 if motion.last_time is None else now - motion.last_time)
        prev_ref = motion.prev_mapped if getattr(motion, "prev_mapped", None) is not None else motion.prev_target
        for name in [n for n in motion.far if prev_ref is None or abs(prev_ref[n] - current[n]) < 100 * TICKS_PER_DEGREE]:
            motion.far.discard(name)  # back within 100 degrees: said again if it happens again
    for name in motion.active if lag is not None else (BODY if motion.teacher else motion.active):
        sent = motion.sent[name] if motion.sent is not None and name in motion.sent else int(motion.command[name])  # what was written
        if lag is None:
            if abs(current[name] - sent) > FOLLOW_DEG * TICKS_PER_DEGREE + 1e-9:
                raise ValueError(f"{name}: following error >5 motor degrees; command={sent}, current={current[name]}")
        elif not _inside(current[name], expected[name], sent):
            since = lag.blocked_since.get(name)
            if lag.delta.get(name) == 0 and (since is None or now - since <= 2.0 * lag.tau_s + 1e-9):
                if since is None:
                    lag.blocked_since[name] = now  # bounded window while rate-limited retraction pulls excess lead back to current + 3
            else:
                raise ValueError(f"{name}: following error >5 motor degrees from the servo model; command={sent}, expected={expected[name]:.0f}, current={current[name]}")
        else:
            lag.blocked_since.pop(name, None)
        if lag is not None and abs(current[name] - sent) > lag.hard_deg * TICKS_PER_DEGREE + 1e-9:
            raise ValueError(f"{name}: following error >{lag.hard_deg:g} motor degrees; command={sent}, current={current[name]}")


def _inside(present: float, expected: float, sent: float) -> bool:
    """present within FOLLOW_DEG of the model's path, on the side of the goal up to the goal itself plus FOLLOW_DEG: an arm that is FASTER than the model
    (less lag than tau) is not an error; one that stays behind the path (blocked, jammed, pushed back) is."""
    margin = FOLLOW_DEG * TICKS_PER_DEGREE + 1e-9
    low, high = (expected - margin, sent + margin) if sent >= expected else (sent - margin, expected + margin)
    return low <= present <= high


def follows_far(motion, name: str, target: dict) -> bool:
    """True when a Leader 100 degrees or more from the arm is FOLLOWED instead of cutting the torque: a staged full-arm session that is already tracking,
    and the target did not jump 100 degrees in one tick (that, and a difference at the start, still stop as before). The command is rate-limited
    (track limit, acceleration) and its lead over the arm bounded (LEAD_DEG + tau * speed), so the arm approaches at the limit speed with the same push as any
    following; cutting the torque of an extended arm would drop it. Said once per joint."""
    prev_ref = motion.prev_mapped if getattr(motion, "prev_mapped", None) is not None else motion.prev_target
    if motion.lag is None or not motion.tracking or prev_ref is None:
        return False
    if abs(target[name] - prev_ref[name]) >= 100 * TICKS_PER_DEGREE - 1e-9:
        return False
    if name not in motion.far:
        motion.far.add(name)
        print(f"{motion.label}: {name} is 100 degrees or more behind the Leader: following at the speed limit, torque stays ON - wait for the Leader to be reached", flush=True)
    return True
