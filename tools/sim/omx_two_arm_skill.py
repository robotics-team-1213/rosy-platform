"""Sub-skills of a two-arm plan step: one short part a policy owns while the teacher's IK does the rest, under the real arm's errors.

Whole steps and whole tasks scored 0/63 (two-arm ACT rounds 1-4, link5 came down 0.04 rad low); the Isaac release corrector learned one
short phase 8/9 where IK got 0/9 (2026-10-30). The privileged teacher runs a step up to the sub-skill in true joint angles; from there the
model, or for "ik" the same IK, commands in the angles the arm reports, which are off by a per-seed joint-zero error (the 2026-11-09 twin
fit found 1-4 deg), with per-joint servo lag (0.10-0.34 s measured, one 0.16 s in the plain sim). omx_two_arm_policy.py records and trains;
this module says what a sub-skill is and judges it. MuJoCo answers geometry only (D-947); no learned policy reaches the real arm (D-793).
"""
import functools
import json
import math

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


def zero_error_center(physics=False):
    """Mean per-arm joint-zero offset of `draw_errors` (non-zero where `--physics-ranges` has a one-sided fitted offset)."""
    if not physics:
        return {}
    ranges, out = physics_ranges(), {}
    for arm in sites.ARMS:
        rows = [ranges["arms"][arm][f"joint{i}"] for i in range(1, 6)]
        if all("zero_offset_deg" in r for r in rows):
            out[arm] = np.append(np.radians([.5 * (r["zero_offset_deg"]["low"] + r["zero_offset_deg"]["high"]) for r in rows]), 0.)
    return out


def draw_errors(seed, zero_error_deg, physics=False):
    """A seed's joint-zero error: +-deg, or between 0 and the fitted offset where --physics-ranges has one."""
    error = draw_zero_error(seed, zero_error_deg)
    error.update(draw_physics(seed, physics_ranges() if physics else None)[1])
    return error


def disturb(teacher, seed, zero_error_deg, lag, physics=False):
    """A seed's errors: +-deg zero error and lag-derived gains, overridden where --physics-ranges has measured values."""
    teacher.zero_error = draw_errors(seed, zero_error_deg, physics)
    teacher.zero_center = zero_error_center(physics) if seed and (zero_error_deg or physics) else {}
    teacher.servo = {arm: dict(kp=gain) for arm, gain in draw_servo_gain(seed, lag).items()}
    servo, _ = draw_physics(seed, physics_ranges() if physics else None)
    for arm, values in servo.items():
        for k, v in values.items():
            mine = teacher.servo.setdefault(arm, {}).get(k)
            teacher.servo[arm][k] = v if mine is None else np.where(np.isnan(v), mine, v)


def _policy_zero(teacher):
    """Residual zero-error dict for `observe` and per-arm command bias when `compensate_zero` is active on a learned policy."""
    if not (getattr(teacher, "compensate_zero", False) and getattr(teacher, "servo_comp", None) is not None):
        return teacher.zero_error, {}
    center = getattr(teacher, "zero_center", None) or {}
    obs = {a: teacher.zero_error[a] - np.append(teacher.servo_comp.zero_est[a], 0.) + center.get(a, 0.) for a in teacher.zero_error}
    return obs, center


def outcome(score, skill):
    """A sub-skill round has no whole tasks: it passes at the sim acceptance bar."""
    if score["n"] and score["passed"] >= SKILL_PASS * score["n"]:
        return dict(status="passed")
    return dict(status="failed", reason=f"하위 동작 {skill} 성공 {score['passed']}/{score['n']}, 기준 {SKILL_PASS:.0%} 미만입니다.")


