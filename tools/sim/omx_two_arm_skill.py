"""Sub-skills of a two-arm plan step: one short part a policy owns while the teacher's IK does the rest, under the real arm's errors.

Whole steps and whole tasks scored 0/63 (two-arm ACT rounds 1-4, link5 came down 0.04 rad low); the Isaac release corrector learned one
short phase 8/9 where IK got 0/9 (2026-10-30). The privileged teacher runs a step up to the sub-skill in true joint angles; from there the
model, or for "ik" the same IK, commands in the angles the arm reports, which are off by a per-seed joint-zero error (the 2026-11-09 twin
fit found 1-4 deg), with per-joint servo lag (0.10-0.34 s measured, one 0.16 s in the plain sim). omx_two_arm_policy.py records and trains;
this module says what a sub-skill is and judges it. MuJoCo answers geometry only (D-947); no learned policy reaches the real arm (D-793).
"""
import functools
import json

import numpy as np

import omx_two_arm_sites as sites
import omx_two_arm_tasks as tasks
import omx_two_arm_teacher as teaching

# phases of omx_two_arm_teacher.step_gen each sub-skill owns, its language input, and how it is judged
SKILLS = {
    "grasp": dict(phases=("grasp", "close", "lift"), say="{arm}: grasp the container at {source} and lift it", judge="held"),
    "release": dict(phases=("lower", "release", "retreat"), say="{arm}: set the container down on {target} and let go", judge="placed"),
}
SKILL_PASS = .9  # 18 of 20, the sim acceptance bar (2026-11-05 decision-vla plan)
LAG_S = (.10, .34)  # real servo lag per joint, command to arrival (twin 2026-11-09); lag ~ 0.16 s x 40 / gain in the sim


def prompt(step, skill):
    """SmolVLA's language input: which arm and which site (ACT reads the same from the goal vector)."""
    return SKILLS[skill]["say"].format(arm=step["arm"], source=step["from"], target=step["to"])


def draw_zero_error(seed, deg):
    """Per-arm joint-zero calibration error for a seed, uniform within +-deg on the five arm joints; seed 0 is the exact arm."""
    if not seed or not deg:
        return {}
    rng = np.random.default_rng(seed + 7919)
    return {arm: np.append(rng.uniform(-1, 1, 5) * np.radians(deg), 0.) for arm in sites.ARMS}


def draw_servo_gain(seed, lag):
    """Per-arm position gains of the five arm joints for a seed, each joint's lag uniform in LAG_S; seed 0 or no lag keeps the sim's one gain."""
    if not seed or not lag:
        return {}
    rng = np.random.default_rng(seed + 104729)
    return {arm: teaching.SERVO_GAIN * .16 / rng.uniform(*LAG_S, 5) for arm in sites.ARMS}


@functools.cache
def physics_ranges():
    import omx_physics
    return omx_physics.ranges()


def draw_physics(seed, ranges):
    """Per-arm servo constants and joint-zero error for a seed from omx_physics.ranges(): uniform where `measured`, nan (the world's own
    value) elsewhere. kp, kv and force share one fraction per joint, a servo being stiff or soft as a whole (design at the top, the real
    registers at the bottom). A fitted zero_offset_deg has a known sign (sim q = real q + offset), so the error is drawn between 0 and it."""
    if not seed or not ranges:
        return {}, {}
    rng, servo, zero = np.random.default_rng(seed + 15485863), {}, {}
    for arm in sites.ARMS:
        rows = [ranges["arms"][arm][j] for j in ("joint1", "joint2", "joint3", "joint4", "joint5")]
        stiff = rng.uniform(0, 1, 5)
        servo[arm] = {k: np.array([r[k]["low"] + (stiff[i] if k in ("kp", "kv", "force") else rng.uniform()) * (r[k]["high"] - r[k]["low"])
                                   if r[k]["measured"] else np.nan for i, r in enumerate(rows)]) for k in ("kp", "kv", "force", "damping", "frictionloss")}
        if all("zero_offset_deg" in r for r in rows):
            zero[arm] = np.append(np.radians([rng.uniform(r["zero_offset_deg"]["low"], r["zero_offset_deg"]["high"]) for r in rows]), 0.)
    return servo, zero


def draw_errors(seed, zero_error_deg, physics=False):
    """A seed's joint-zero error: +-deg, or between 0 and the fitted offset where --physics-ranges has one."""
    error = draw_zero_error(seed, zero_error_deg)
    error.update(draw_physics(seed, physics_ranges() if physics else None)[1])
    return error


def disturb(teacher, seed, zero_error_deg, lag, physics=False):
    """A seed's errors: +-deg zero error and lag-derived gains, overridden where --physics-ranges has measured values."""
    teacher.zero_error = draw_errors(seed, zero_error_deg, physics)
    teacher.servo = {arm: dict(kp=gain) for arm, gain in draw_servo_gain(seed, lag).items()}
    servo, _ = draw_physics(seed, physics_ranges() if physics else None)
    for arm, values in servo.items():
        for k, v in values.items():
            mine = teacher.servo.setdefault(arm, {}).get(k)
            teacher.servo[arm][k] = v if mine is None else np.where(np.isnan(v), mine, v)


