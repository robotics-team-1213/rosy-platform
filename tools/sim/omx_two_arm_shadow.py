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


def norm_to_rad(value):
    """LeRobot RANGE_M100_100, tick 2048 = 0 rad (omx_two_arm_kin.norm_to_rad)."""
    return (np.asarray(value, float) + 100) / 200 * 4095 * 2 * math.pi / 4096 - math.pi


def health_joints(text):
    """{arm: [5 follower values]} from the pipeline's health stage output (JSON lines)."""
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("stage") == "health":
            return {bus["arm"]: [bus["motors"][j]["position"] for j in REAL_JOINTS] for bus in row["buses"] if bus["role"] == "follower"}
    raise ValueError("no health stage in the output")


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


def compare(args):
    from PIL import Image
    import mujoco
    import omx_two_arm_policy as pol
    import omx_two_arm_tasks as tasks
    import omx_two_arm_teacher as teaching
    snap = Path(args.snapshot)
    meta = json.loads((snap / "snapshot.json").read_text(encoding="utf-8"))
    driver = pol.Driver(args.model, args.steps_file, sites.parse_choices(args.choice))
    world, layout = driver.world, driver.layout
    task = tasks.get_task(layout, args.task)
    here, plan = dict(task.get("start", {})), None
    for step in task["steps"]:
        if step["id"] == args.step:
            plan = step
            break
        here[step["container"]] = step["to"]
    if plan is None or plan["from"] == "belt":
        raise SystemExit(f"{args.task}/{args.step}: not a step of the task, or a belt step (needs the belt feed)")
    # shortcut: the gripper takes the sim wait opening, the real jaw unit is not mapped; upgrade when a jaw calibration exists
    state = np.concatenate([np.append(norm_to_rad(meta["joints"][arm]), layout.arms[arm].wait[5]) for arm in sites.ARMS]).astype(np.float32)
    teacher_t = teacher_first(world, here, plan)
    data = teaching.Teacher(world, seed=0).fresh(here)
    for k, arm in enumerate(sites.ARMS):
        data.qpos[world.q[arm]] = state[6 * k:6 * k + 6]
        data.qpos[world.mimic[arm]] = -state[6 * k + 5]
    mujoco.mj_forward(world.model, data)
    sim = {view: world.render(data, view, pol.SHAPE) for view in teaching.RECORDED}
    real = {view: np.asarray(Image.open(snap / f"{REAL_VIEWS[view]}.jpg").convert("RGB").resize(pol.SHAPE[::-1])) for view in teaching.RECORDED}
    goal = pol.goal_vector(layout, plan, {k: v for k, v in here.items() if k != plan["container"]})
    with driver.torch.inference_mode():
        out = {}
        for name, images in (("real", real), ("sim", sim)):
            driver.policy.reset()
            out[name] = driver.act(state, images, goal)
    deg = lambda v: np.degrees(v).round(1).tolist()  # noqa: E731
    names = [f"{arm}.{j}" for arm in sites.ARMS for j in (*REAL_JOINTS, "gripper")]
    result = dict(snapshot=str(snap), captured_at=meta["captured_at"], model=str(args.model), task=args.task, step=args.step, arm=plan["arm"], joints=names,
                  state_deg=deg(state), real_deg=deg(out["real"]), sim_deg=deg(out["sim"]), teacher_deg=deg(teacher_t),
                  real_minus_sim_deg=deg(out["real"] - out["sim"]), real_minus_teacher_deg=deg(out["real"] - teacher_t), sim_minus_teacher_deg=deg(out["sim"] - teacher_t),
                  max_abs_real_minus_sim_deg=float(np.degrees(np.abs(out["real"] - out["sim"]).max()).round(1)),
                  image_mean_abs_diff={view: round(float(np.abs(real[view].astype(int) - sim[view].astype(int)).mean()), 1) for view in teaching.RECORDED},
                  note="L2 shadow: no command reached an arm (D-793); sim scene is the task's nominal start, gripper from the sim wait pose")
    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "shadow.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    Image.fromarray(np.vstack([pol.sheet(real), pol.sheet(sim)])).save(dest / "real-over-sim.png")
    print(json.dumps(result))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--site", required=True)
    c.add_argument("--frames", default="http://127.0.0.1:8767", help="the site's camera view server, as seen on the site")
    c.add_argument("--health", required=True, help="remote command that prints two_arm_pipeline.py --stage health output")
    c.add_argument("--out", required=True)
    m = sub.add_parser("compare")
    m.add_argument("--model", required=True)
    m.add_argument("--steps-file", required=True)
    m.add_argument("--snapshot", required=True)
    m.add_argument("--task", default="outbound")
    m.add_argument("--step", default="m0")
    m.add_argument("--choice", action="append", default=[])
    m.add_argument("--out", required=True)
    args = p.parse_args(argv)
    return capture(args) if args.cmd == "capture" else compare(args)


if __name__ == "__main__":
    raise SystemExit(main())
