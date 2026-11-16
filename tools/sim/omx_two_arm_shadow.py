#!/usr/bin/env python3
"""Shadow check of a two-arm model on the real cell (D-793 L2): real frames and joints in, nothing out to the arms.

`capture` reads the site's four camera frames and both arms' follower joints (the two-arm pipeline's read-only `health` stage) into a
snapshot folder. `compare` (a lab PC with MuJoCo + LeRobot) poses the sim arms at the real joints, renders the same four views, and runs
the model once on the real frames and once on the sim frames with the same state and plan-step goal. The gap between the two outputs is
what the cameras alone change (sim2real of the image input); both are also set against the teacher's first target for that step.

    omx_two_arm_shadow.py capture --site rosy-arm-cell --health "<remote command printing the health stage JSON>" --out SNAP
    MUJOCO_GL=egl omx_two_arm_shadow.py compare --model M --steps-file S --snapshot SNAP --task outbound --step m0 --out DIR [--choice k=v]

No command reaches an arm (D-793 L2). The sim scene holds the task's nominal start, not what is on the real cell. Geometry only (D-947).
"""
import argparse
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402

REAL_VIEWS = {"top": "top", "side": "side", "a_wrist": "arm_a_wrist", "b_wrist": "arm_b_wrist"}  # sim view -> site camera label
REAL_JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")  # joint1..joint5
HEALTH_JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5")
DEFAULT_HEALTH_CMD = "cat ~/.local/state/rosy/motor-health/arm_a.json ~/.local/state/rosy/motor-health/arm_b.json"


def shadow_risks(arm, state_rad, real_rad, sim_rad, *, max_shadow_deg=None, max_idle_deg=None):
    """Split active-arm vs idle-arm L2 shadow drift and enforce optional Go/No-Go caps."""
    idx = sites.ARMS.index(arm)
    active = slice(6 * idx, 6 * idx + 6)
    idle = slice(6 * (1 - idx), 6 * (1 - idx) + 6)
    state, real, sim = np.asarray(state_rad, float), np.asarray(real_rad, float), np.asarray(sim_rad, float)
    active_sim = round(float(np.degrees(np.abs(real[active] - sim[active])).max()), 1)
    active_step = round(float(np.degrees(np.abs(real[active] - state[active])).max()), 1)
    idle_delta = round(float(np.degrees(np.abs(real[idle] - state[idle])).max()), 1)
    reasons = []
    if max_shadow_deg is not None and active_sim > max_shadow_deg:
        reasons.append(f"active_arm_shadow_deg {active_sim} > {max_shadow_deg}")
    if max_idle_deg is not None and idle_delta > max_idle_deg:
        reasons.append(f"idle_arm_delta_deg {idle_delta} > {max_idle_deg}")
    return {
        "active_arm_max_abs_real_minus_sim_deg": active_sim,
        "active_arm_max_step_deg": active_step,
        "idle_arm_max_abs_delta_deg": idle_delta,
        "l2_gate": {"passed": not reasons, "reasons": reasons},
    }


def norm_to_rad(value):
    """LeRobot RANGE_M100_100, tick 2048 = 0 rad (omx_two_arm_kin.norm_to_rad)."""
    return (np.asarray(value, float) + 100) / 200 * 4095 * 2 * math.pi / 4096 - math.pi


def _tick_to_norm(present_raw):
    value = float(present_raw)
    if not math.isfinite(value):
        raise ValueError("non-finite motor tick in motor-health")
    return value / 4095.0 * 200.0 - 100.0


def health_joints(text):
    """{arm: [5 follower values]} from two_arm_pipeline --stage health JSON lines or motor-health/*.json."""
    decoder, observed = json.JSONDecoder(), {}
    for line in text.splitlines():
        pos, n = 0, len(line)
        while pos < n:
            while pos < n and line[pos].isspace():
                pos += 1
            if pos >= n or line[pos] != "{":
                break
            try:
                row, end = decoder.raw_decode(line, pos)
            except ValueError:
                break
            pos = end
            if not isinstance(row, dict):
                continue
            if row.get("stage") == "health":
                return {bus["arm"]: [bus["motors"][j]["position"] for j in REAL_JOINTS] for bus in row["buses"] if bus["role"] == "follower"}
            if row.get("schema_version") == "rosy.motor-health.v1" and row.get("owner_id") in sites.ARMS:
                by_joint = {m["joint"]: m["present_raw"] for m in row.get("motors", []) if "joint" in m and "present_raw" in m}
                if all(j in by_joint for j in HEALTH_JOINTS):
                    observed[row["owner_id"]] = [_tick_to_norm(by_joint[j]) for j in HEALTH_JOINTS]
    if all(arm in observed for arm in sites.ARMS):
        return {arm: observed[arm] for arm in sites.ARMS}
    raise ValueError("no health stage or complete motor-health pair in the output")