def outcome(score, skill):
    """A sub-skill round has no whole tasks: it passes at the sim acceptance bar."""
    if score["n"] and score["passed"] >= SKILL_PASS * score["n"]:
        return dict(status="passed")
    return dict(status="failed", reason=f"하위 동작 {skill} 성공 {score['passed']}/{score['n']}, 기준 {SKILL_PASS:.0%} 미만입니다.")


def step(driver, teacher, data, plan, here, skill):
    """One plan step with the sub-skill handed to the driver's model (or its IK); judged when the sub-skill ends."""
    import omx_two_arm_policy as policy  # it imports this module
    w, L, arm, c = driver.world, driver.layout, plan["arm"], plan["container"]
    others = {k: v for k, v in here.items() if k != c}
    idle = {o: L.sim_arms[o].wait for o in L.arms if o != arm}
    before = {o: w.pose(data, o) for o in others}
    row = dict(step=plan["id"], container=c, arm=arm, source=plan["from"], target=plan["to"], skill=skill, lifted=False)
    phases, gen = SKILLS[skill]["phases"], teacher.step_gen(data, plan, others, teacher)
    teacher.privileged = True
    try:
        target = next(gen)
        while teacher.phase not in phases:
            teacher.frame(data, {arm: target, **idle}, plan["id"])
            target = next(gen)
        teacher.privileged = False  # from here on commands are in reported angles
        start_z = w.pose(data, c)[0][2]
        if driver.kind == "ik":
            while teacher.phase in phases:
                teacher.frame(data, {arm: target, **idle}, plan["id"])
                target = next(gen)
        else:
            goal, said = policy.goal_vector(L, plan, others), prompt(plan, skill)
            driver.policy.reset()
            for _ in range(driver.longest[plan["id"]] + 15):  # the teacher's time on the sub-skill and a second of grace
                state, images = policy.observe(w, data, teacher.zero_error)
                action = driver.act(state, images, goal, said)
                k = sites.ARMS.index(arm)  # the other arm waits as the teacher had it wait: the model drives only the step's arm
                teacher.frame(data, {arm: action[k * 6:k * 6 + 6], **idle}, plan["id"])
    except StopIteration as stop:  # blocked or unreachable before the sub-skill began
        return dict(row, result=stop.value["result"], reason=stop.value.get("reason", ""))
    if SKILLS[skill]["judge"] == "placed":
        teacher.carried = None
        return teacher.verdict(data, plan, row, before)
    tcp, _ = w.tcp(data, arm)
    pos = w.pose(data, c)[0]
    rise, in_jaw = float(pos[2] - start_z), float(np.linalg.norm(pos - tcp))
    moved = teacher.disturbed(data, before, teacher)
    arm_hits = sorted(f"{a}~{b}" for a, b in teacher.contacts["arm_other"])
    crash = sorted("~".join(p) for p in teacher.contacts["arm_arm"])
    held = rise > .015 and in_jaw < .06
    return dict(row, result="pass" if held and not moved and not arm_hits and not crash else "fail", lifted=held, rise_mm=round(rise * 1000, 1),
                container_to_tcp_mm=round(in_jaw * 1000, 1), neighbours_disturbed=moved, arm_link_contacts=arm_hits, arm_arm_contacts=crash,
                first_contact_phase=teacher.first)


def isolated(driver, name, seed, skill, zero_error_deg, lag, physics=False):
    """Each step of a task from the plan's nominal state with its own errors, the sub-skill judged alone."""
    task = tasks.get_task(driver.layout, name)
    here, rows = dict(task.get("start", {})), []
    with driver.torch.inference_mode():
        for plan in task["steps"]:
            teacher = teaching.Teacher(driver.world, seed=seed + len(rows))
            disturb(teacher, seed + len(rows), zero_error_deg, lag, physics)
            data = teacher.fresh(here)  # step_gen brings a belt container in itself
            rows.append(dict(step(driver, teacher, data, plan, here, skill), task=name, seed=seed))
            print(json.dumps(rows[-1], default=str), flush=True)
            here[plan["container"]] = plan["to"]
            teacher.off_stand(data, plan, here)
    return rows


def options(parser):
    parser.add_argument("--skill", choices=sorted(SKILLS), help="learn and judge only this part of each step; the teacher's IK does the rest")
    parser.add_argument("--zero-error-deg", type=float, default=0., help="per-seed joint-zero calibration error, uniform within +-deg (the twin fit found up to 4)")
    parser.add_argument("--servo-lag", action="store_true", help="per-seed per-joint servo lag in the measured 0.10-0.34 s")
    parser.add_argument("--physics-ranges", action="store_true", help="per-seed servo, friction and zero error from omx_physics ranges where measured")


def argv(args):
    """The sub-skill options again, for a child process of the round."""
    flags = [*(["--servo-lag"] if args.servo_lag else []), *(["--physics-ranges"] if args.physics_ranges else [])]
    return ["--skill", args.skill, "--zero-error-deg", str(args.zero_error_deg), *flags] if args.skill else []