def _judge_step(teacher, data, plan, row, before, start_z, skill):
    if SKILLS[skill]["judge"] == "placed":
        teacher.carried = None
        return teacher.verdict(data, plan, row, before)
    w = teacher.world
    tcp, _ = w.tcp(data, plan["arm"])
    pos = w.pose(data, plan["container"])[0]
    rise, in_jaw = float(pos[2] - start_z), float(np.linalg.norm(pos - tcp))
    moved = teacher.disturbed(data, before, teacher)
    arm_hits = sorted(f"{a}~{b}" for a, b in teacher.contacts["arm_other"])
    crash = sorted("~".join(p) for p in teacher.contacts["arm_arm"])
    held = rise > .015 and in_jaw < .06
    return dict(row, result="pass" if held and not moved and not arm_hits and not crash else "fail", lifted=held, rise_mm=round(rise * 1000, 1),
                container_to_tcp_mm=round(in_jaw * 1000, 1), container_to_tcp_xyz_mm=[round(float(v) * 1000, 1) for v in pos - tcp], neighbours_disturbed=moved, arm_link_contacts=arm_hits, arm_arm_contacts=crash,
                first_contact_phase=teacher.first)


def step(driver, teacher, data, plan, here, skill):
    """One plan step with the sub-skill handed to the driver's model (or its IK); judged when the sub-skill ends."""
    import omx_two_arm_policy as policy  # it imports this module
    w, L, arm, c = driver.world, driver.layout, plan["arm"], plan["container"]
    others = {k: v for k, v in here.items() if k != c}
    idle = {o: L.sim_arms[o].wait for o in L.arms if o != arm}
    before = {o: w.pose(data, o) for o in others}
    row = dict(step=plan["id"], container=c, arm=arm, source=plan["from"], target=plan["to"], skill=skill, lifted=False)
    phases, gen = SKILLS[skill]["phases"], teacher.step_gen(data, plan, others, teacher)
    teacher.privileged = not getattr(teacher, "estimated_prefix", False)  # the real cell reaches the sub-skill on its zero estimate too
    try:
        target = next(gen)
        while teacher.phase not in phases:
            teacher.frame(data, {arm: target, **idle}, plan["id"])
            target = next(gen)
        teacher.privileged = False  # from here on commands are in reported angles
        start_z = w.pose(data, c)[0][2]
        if driver.kind == "ik":
            last_cmd = target
            while teacher.phase in phases:
                last_cmd = target
                teacher.frame(data, {arm: target, **idle}, plan["id"])
                target = next(gen)
        else:
            goal = policy.goal_vector(L, plan, others, getattr(driver, "goal_mode", "joints")) if getattr(driver, "has_goal", True) else None
            said = prompt(plan, skill)
            driver.policy.reset()
            first_bad, last_cmd = None, None
            ze_obs, ze_bias = _policy_zero(teacher)
            for sub_t in range(driver.longest[plan["id"]] + 15):  # the teacher's time on the sub-skill and a second of grace
                state, images = policy.observe(w, data, ze_obs)
                if getattr(driver, "history", False):
                    state = np.concatenate([state, policy.command_history(teacher, state)])
                action = driver.act(state, images, goal, said)
                k = sites.ARMS.index(arm)  # the other arm waits as the teacher had it wait: the model drives only the step's arm
                last_cmd = action[k * 6:k * 6 + 6] + ze_bias.get(arm, 0.)
                teacher.frame(data, {arm: last_cmd, **idle}, plan["id"])
                if first_bad is None and (teacher.contacts["arm_arm"] or teacher.contacts["arm_other"] or teacher.disturbed(data, before, teacher)):
                    first_bad = sub_t
            row["first_bad_subframe"] = first_bad
        if skill == "release" and last_cmd is not None:
            teacher.carried, teacher.phase = None, "park"
            for _ in range(round(.7 * teaching.FPS)):
                teacher.frame(data, {arm: last_cmd, **idle}, plan["id"])
    except StopIteration as stop:  # blocked or unreachable before the sub-skill began
        return dict(row, result=stop.value["result"], reason=stop.value.get("reason", ""))
    return _judge_step(teacher, data, plan, row, before, start_z, skill)


def _tcp_yaw(R, ref_yaw):
    """Jaw axis yaw nearest `ref_yaw` modulo pi (the jaw is symmetric at 180 deg)."""
    d = tasks.wrap_pi(math.atan2(-R[0, 1], R[1, 1]) - ref_yaw)
    return ref_yaw + (d - math.pi if d > math.pi / 2 else d + math.pi if d < -math.pi / 2 else d)


