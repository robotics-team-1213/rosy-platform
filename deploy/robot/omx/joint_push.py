"""A joint pushing against something it cannot move, seen in the runner's 1 Hz health samples.

arm_b, 2026-11-03 13:27: the jaws closed on a box edge while marking at the hover, the park folded home with the box
hanging from them and the box wedged the elbow 11 counts (1 deg) short of home. That is under the stall test's
4 units and outside any chunk, so nothing watched: the elbow's integral wound its PWM 261 -> 476 in 18 s at a
standstill and the motor latched an overload (hw_error 32) that only a reboot clears. Normal holds sit flat
(home 30, an extended hover swinging -20..-180); a wind-up climbs every sample. The thresholds are cell_params
(`windup.*`), measured from the field health logs with push_replay.py; rerun it on new logs before changing them.
"""
import cell_params as prm

STILL = 0.3            # units between two samples: not moving
REST_GAP = 0.5         # units short of a still target
REST_SAMPLES = 4       # 1 Hz samples: three rises
MOTORS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def windup(target, present, pwm):
    """The |PWM| rise of one joint over equal-length sample lists when it is still, short of a still target and
    climbs every sample; else 0."""
    effort = [abs(v) for v in pwm]
    if (max(target) - min(target) < STILL and max(present) - min(present) < STILL
            and abs(target[-1] - present[-1]) >= REST_GAP and all(a < b for a, b in zip(effort, effort[1:]))):
        return effort[-1] - effort[0]
    return 0


def pushing(samples, limits=None, jaws=False, params=None):
    """samples: (target, present, pwm) per health sample, oldest first. (motor, reason) of a load-bearing joint whose
    PWM winds up at a standstill short of its target, or, with `jaws`, of jaws stopped short at load; else None."""
    cap = lambda motor: (limits or {}).get(motor) or 300  # noqa: E731  the session baseline cap
    rise, share, jaw_share = (prm.get(params, f"windup.{k}") for k in ("rest_rise", "rest_pwm", "jaw_pwm"))
    window = samples[-REST_SAMPLES:]
    for i, motor in enumerate(MOTORS[:4]):
        if len(window) < REST_SAMPLES:
            break
        target, present, pwm = ([s[k][i] for s in window] for k in range(3))
        if windup(target, present, pwm) >= rise and abs(pwm[-1]) >= share * cap(motor):
            return motor, (f"{motor} still {abs(target[-1] - present[-1]):.1f} units short, PWM winding up "
                           f"{abs(pwm[0])} -> {abs(pwm[-1])} of {cap(motor)}: pushing against something")
    if jaws and len(samples) >= 2:
        (_, before, pwm0), (target, present, pwm1) = samples[-2:]
        gap = abs(present[5] - target[5])
        if (abs(present[5] - before[5]) < STILL and gap > prm.get(params, "windup.jaw_gap")
                and min(abs(pwm0[5]), abs(pwm1[5])) >= jaw_share * cap("gripper")):
            return "gripper", (f"the jaws stopped {gap:.1f} units short at PWM {pwm1[5]} of {cap('gripper')}: "
                               "something is in them")
    return None
