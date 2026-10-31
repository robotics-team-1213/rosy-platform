"""A recording session's follower caps file: commissioning caps and the session-only servo gains (2026-10-26)."""
from __future__ import annotations

import json
from pathlib import Path

from guarded_native import PROFILE_ACC, PROFILE_VEL
from joint_tune import CAP_MAX, FOLLOWER

PWM_MAX = CURRENT_MAX = CAP_MAX  # first sessions stay well below the hardware maximum (885 / 1750)
P_GAIN_MAX = 1600  # the elbow runs at 1500; higher gains need their own commissioning
# The XL430 shoulder and elbow carry the arm at reach: at 0.23 m the shoulder used 78 % of PWM 300 and fell 5 deg
# behind (2026-10-26, user decision: higher than 400). 600 is 68 % of their 885; the XL330 wrist keeps CAP_MAX.
XL430_PWM_MAX = 600


def load_caps(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    caps = {int(k): v for k, v in raw.items()}
    if set(caps) != set(FOLLOWER):
        raise SystemExit(f"caps must name every follower ID {sorted(FOLLOWER)}")
    for motor, cap in caps.items():
        xl330 = FOLLOWER[motor][0] == 1200
        allowed = {"pwm", "current", "p", "acc", "vel"} if xl330 else {"pwm", "p", "acc", "vel"}
        if not set(cap) <= allowed or "pwm" not in cap or ("acc" in cap) != ("vel" in cap):
            raise SystemExit(f"motor {motor}: caps keys must be {sorted(allowed)} with pwm, acc and vel together")
        pwm_max = PWM_MAX if xl330 else XL430_PWM_MAX
        if not (type(cap["pwm"]) is int and 1 <= cap["pwm"] <= pwm_max):
            raise SystemExit(f"motor {motor}: pwm 1..{pwm_max}")
        if "current" in cap and not (type(cap["current"]) is int and 1 <= cap["current"] <= CURRENT_MAX):
            raise SystemExit(f"motor {motor}: current 1..{CURRENT_MAX}")
        for key, (low, high) in (("p", (1, P_GAIN_MAX)), ("acc", PROFILE_ACC), ("vel", PROFILE_VEL)):
            if key in cap and not (type(cap[key]) is int and low <= cap[key] <= high):
                raise SystemExit(f"motor {motor}: {key} {low}..{high}")
    names = {"pwm": "pwm_limit", "current": "current_limit", "p": "p_gain", "acc": "profile_acc", "vel": "profile_vel"}
    return {motor: {names[key]: value for key, value in cap.items()} for motor, cap in caps.items()}
