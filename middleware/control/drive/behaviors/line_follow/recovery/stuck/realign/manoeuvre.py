"""D-607 8 REALIGN legs (PIVOT, or KTURN back then forward) on one sign-locked odom yaw target."""
from __future__ import annotations

import math

from core_features.line_follow.cue.odom_pivot import OdomPivot


class Manoeuvre:
    """One accepted REALIGN: leg pivot, or back then fwd; progress on odom yaw with the sign locked."""

    def __init__(self, req: dict, *, key, yaw_at_order: float, pose, now: float, rate: float,
                 speed: float) -> None:
        self.kind, self.turn_spot = req["kind"], req.get("turn_spot") is True
        angle = float(req["angle_rad"])
        if self.kind == "PIVOT":
            self.leg, self.twists, duration = "pivot", {"pivot": (0.0, rate)}, abs(angle) / rate
        else:
            back_r, fwd_r = float(req["back_radius_m"]), float(req["fwd_radius_m"])
            vb, vf = min(speed, rate * back_r), min(speed, rate * fwd_r)
            self.leg, self.back_m, self.start = "back", float(req["back_m"]), (pose.x, pose.y)
            self.twists = {"back": (-vb, vb / back_r), "fwd": (vf, vf / fwd_r)}
            # The reverse arc may already reach the target; the forward arc turns the rest.
            duration = self.back_m / vb + max(0.0, abs(angle) - self.back_m / back_r) * fwd_r / vf
        # OdomPivot's deadline is |angle| / rate + TIME_PAD_S: hand it the manoeuvre's mean yaw rate.
        self.yaw = OdomPivot(key=key, yaw_at_order=yaw_at_order, yaw_now=pose.yaw, angle_rad=angle,
                             rate=max(abs(angle), 1e-3) / max(duration, 1e-3), now=now)

    def step(self, now: float, pose, key) -> tuple[str, object]:
        """("move", (linear, angular)) | ("done", None) | ("fail", reason)."""
        verdict, sign = self.yaw.step(now, pose, key)
        if verdict != "turn":
            return verdict, sign
        if self.leg == "back" and math.hypot(pose.x - self.start[0], pose.y - self.start[1]) >= self.back_m:
            self.leg = "fwd"
        linear, angular = self.twists[self.leg]
        return "move", (linear, sign * angular)

    def view(self) -> dict:
        return {"kind": self.kind, "leg": self.leg, "turn_spot": self.turn_spot, **self.yaw.view()}