def recovery_gen(teacher, data, plan, others, skill):
    """Yield privileged Teacher joint targets completing `skill` from drifted live arm & container pose."""
    w, L = teacher.world, teacher.layout
    arm, c, ik_arm = plan["arm"], plan["container"], L.sim_arms[plan["arm"]]
    sa, sb = L.sites[plan["from"]], L.sites[plan["to"]]
    pos_c, yaw_c, _ = w.pose(data, c)
    wps = tasks.waypoints(L, plan, others, pick=(pos_c[:2], yaw_c), drop=teacher.drop, drop_upper=teacher.drop_upper)
    phases = SKILLS[skill]["phases"]
    start_i = next(i for i, wp in enumerate(wps) if wp[0] == phases[0])
    g_open = teaching.jaw.angle_for_gap(teaching.OPEN_GAP[sa["kind"]])
    g_to = teaching.jaw.angle_for_gap(teaching.OPEN_GAP[sb["kind"]])
    g_hold = teaching.jaw.angle_for_gap(teaching.HOLD_GAP)
    q = teacher.q_now(data, arm)
    _, p_now, R_now = ik_arm.frames(q)
    tcp_w, R_w = w.tcp(data, arm)
    off = R_w.T @ (pos_c - tcp_w) if skill == "release" else None
    p_from = (pos_c + np.array([0., 0., L.hold_below])) if off is not None else p_now
    yaw_from = _tcp_yaw(R_now, wps[start_i][3])
    if skill == "grasp" and abs(float(q[5] - g_open)) > .05:
        teacher.phase = phases[0]
        a0 = float(q[5])
        for i in range(1, 9):
            yield np.append(q[:5], a0 + (g_open - a0) * i / 8)
    hover_z = max(float(p_from[2]), wps[0][2] if skill == "grasp" else wps[start_i - 1][2])
    xy_err = float(np.linalg.norm(p_from[:2] - wps[start_i][1]))
    if (skill == "release" and (xy_err > .005 or p_now[2] < hover_z - .005)) or (skill == "grasp" and xy_err > .010 and p_now[2] < hover_z - .005):
        p_hover = np.array([wps[start_i][1][0], wps[start_i][1][1], hover_z])
        shift0 = None if off is None else (lambda pos, yw, qq: teacher._hold_shift(ik_arm, off, qq, yw, pos))
        g0 = g_hold if wps[start_i][4] == "hold" else g_open
        teacher.phase = phases[0]
        q, _ = yield from teacher.tcp_move_g(teacher, ik_arm, q, p_from, p_hover, yaw_from, wps[start_i][3], g0, 1.0, shift0)
        p_from, yaw_from = p_hover, wps[start_i][3]
    for name, xy, z, yaw, grip in wps[start_i:]:
        if name not in phases:
            break
        teacher.phase = name
        if name in ("close", "release"):
            a0, a1 = (g_open, g_hold) if name == "close" else (g_hold, g_to)
            n = round(1.5 * teaching.FPS)
            for i in range(1, n + 1):
                yield np.append(q[:5], a0 + (a1 - a0) * i / n)
            if name == "close":
                tcp_c, R_c = w.tcp(data, arm)
                off = R_c.T @ (w.pose(data, c)[0] - tcp_c)
            else:
                teacher.carried = None
            p_from, yaw_from = np.array([*xy, z]), yaw
        else:
            p_to = np.array([*xy, z])
            shift = None if off is None or name in ("grasp", "lift") else (lambda pos, yw, qq: teacher._hold_shift(ik_arm, off, qq, yw, pos))
            g = g_hold if grip == "hold" else (g_open if name == "grasp" else g_to)
            seconds = 1.5 if name in ("grasp", "lower", "lift", "retreat") else max(1.5, float(np.linalg.norm(p_to - p_from)) / teaching.CARRY_SPEED)
            q, _ = yield from teacher.tcp_move_g(teacher, ik_arm, q, p_from, p_to, yaw_from, yaw, g, seconds, shift)
            p_end = p_to + shift(p_to, yaw, q) if shift is not None else p_to
            yield from teacher.settle_g(data, arm, q, g, p_end)
            p_from, yaw_from = p_to, yaw


