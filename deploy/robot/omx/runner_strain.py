"""The chunk runner's holds below the guard (moved out of chunk_runner.py at its 600-line cap, 2026-11-09).

`strained`: a load-bearing joint pushing with a rising lag, or a blocked wrist roll. `shed`: while the guard holds an
overloaded joint (NativeJointMotion.held), the XL430 shoulder lift and elbow carry the load off it toward the fold,
each stopping at its own STRAIN_LAG (the cell_unwedge way: no wrist command)."""
from __future__ import annotations

from omx_adapter.chunk_library import NAMES

MOTORS = [n.split(".")[0] for n in NAMES]
# Strain, in every other chunk (goto, park, lift), where normal travel lags up to ~2.6 units: hold when a load-bearing
# joint lags STRAIN_LAG, its lag rose STRAIN_RISE over STRAIN_TICKS ticks and the guard's 5 Hz PWM is at STRAIN_PWM of its cap.
# Real strains (2026-10-27): shoulder 2.4 -> 4.7 deg at 263 -> 516 of 600 in 0.7 s, a wrist on the wall at 55-86 %.
# The guard brakes at 10 deg/s^2 (0.65 deg on at RISE_SPEED 2), so 2.2 units (4.0 deg) still stops short of its 5.
STRAIN_LAG, STRAIN_RISE, STRAIN_TICKS, STRAIN_PWM = 2.2, 0.25, 6, 0.5
# A blocked wrist roll pushes at low PWM (arm_a dead at 28 % of its cap, 4 times on 2026-11-01), so the PWM test
# never fires. Its travel lag saws up to ~1.6 going negative while it keeps moving (arm_b's "stalls" at -13 and 9.89,
# 8 of 8, 2026-11-06), so a rising lag holds at ROLL_BLOCK_LAG only once ROLL_STILL_TICKS show it still, or at STRAIN_LAG.
ROLL_BLOCK_LAG, ROLL_STILL, ROLL_STILL_TICKS = 1.5, 0.3, 15
SHED = ("shoulder_lift", "elbow_flex")


def strained(runner, sent, present):
    """(motor, lag, pwm, cap) of a load-bearing joint whose lag keeps rising while it pushes, or of a wrist roll
    that stopped moving with its lag rising past ROLL_BLOCK_LAG at any PWM; else None."""
    lags = [abs(present[i] - sent[n]) if n in sent else 0.0 for i, n in enumerate(NAMES[:5])]
    runner.trend = (runner.trend + [[*lags, present[4]]])[-(ROLL_STILL_TICKS + 1):]
    if len(runner.trend) <= STRAIN_TICKS:
        return None
    motion = getattr(runner.robot, "motion", None)  # the guard's own PWM sample: no extra bus read
    pwm, limits = getattr(motion, "effort_pwm", None) or {}, getattr(motion, "pwm_limits", None) or {}
    first, middle = runner.trend[-STRAIN_TICKS - 1], runner.trend[-STRAIN_TICKS // 2 - 1]
    for i, motor in enumerate(MOTORS[:4]):
        rising = first[i] < middle[i] < lags[i] and lags[i] - first[i] >= STRAIN_RISE
        pushing = motor not in pwm or motor not in limits or abs(pwm[motor]) >= STRAIN_PWM * limits[motor]
        if lags[i] >= STRAIN_LAG and rising and pushing:
            return motor, lags[i], pwm.get(motor), limits.get(motor)
    path = [row[5] for row in runner.trend]
    still = len(path) > ROLL_STILL_TICKS and max(path) - min(path) < ROLL_STILL
    if (first[4] < middle[4] < lags[4] and lags[4] >= ROLL_BLOCK_LAG and lags[4] - first[4] >= STRAIN_RISE
            and (still or lags[4] >= STRAIN_LAG)):
        return MOTORS[4], lags[4], pwm.get(MOTORS[4]), limits.get(MOTORS[4])
    return None


def shed(target, present, sent, home, step):
    """One tick of load shedding: SHED joints step toward `home` by at most `step`; the rest stay."""
    out = list(target)
    for name in SHED:
        i = MOTORS.index(name)
        if abs(present[i] - sent.get(f"{name}.pos", target[i])) < STRAIN_LAG:
            out[i] += max(-step, min(step, home[i] - out[i]))
    return out
