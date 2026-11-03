"""A joint pushing against something it cannot move, seen in the runner's 1 Hz health samples.

arm_b, 2026-11-03 13:27: the jaws closed on a box edge while marking at the hover, the park folded home with the box
hanging from them and the box wedged the elbow 11 counts (1 deg) short of home. That is under the stall test's
4 units and outside any chunk, so nothing watched: the elbow's integral wound its PWM 261 -> 476 in 18 s at a
standstill and the motor latched an overload (hw_error 32) that only a power cycle clears. Normal holds sit flat
(home 30, an extended hover swinging -20..-180); a wind-up climbs every sample.
"""
STILL = 0.3            # units between two samples: not moving
REST_GAP = 0.5         # units short of a still target
REST_SAMPLES, REST_RISE, REST_PWM = 4, 40, 0.4  # |PWM| climbing every sample, by 40 over 3 s, to 40 % of the cap
JAW_GAP, JAW_PWM = 2.0, 0.5  # jaws this far from their park target, still, at half their cap on two samples
MOTORS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


def pushing(samples, limits=None, jaws=False):
    """samples: (target, present, pwm) per health sample, oldest first. (motor, reason) of a load-bearing joint whose
    PWM winds up at a standstill short of its target, or, with `jaws`, of jaws stopped short at load; else None."""
    cap = lambda motor: (limits or {}).get(motor) or 300  # noqa: E731  the session baseline cap
    window = samples[-REST_SAMPLES:]
    for i, motor in enumerate(MOTORS[:4]):
        if len(window) < REST_SAMPLES:
            break
        target, present, pwm = ([s[k][i] for s in window] for k in range(3))
        effort = [abs(v) for v in pwm]
        if (max(target) - min(target) < STILL and max(present) - min(present) < STILL
                and abs(target[-1] - present[-1]) >= REST_GAP and all(a < b for a, b in zip(effort, effort[1:]))
                and effort[-1] - effort[0] >= REST_RISE and effort[-1] >= REST_PWM * cap(motor)):
            return motor, (f"{motor} still {abs(target[-1] - present[-1]):.1f} units short, PWM winding up "
                           f"{effort[0]} -> {effort[-1]} of {cap(motor)}: pushing against something")
    if jaws and len(samples) >= 2:
        (_, before, pwm0), (target, present, pwm1) = samples[-2:]
        gap = abs(present[5] - target[5])
        if (abs(present[5] - before[5]) < STILL and gap > JAW_GAP
                and min(abs(pwm0[5]), abs(pwm1[5])) >= JAW_PWM * cap("gripper")):
            return "gripper", (f"the jaws stopped {gap:.1f} units short of the park at PWM {pwm1[5]} of "
                               f"{cap('gripper')}: something is in them; free it before folding")
    return None