def _candidate_prefixes(prefix_frames, eval_row, horizon, backoff=5, seed=0):
    bad = eval_row.get("first_bad_subframe")
    auto = str(prefix_frames).strip().lower() == "auto" or (isinstance(prefix_frames, int) and prefix_frames < 0)
    if bad is not None:
        bo = (4, 6, 8)[seed % 3] if (auto and seed) else backoff
        safe = max(0, int(bad) - bo)
        raw = [safe, max(0, safe - bo)] if auto else [min(max(0, int(prefix_frames)), safe)]
    elif auto:
        base = [min(horizon, max(20, horizon * 2 // 3)), min(horizon, 15)]
        raw = [min(horizon, max(12, round(horizon * (.45, .60, .75)[seed % 3]))), *base] if seed else base
    else:
        raw = [min(max(0, int(prefix_frames)), horizon)]
    return list(dict.fromkeys(raw))


def recover(driver, recorder, plan, here, skill, prefix_frames="auto"):
    """Evaluate `driver` on one step; if it fails, rewind, roll `driver` for `prefix_frames`, then save privileged recovery iff it passes."""
    import omx_two_arm_policy as policy
    w, L, arm, c = recorder.world, recorder.layout, plan["arm"], plan["container"]
    probe = teaching.Teacher(w, seed=recorder.seed, pick_vision=recorder.pick_vision, belt_skew=recorder.belt_skew, cam_jitter=recorder.cam_jitter)
    probe.zero_error, probe.zero_center = dict(recorder.zero_error), dict(getattr(recorder, "zero_center", {}) or {})
    probe.servo, probe.compensate_zero = {a: dict(v) for a, v in recorder.servo.items()}, recorder.compensate_zero
    eval_row = step(driver, probe, probe.fresh(here), plan, here, skill)
    if eval_row["result"] != "fail":
        return dict(eval_row, dagger_status="passed_skip" if eval_row["result"] == "pass" else "blocked_skip")
    others = {k: v for k, v in here.items() if k != c}
    idle = {o: L.sim_arms[o].wait for o in L.arms if o != arm}
    row = dict(step=plan["id"], container=c, arm=arm, source=plan["from"], target=plan["to"], skill=skill, lifted=False)
    phases = SKILLS[skill]["phases"]
    verdict = dict(row, result="fail")
    for n_prefix in _candidate_prefixes(prefix_frames, eval_row, driver.longest[plan["id"]], seed=recorder.seed):
        recorder.rng, recorder.skew_i = np.random.default_rng(recorder.seed), 0
        recorder.contacts, recorder.carried = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set()), None
        recorder.goal = None
        data = recorder.fresh(here)
        before = {o: w.pose(data, o) for o in others}
        gen = recorder.step_gen(data, plan, others, recorder)
        recorder.privileged = True
        try:
            target = next(gen)
            while recorder.phase not in phases:
                recorder.frame(data, {arm: target, **idle}, plan["id"])
                target = next(gen)
        except StopIteration as stop:
            return dict(row, result=stop.value["result"], reason=stop.value.get("reason", ""), dagger_status="blocked_skip")
        start_z = w.pose(data, c)[0][2]
        recorder.privileged, recorder.goal = False, None
        goal_driver = policy.goal_vector(L, plan, others, getattr(driver, "goal_mode", "joints")) if getattr(driver, "has_goal", True) else None
        said = prompt(plan, skill)
        driver.policy.reset()
        ze_obs, ze_bias = _policy_zero(recorder)
        for _ in range(n_prefix):
            state, images = policy.observe(w, data, ze_obs)
            action = driver.act(state, images, goal_driver, said)
            k = sites.ARMS.index(arm)
            recorder.frame(data, {arm: action[k * 6:k * 6 + 6] + ze_bias.get(arm, 0.), **idle}, plan["id"])
            if recorder.contacts["arm_arm"] or recorder.contacts["arm_other"]:
                break
        pos_c = w.pose(data, c)[0]
        pre_bad = bool(recorder.contacts["arm_arm"] or recorder.contacts["arm_other"] or (hasattr(recorder, "disturbed") and recorder.disturbed(data, before, recorder)))
        if not pre_bad and skill == "grasp" and hasattr(w, "model"):
            pre_bad = float(np.linalg.norm(pos_c[:2] - L.sites[plan["from"]]["xy"])) > .035
        if not pre_bad and skill == "release" and hasattr(w, "model"):
            pre_bad = float(np.linalg.norm(pos_c - w.tcp(data, arm)[0])) > .06
        if pre_bad:
            recorder.dataset.clear_episode_buffer()
            verdict = dict(row, result="fail", reason="prefix_invalid", dagger_prefix_frames=n_prefix)
            continue
        recorder.privileged = True
        recorder.goal = True if recorder.no_goal else (goal_driver if goal_driver is not None else policy.goal_vector(L, plan, others, recorder.goal_mode))
        recorder.prompt = said
        recorder.count, last_rec = 0, None
        for target in recovery_gen(recorder, data, plan, others, skill):
            last_rec = target
            recorder.frame(data, {arm: target, **idle}, plan["id"])
        recorder.goal = None
        if skill == "release" and last_rec is not None:
            recorder.carried, recorder.phase = None, "park"
            for _ in range(round(.7 * teaching.FPS)):
                recorder.frame(data, {arm: last_rec, **idle}, plan["id"])
        verdict = dict(_judge_step(recorder, data, plan, row, before, start_z, skill), dagger_prefix_frames=n_prefix)
        if verdict["result"] == "pass" and recorder.count > 0:
            recorder.dataset.save_episode()
            recorder.longest[plan["id"]] = max(recorder.longest.get(plan["id"], 0), n_prefix + recorder.count)
            return dict(verdict, dagger_status="recovered")
        recorder.dataset.clear_episode_buffer()
    return dict(verdict, dagger_status="recovery_failed")


def isolated(driver, name, seed, skill, zero_error_deg, lag, physics=False, *, compensate_zero=False, zero_est_noise_deg=0., estimated_prefix=False):
    """Each step of a task from the plan's nominal state with its own errors, the sub-skill judged alone."""
    task = tasks.get_task(driver.layout, name)
    here, rows = dict(task.get("start", {})), []
    with driver.torch.inference_mode():
        for plan in task["steps"]:
            teacher = teaching.Teacher(driver.world, seed=seed + len(rows), pick_vision=getattr(driver, "pick_vision", False),
                                       belt_skew=getattr(driver, "belt_skew", False), cam_jitter=getattr(driver, "cam_jitter", False))
            disturb(teacher, seed + len(rows), zero_error_deg, lag, physics)
            teacher.compensate_zero, teacher.zero_est_noise_deg, teacher.estimated_prefix = bool(compensate_zero), zero_est_noise_deg, bool(estimated_prefix)
            data = teacher.fresh(here)  # step_gen brings a belt container in itself
            rows.append(dict(step(driver, teacher, data, plan, here, skill), task=name, seed=seed))
            print(json.dumps(rows[-1], default=str), flush=True)
            here[plan["container"]] = plan["to"]
            teacher.off_stand(data, plan, here)
    return rows


def noise_degrees(text):
    """--zero-est-noise-deg: one sigma for all five joints, or five comma-separated ones."""
    values = tuple(float(v) for v in text.split(","))
    if len(values) not in (1, 5) or min(values) < 0:
        raise ValueError(text)
    return values[0] if len(values) == 1 else values


def options(parser):
    parser.add_argument("--pick-vision", action="store_true", help="infer belt pick pose from top camera")
    parser.add_argument("--belt-skew", action="store_true", help="spawn skewed/offset containers on belt")
    parser.add_argument("--cam-jitter", action="store_true", help="perturb physical top camera pose and self-calibrate online")
    parser.add_argument("--compensate-zero", action="store_true", help="calibrate and compensate joint-zero error online (G-20)")
    parser.add_argument("--zero-est-noise-deg", type=noise_degrees, default=0.,
                        help="with --compensate-zero: per-seed Gaussian error (sigma, deg) of the zero estimate, one value or five (joints 1-5); 0 is the oracle")
    parser.add_argument("--state-history", action="store_true",
                        help="collect: the state also carries each arm's last joint command (the policy then sees its servo's lag)")
    parser.add_argument("--estimated-prefix", action="store_true",
                        help="judge: the IK before the sub-skill also runs on reported angles (+ the zero estimate with --compensate-zero), as on the real cell")
    parser.add_argument("--skill", choices=sorted(SKILLS), help="learn and judge only this part of each step; the teacher's IK does the rest")
    parser.add_argument("--zero-error-deg", type=float, default=0., help="per-seed joint-zero calibration error, uniform within +-deg (the twin fit found up to 4)")
    parser.add_argument("--servo-lag", action="store_true", help="per-seed per-joint servo lag in the measured 0.10-0.34 s")
    parser.add_argument("--physics-ranges", action="store_true", help="per-seed servo, friction and zero error from omx_physics ranges where measured")


def argv(args):
    """The sub-skill and vision/skew options again, for a child process of the round."""
    vision = [*(["--pick-vision"] if getattr(args, "pick_vision", False) else []),
              *(["--belt-skew"] if getattr(args, "belt_skew", False) else []),
              *(["--cam-jitter"] if getattr(args, "cam_jitter", False) else []),
              *(["--compensate-zero"] if getattr(args, "compensate_zero", False) else []),
              *(["--zero-est-noise-deg", ",".join(map(str, np.atleast_1d(args.zero_est_noise_deg)))] if np.any(getattr(args, "zero_est_noise_deg", 0.)) else []),
              *(["--estimated-prefix"] if getattr(args, "estimated_prefix", False) else []),
              *(["--state-history"] if getattr(args, "state_history", False) else [])]
    flags = [*(["--servo-lag"] if args.servo_lag else []), *(["--physics-ranges"] if args.physics_ranges else [])]
    return [*(["--skill", args.skill, "--zero-error-deg", str(args.zero_error_deg), *flags] if args.skill else []), *vision]


def pipeline_stages(score, layout, eval_rows, *, pick_vision=False, belt_skew=False, gazebo_report=None, isaac_report=None, skill=None):
    import omx_ladder as ladder
    import omx_two_arm_policy as policy
    verdict = policy.outcome(score, skill)
    handoff = teaching.isaac_handoff(dict(task="two-arm-policy", completed=verdict["status"] == "passed", steps=score["n"], steps_pass=score["passed"], rows=eval_rows), layout)
    gz = ladder.judge_gazebo_contract(gazebo_report) if gazebo_report else dict(status="not_run", claim="ROS 실행 계약", contract=None, artifacts=[], reason="별도 ROS 2 실행 계약 점검(omx_backend_conformance.py)을 이 라운드에서 실행하지 않았습니다.")
    return dict(
        mujoco=dict(stage_order=1, track="learning_and_physics", status=verdict["status"], role="stage1_geometry_vision_and_act_policy", claim="기하·비전 정책(Stage 1): 4카메라+12관절 입력 ACT 추론 및 도달·순서·충돌 검증(D-947)", pick_vision=bool(pick_vision), belt_skew=bool(belt_skew), eval=score, reason=verdict.get("reason")),
        isaac=dict(stage_order=2, track="learning_and_physics", role="stage2_physx_contact_pad_slip_and_seating", handoff=handoff, **(ladder.judge_isaac_stage(isaac_report if isaac_report else handoff))),
        gazebo=dict(stage_order=None, track="ros2_execution_contract", role="ros2_interface_conformance", **gz),
    )
