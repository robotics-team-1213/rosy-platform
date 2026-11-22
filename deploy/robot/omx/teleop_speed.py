"""Stepped speed of a full-arm Leader teleop / recording session (W14, user decision 2026-11-21).

A person at the bench raises the stage in <prep>/teleop-speed-<arm>.json = {"stage": 30|45|60} (no redeploy); anything else, no file or an
unreadable one is the current behaviour (follower caps untouched, FULL_TRACK_DEG_S, ACCEL_DEG_S2). Only a session that follows a Leader with the
whole arm uses it (record_session --teleop-stage: never body-only, chunk, replay/teacher or bimanual); the caps of every other session are not touched.

What a stage fixes (the 5 degree following error, LEAD_DEG 3, braking, stall hold, 100 degrees, PWM and current limits stay as they are):
  tracking limit      = the stage, deg/s
  servo profile vel   = the smallest raw value at least 10 % faster than the tracking limit: 1 raw = 0.229 rev/min = 0.229 * 6 = 1.374 deg/s
  servo profile acc   = reaches that velocity in 0.15 s: 1 raw = 214.577 rev/min^2 = 214.577 * 360 / 3600 = 21.4577 deg/s^2
  command accel limit = 30 / 45 / 60 -> 30 / 60 / 90 deg/s^2 (the full-arm ACCEL_DEG_S2; 10 without a stage)
  braking limit       = a reversal must overrun by under 3 degrees at every stage. Braking from v at a overruns about v^2/(2a) (the tick term
                        v*dt/2 is added with dt = 1/20 s, slower than the 30 Hz recorder, and 0.4 degree of margin): a = v^2 / (2 * (3 - 0.025 v - 0.4)),
                        never below the 200 deg/s^2 of the default 25 deg/s (30 -> 245, 45 -> 690, 60 -> 1640 deg/s^2). The command is not the arm:
                        a hard command brake costs nothing mechanical, the servo profile smooths it.
Both raw values lie inside the guard's admitted profile range (PROFILE_ACC 5..100, PROFILE_VEL 15..200), so that range is not widened. The session
writes them as SESSION_ONLY caps (found values are read first and restored at the end, as for the other session gains).
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

ENV = "ROSY_TELEOP_STAGE"
VEL_DEG_S_PER_RAW, ACC_DEG_S2_PER_RAW = 1.374, 21.4577
ACCEL = {30: 30.0, 45: 60.0, 60: 90.0, 90: 135.0, 120: 180.0}  # 90 and 120: prepared for a human's hand speed, not the default (W17)
ALIGN_DEG_S = 10.0  # start alignment rate of a staged full-arm session (1 degree/s elsewhere): 20 degrees apart = 2 s, not 20 s


def _raw(value: float) -> int:
    return math.ceil(round(value, 6))


def profile_vel_raw(stage: int) -> int:
    return _raw(stage * 1.1 / VEL_DEG_S_PER_RAW)


def profile_acc_raw(stage: int) -> int:
    return _raw(profile_vel_raw(stage) * VEL_DEG_S_PER_RAW / 0.15 / ACC_DEG_S2_PER_RAW)


def brake_deg_s2(stage: int) -> float:
    budget = max(0.35, 3 - 0.025 * stage - 0.4)  # from 90 deg/s the 1/20 s tick term alone is 2.25 degrees: the budget bottoms out, under 3 degrees is then not promised
    return float(max(200, 5 * math.ceil(round(stage**2 / (2 * budget) / 5, 6))))


def tau_s(stage: int) -> float:
    """Servo lag time constant for guarded_native_lag: 0.27 s measured at profile acceleration 8; the stages' own acceleration scales it (an estimate, see there)."""
    return round(0.27 * math.sqrt(8 / profile_acc_raw(stage)), 2)


STAGES = {s: {"track_deg_s": float(s), "profile_vel": profile_vel_raw(s), "profile_acc": profile_acc_raw(s), "accel_deg_s2": ACCEL[s],
              "brake_deg_s2": brake_deg_s2(s), "tau_s": tau_s(s), "align_deg_s": ALIGN_DEG_S} for s in ACCEL}


def valid(value):
    return value if type(value) is int and value in STAGES else None


def read_stage(path) -> int | None:
    """The declared stage, or None (no file, unreadable, any other value): the current behaviour, never a refusal."""
    try:
        return valid(json.loads(Path(path).read_text(encoding="utf-8-sig")).get("stage"))
    except (OSError, ValueError, AttributeError):
        return None


def stage_from_env(env=None) -> int | None:
    try:
        return valid(int((os.environ if env is None else env).get(ENV, "")))
    except ValueError:
        return None


def summary(stage) -> dict:
    """What status shows for the screen's parameter list; no stage = the default 25 deg/s with the caps file's own profile."""
    return {"stage": None, **{"track_deg_s": 25.0, "accel_deg_s2": 10.0, "brake_deg_s2": 200.0, "align_deg_s": 1.0}} if stage is None else {"stage": stage, **STAGES[stage]}


def apply_to_caps(caps: dict, stage: int) -> dict:
    """caps as load_caps returns them ({motor: {name: value}}) with the stage's profile on every follower motor; the input is not changed."""
    row = STAGES[stage]
    return {motor: {**cap, "profile_vel": row["profile_vel"], "profile_acc": row["profile_acc"]} for motor, cap in caps.items()}