def capture(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ssh = lambda cmd: subprocess.run(["ssh", "-o", "ConnectTimeout=10", args.site, cmd], capture_output=True, check=True, timeout=120).stdout  # noqa: E731
    t0 = time.time()
    for label in REAL_VIEWS.values():
        blob = ssh(f"curl -sf {args.frames}/frame/{label}.jpg")
        if not blob:
            raise SystemExit(f"no frame for {label}")
        (out / f"{label}.jpg").write_bytes(blob)
    joints = health_joints(ssh(args.health).decode())
    meta = dict(captured_at=t0, frames_s=round(time.time() - t0, 2), joints=joints, site=args.site)
    (out / "snapshot.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta))
    return 0


class FirstTarget(Exception):
    pass


def teacher_first(world, here, plan, seed=0):
    """The teacher's first commanded targets for this step from the nominal start, without running the step."""
    import omx_two_arm_teacher as teaching

    class Probe(teaching.Teacher):
        armed = False

        def frame(self, data, targets, label, ctxs=None):
            if self.armed:
                raise FirstTarget(targets)
            super().frame(data, targets, label, ctxs)

    teacher = Probe(world, seed=seed)
    data = teacher.fresh(here)  # fresh() settles through frame(), so the probe is armed after it
    teacher.armed = True
    try:
        teacher.run_step(data, plan, {k: v for k, v in here.items() if k != plan["container"]})
    except FirstTarget as hit:
        return np.concatenate([hit.args[0][arm] for arm in sites.ARMS])
    raise ValueError("the teacher sent no target")


def _compare_one(driver, snap_real, meta, plan, here, args, *, Image, mujoco, pol, skills, teaching):
    world, layout = driver.world, driver.layout
    # shortcut: the gripper takes the sim wait opening, the real jaw unit is not mapped; upgrade when a jaw calibration exists
    state = np.concatenate([np.append(norm_to_rad(meta["joints"][arm]), layout.arms[arm].wait[5]) for arm in sites.ARMS]).astype(np.float32)
    teacher_t = teacher_first(world, here, plan)
    t_sim = teaching.Teacher(world, seed=0)
    data = t_sim.fresh(here)
    if plan["from"] == "belt":
        t_sim.belt_in(data, plan, {o: layout.sim_arms[o].wait for o in layout.arms if o != plan["arm"]})
    for k, arm in enumerate(sites.ARMS):
        data.qpos[world.q[arm]] = state[6 * k:6 * k + 6]
        data.qpos[world.mimic[arm]] = -state[6 * k + 5]
    mujoco.mj_forward(world.model, data)
    sim = {view: world.render(data, view, pol.SHAPE) for view in teaching.RECORDED}
    goal = pol.goal_vector(layout, plan, {k: v for k, v in here.items() if k != plan["container"]}, getattr(driver, "goal_mode", "joints")) if driver.has_goal else None
    prompt = args.prompt or (skills.prompt(plan, args.skill) if args.skill else pol.PROMPT)
    with driver.torch.inference_mode():
        out = {}
        for name, images in (("real", snap_real), ("sim", sim)):
            driver.policy.reset()
            out[name] = driver.act(state, images, goal, prompt=prompt)
    deg = lambda v: np.degrees(v).round(1).tolist()  # noqa: E731
    names = [f"{arm}.{j}" for arm in sites.ARMS for j in (*REAL_JOINTS, "gripper")]
    risks = shadow_risks(
        plan["arm"], state, out["real"], out["sim"],
        max_shadow_deg=args.max_shadow_deg, max_idle_deg=args.max_idle_deg,
    )
    result = dict(snapshot=str(Path(args.snapshot)), captured_at=meta["captured_at"], model=str(args.model), policy_type=driver.kind, prompt=prompt,
                  task=args.task, step=plan["id"], arm=plan["arm"], joints=names,
                  state_deg=deg(state), real_deg=deg(out["real"]), sim_deg=deg(out["sim"]), teacher_deg=deg(teacher_t),
                  real_minus_sim_deg=deg(out["real"] - out["sim"]), real_minus_teacher_deg=deg(out["real"] - teacher_t), sim_minus_teacher_deg=deg(out["sim"] - teacher_t),
                  max_abs_real_minus_sim_deg=float(np.degrees(np.abs(out["real"] - out["sim"]).max()).round(1)),
                  image_mean_abs_diff={view: round(float(np.abs(snap_real[view].astype(int) - sim[view].astype(int)).mean()), 1) for view in teaching.RECORDED},
                  **risks,
                  note="L2 shadow: no command reached an arm (D-793); sim scene is the task's nominal start, gripper from the sim wait pose")
    return result, Image.fromarray(np.vstack([pol.sheet(snap_real), pol.sheet(sim)]))


def compare(args):
    from PIL import Image
    import mujoco
    import omx_two_arm_policy as pol
    import omx_two_arm_skill as skills
    import omx_two_arm_tasks as tasks
    import omx_two_arm_teacher as teaching
    snap = Path(args.snapshot)
    meta = json.loads((snap / "snapshot.json").read_text(encoding="utf-8"))
    import torch
    if not torch.cuda.is_available():  # the saved processors name cuda; on a CPU run (the GPU busy training) move them
        import lerobot.policies.factory as factory
        make = factory.make_pre_post_processors
        factory.make_pre_post_processors = lambda config, **kw: make(config, preprocessor_overrides={"device_processor": {"device": "cpu"}},
                                                                      postprocessor_overrides={"device_processor": {"device": "cpu"}}, **kw)
    driver = pol.Driver(
        args.model, args.steps_file, sites.parse_choices(args.choice),
        n_action_steps=args.n_action_steps, flow_steps=args.flow_steps,
        use_amp=True if args.amp else None,
    )
    layout = driver.layout
    task = tasks.get_task(layout, args.task)
    raw_steps = [s.strip() for s in args.step.split(",") if s.strip()]
    step_ids = [s["id"] for s in task["steps"]] if raw_steps == ["all"] else raw_steps
    if not step_ids:
        raise SystemExit("at least one --step id is required")
    here, targets = dict(task.get("start", {})), {}
    for step in task["steps"]:
        if step["id"] in step_ids:
            targets[step["id"]] = (step, dict(here))
        here[step["container"]] = step["to"]
    missing = [sid for sid in step_ids if sid not in targets]
    if missing:
        raise SystemExit(f"{args.task}/{','.join(missing)}: not a step of the task")
    real = {view: np.array(Image.open(snap / f"{REAL_VIEWS[view]}.jpg").convert("RGB").resize(pol.SHAPE[::-1]), copy=True)
            for view in teaching.RECORDED}
    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)
    ctx = dict(Image=Image, mujoco=mujoco, pol=pol, skills=skills, teaching=teaching)
    if len(step_ids) == 1 and raw_steps != ["all"]:
        plan, step_here = targets[step_ids[0]]
        result, sheet_img = _compare_one(driver, real, meta, plan, step_here, args, **ctx)
        (dest / "shadow.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        sheet_img.save(dest / "real-over-sim.png")
        print(json.dumps(result))
        return 0 if result["l2_gate"]["passed"] else 2
    results, reasons = [], []
    for sid in step_ids:
        plan, step_here = targets[sid]
        result, sheet_img = _compare_one(driver, real, meta, plan, step_here, args, **ctx)
        (dest / f"{sid}-shadow.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        sheet_img.save(dest / f"{sid}-real-over-sim.png")
        results.append(result)
        reasons.extend(f"{sid}: {r}" for r in result["l2_gate"]["reasons"])
    ranked = [r["step"] for r in sorted(results, key=lambda r: (r["l2_gate"]["passed"], -r["active_arm_max_abs_real_minus_sim_deg"]))]
    summary = dict(snapshot=str(snap), captured_at=meta["captured_at"], model=str(args.model), policy_type=driver.kind,
                   task=args.task, steps=results, ranked_steps=ranked, l2_gate={"passed": not reasons, "reasons": reasons})
    (dest / "shadow.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary))
    return 0 if not reasons else 2


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--site", required=True)
    c.add_argument("--frames", default="http://127.0.0.1:8767", help="the site's camera view server, as seen on the site")
    c.add_argument("--health", default=DEFAULT_HEALTH_CMD, help="remote command printing two_arm_pipeline --stage health or motor-health/*.json")
    c.add_argument("--out", required=True)
    m = sub.add_parser("compare")
    m.add_argument("--model", required=True)
    m.add_argument("--steps-file", required=True)
    m.add_argument("--snapshot", required=True)
    m.add_argument("--task", default="outbound")
    m.add_argument("--step", default="m0")
    m.add_argument("--choice", action="append", default=[])
    m.add_argument("--skill", choices=("grasp", "release"), default=None)
    m.add_argument("--prompt", default=None)
    m.add_argument("--flow-steps", type=int, default=None)
    m.add_argument("--n-action-steps", type=int, default=None)
    m.add_argument("--amp", action="store_true")
    m.add_argument("--max-shadow-deg", type=float, default=None)
    m.add_argument("--max-idle-deg", type=float, default=None)
    m.add_argument("--out", required=True)
    args = p.parse_args(argv)
    return capture(args) if args.cmd == "capture" else compare(args)


if __name__ == "__main__":
    raise SystemExit(main())
