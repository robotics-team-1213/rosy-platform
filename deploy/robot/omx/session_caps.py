"""A recording session's follower caps file: commissioning caps and the session-only servo gains (2026-10-26)."""
from __future__ import annotations

import json
from pathlib import Path

from guarded_native import PROFILE_ACC, PROFILE_VEL
from joint_tune import CAP_MAX, FOLLOWER

PWM_MAX = CURRENT_MAX = CAP_MAX  # first sessions stay well below the hardware maximum (885 / 1750)
P_GAIN_MAX = 1600  # the elbow runs at 1500; higher gains need their own commissioning
# I gain: without it a loaded joint stops short of its goal with PWM to spare (two_arm_config.follower_gains). Both
# arms' wrists lagged >5 deg under load on 2026-10-31/11-01 at PWM 38-55 % and the guard ended the sessions.
I_GAIN_MAX = 1600
# The XL430 shoulder and elbow carry the arm at reach: at 0.23 m the shoulder used 78 % of PWM 300 and fell 5 deg
# behind (2026-10-26, user decision: higher than 400). 600 is 68 % of their 885; the XL330 wrist keeps CAP_MAX.
XL430_PWM_MAX = 600
# D-951 6: the OMX-AI follower's servo tuning sits under the site caps file, a robot's operating profile `servo` on
# top. Gains and profiles only: PWM and current stay commissioning caps in the caps file.
MODEL_TUNING = Path(__file__).with_name("omx-ai-follower-tuning.json")
TUNING_SCHEMA = "rosy.omx-servo-tuning.v1"
TUNING_KEYS = {"p", "i", "acc", "vel"}


def load_tuning(raw, where: str) -> dict:
    """{follower ID: {p|i|acc|vel: value}}; load_caps checks the ranges once the layers are merged."""
    try:
        tuning = {int(k): v for k, v in raw.items()}
    except (AttributeError, TypeError, ValueError):
        tuning = None
    if tuning is None or not set(tuning) <= set(FOLLOWER) or not all(
            isinstance(v, dict) and set(v) <= TUNING_KEYS for v in tuning.values()):
        raise SystemExit(f"{where}: servo tuning names follower IDs with keys {sorted(TUNING_KEYS)} only")
    return tuning


def model_tuning(path: Path = MODEL_TUNING) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema") != TUNING_SCHEMA:
        raise SystemExit(f"{path.name}: schema {TUNING_SCHEMA} required")
    return load_tuning(document.get("motors"), path.name)


def robot_tuning(profile) -> dict:
    """The robot's own tuning from its operating profile `servo` (D-914); none without a profile."""
    if profile is None:
        return {}
    from cell_robot_profile import load

    return load_tuning(load(profile)["servo"], "operating profile servo")


def load_caps(path: Path, *, model=None, robot=None) -> dict:
    """The site caps file, over the model's tuning and under the robot's (motor and key at a time)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    caps = {int(k): v for k, v in raw.items()}
    if set(caps) != set(FOLLOWER):
        raise SystemExit(f"caps must name every follower ID {sorted(FOLLOWER)}")
    model, robot = model or {}, robot or {}
    caps = {motor: {**model.get(motor, {}), **cap, **robot.get(motor, {})} for motor, cap in caps.items()}
    for motor, cap in caps.items():
        xl330 = FOLLOWER[motor][0] == 1200
        allowed = {"pwm", "current", "p", "i", "acc", "vel"} if xl330 else {"pwm", "p", "i", "acc", "vel"}
        if not set(cap) <= allowed or "pwm" not in cap or ("acc" in cap) != ("vel" in cap):
            raise SystemExit(f"motor {motor}: caps keys must be {sorted(allowed)} with pwm, acc and vel together")
        pwm_max = PWM_MAX if xl330 else XL430_PWM_MAX
        if not (type(cap["pwm"]) is int and 1 <= cap["pwm"] <= pwm_max):
            raise SystemExit(f"motor {motor}: pwm 1..{pwm_max}")
        if "current" in cap and not (type(cap["current"]) is int and 1 <= cap["current"] <= CURRENT_MAX):
            raise SystemExit(f"motor {motor}: current 1..{CURRENT_MAX}")
        for key, (low, high) in (("p", (1, P_GAIN_MAX)), ("i", (0, I_GAIN_MAX)), ("acc", PROFILE_ACC), ("vel", PROFILE_VEL)):
            if key in cap and not (type(cap[key]) is int and low <= cap[key] <= high):
                raise SystemExit(f"motor {motor}: {key} {low}..{high}")
    names = {"pwm": "pwm_limit", "current": "current_limit", "p": "p_gain", "i": "i_gain", "acc": "profile_acc",
             "vel": "profile_vel"}
    return {motor: {names[key]: value for key, value in cap.items()} for motor, cap in caps.items()}
