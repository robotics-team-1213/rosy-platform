#!/usr/bin/env python3
"""arm_b's real cell in MuJoCo: v2.1 jaws, measured sites and cameras, a scripted teacher and closed-loop ACT evaluation.

Run on a lab PC, in a LeRobot environment that can also import mujoco:

    MUJOCO_GL=egl python tools/sim/omx_cell_sim.py --cell CELL check 3
    MUJOCO_GL=egl python tools/sim/omx_cell_sim.py --cell CELL collect --episodes 60 --out DIR
    MUJOCO_GL=egl python tools/sim/omx_cell_sim.py --cell CELL evaluate --model DIR --episodes 50 --seed-base 100000 --out F --artifacts DIR
    MUJOCO_GL=egl python tools/sim/omx_cell_sim.py --cell CELL compare live.json --out DIR

CELL holds the site's values (deploy/robot/omx/sim/ladder-cell.example.json shows the form; the real one stays private).
Geometry here decides reach, order and collisions. Contact and vision numbers do not carry to the real arm (D-947).
"""
import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ISAAC = ROOT / "learning/envs/isaac"
sys.path[:0] = [str(ISAAC), str(Path(__file__).resolve().parent)]
os.environ.setdefault("MUJOCO_GL", "egl")
import mujoco  # noqa: E402
import numpy as np  # noqa: E402
import omx_ladder as ladder  # noqa: E402
import palletizing_gripper as jaw  # noqa: E402

FPS, SHAPE = 15, (240, 320)
JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")
BOX = np.array([.09, .03, .03])  # 3-cell container; 16 g (cell_model_inventory.yaml)
BOX_BELOW_TCP = .00201  # Isaac hold check: the held box centre sits 2.01 mm under the TCP
URDF = ISAAC / "assets/omx_f_palletizing_description/urdf/omx_f_palletizing.urdf"
MESHES = (ISAAC / "assets/open_manipulator_description/meshes/omx_f", ISAAC / "assets/omx_f_palletizing_description/meshes/omx_f")
TRAIN_XY, TRAIN_YAW = .015, .08
EVAL_XY, EVAL_YAW = .02, .12  # wider than the data: interpolation alone must not count as success
TASK = "move the container from the pallet to the ship slot"


def norm_to_rad(value):
    """grasp_planner.norm_to_rad: LeRobot RANGE_M100_100, tick 2048 = 0 rad. These are not degrees."""
    return (np.asarray(value) + 100) / 200 * 4095 * 2 * math.pi / 4096 - math.pi


class Cell:
    def __init__(self, path):
        self.values = json.loads(Path(path).read_text(encoding="utf-8"))
        v = self.values
        self.pick, self.place = v["sites"]["pallet"], v["sites"]["slot1"]
        self.home = np.append(norm_to_rad(v["plan"]["home"]), 1.0)
        limits = np.array([v["plan"]["limits"]["joints_rad"][j] for j in JOINTS[:5]])
        limits[:, 0] = np.minimum(limits[:, 0], self.home[:5])  # the real park pose sits past the nominal joint2 limit
        self.limits, self.top, self.side = limits, v["pnp"]["top"], v["pnp"]["side"]
        self.table_z = v["table_z"]
        self.open, self.hold = jaw.angle_for_gap(.042), jaw.angle_for_gap(BOX[1] - jaw.SQUEEZE_M)
        self.deck = self._deck_rect()
        self.model = self._build()
        self._bind()

    def _axes(self, camera):
        forward, up = np.array(camera["forward"]), np.array(camera["up"])
        return np.cross(forward, up), up, forward

    def _on_plane(self, pixel, z):
        right, up, forward = self._axes(self.top)
        ray = forward * self.top["f"] + right * (pixel[0] - 320) - up * (pixel[1] - 240)
        eye = np.array(self.top["eye"])
        return eye + ray * (z - eye[2]) / ray[2]

    def _deck_rect(self):
        corners = np.array([self._on_plane(p, self.pick["surface_z"])[:2] for p in self.pick["surface_px"]])
        return corners.min(0), corners.max(0)

    def place_surface(self):
        """The slot's floor in this flat scene: the deck covers it (shortcut: no stud plate; see ship_plate for seating)."""
        low, high = self.deck
        xy = np.array(self.place["place"])
        inside = bool(np.all(xy >= low) and np.all(xy <= high))
        return max(self.place["surface_z"], self.pick["surface_z"]) if inside else self.place["surface_z"]

    def _build(self):
        urdf = URDF.read_text(encoding="utf-8")
        urdf = re.sub(r"<(gazebo|ros2_control)\b.*?</\1>", "", urdf, flags=re.S)
        urdf = re.sub(r"package://[a-z_]+/meshes/omx_f/", "", urdf)
        self.pairs = re.findall(r'<joint\s[^>]*>.*?<parent link="([^"]+)"/>\s*<child link="([^"]+)"/>', urdf, flags=re.S)
        self.meshes = tempfile.TemporaryDirectory()
        for folder in MESHES:
            for mesh in folder.glob("*.stl"):
                shutil.copy(mesh, self.meshes.name)
        head = f'<mujoco><compiler meshdir="{self.meshes.name}" balanceinertia="true" discardvisual="false" fusestatic="false"/></mujoco>'
        spec = mujoco.MjSpec.from_string(re.sub(r"(<robot\b[^>]*>)", r"\1" + head, urdf, count=1))
        spec.option.timestep = .002
        spec.option.cone, spec.option.impratio = mujoco.mjtCone.mjCONE_ELLIPTIC, 10
        spec.visual.global_.offwidth, spec.visual.global_.offheight = 640, 480
        world, box = spec.worldbody, mujoco.mjtGeom.mjGEOM_BOX
        contact = dict(solref=[.002, 1], solimp=[.95, .99, .001, .5, 2])
        world.add_geom(name="table", type=box, size=[.6, .6, .01], pos=[.1, 0, self.table_z - .01], rgba=[.55, .5, .42, 1])
        low, high = self.deck
        z = self.pick["surface_z"]
        world.add_geom(name="pallet", type=box, size=[*(high - low) / 2, (z - self.table_z) / 2],
                       pos=[*(low + high) / 2, (z + self.table_z) / 2], rgba=[.1, .13, .3, 1])
        body = world.add_body(name="box", pos=[.16, -.03, .005])
        body.add_freejoint(name="box")
        body.add_geom(name="box", type=box, size=[*(BOX / 2)], mass=.016, friction=[1, .005, .0001], rgba=[.85, .35, .08, 1], **contact)
        for k, (finger, side) in enumerate((("link6", 1), ("link7", -1))):
            for part in spec.body(finger).geoms:
                part.contype = part.conaffinity = 0
            centre, size, angle = jaw.pad_box(side)
            spec.body(finger).add_geom(name=f"pad{k}", type=box, pos=centre, size=[s / 2 for s in size],
                                       quat=[math.cos(angle / 2), 0, 0, math.sin(angle / 2)], mass=.004, rgba=[0, 0, 0, 0], **contact)
        world.add_light(pos=[.1, 0, 1.2], dir=[0, 0, -1], diffuse=[.8, .8, .8])
        for name, camera in (("top", self.top), ("side", self.side)):
            right, up, _ = self._axes(camera)
            world.add_camera(name=name, pos=camera["eye"], xyaxes=[*right, *up], fovy=math.degrees(2 * math.atan(240 / camera["f"])))
        wrist = self.values["wrist_camera"]
        lens, (w, x, y, z_) = jaw.wrist_camera_pose(dict(jaw.WRIST_CAMERA_B, lens_m=wrist["lens_m"], axis_hit_x_m=wrist["axis_hit_x_m"]))
        # The real frame shows the jaw tips rising from the bottom: the helper's assumed image-up is turned 180 deg.
        spec.body("link5").add_camera(name="wrist", pos=lens, quat=[-z_, y, -x, w], fovy=jaw.WRIST_CAMERA_B["vfov_deg"])
        for part in spec.body("link5").geoms:  # group 3 is hidden by default: the real wrist view has no housing before the lens
            part.group = 3
        for joint in spec.joints:
            if joint.name != "box":
                joint.damping, joint.armature = .3, .01
        for name in JOINTS:
            force = .2 if name == "gripper_joint_1" else 2.0
            spec.add_actuator(name=name, target=name, trntype=mujoco.mjtTrn.mjTRN_JOINT, gaintype=mujoco.mjtGain.mjGAIN_FIXED,
                              gainprm=[40.0] + [0] * 9, biastype=mujoco.mjtBias.mjBIAS_AFFINE, biasprm=[0, -40.0, -6.3] + [0] * 7,
                              forcelimited=mujoco.mjtLimited.mjLIMITED_TRUE, forcerange=[-force, force])
        for parent, child in self.pairs:
            spec.add_exclude(bodyname1=parent, bodyname2=child)
        spec.add_exclude(bodyname1="link6", bodyname2="link7")
        spec.add_equality(type=mujoco.mjtEq.mjEQ_JOINT, name1="gripper_joint_2", name2="gripper_joint_1", data=[0, -1, 0, 0, 0] + [0] * 6)
        model = spec.compile()
        rgba = model.geom_rgba
        rgba[(rgba[:, 0] > .9) & (rgba[:, 1] < .1) & (rgba[:, 2] < .1), 3] = 0  # the URDF's TCP marker is not on the real arm
        return model

    def _bind(self):
        model = self.model
        self.tcp = np.array([float(x) for x in re.search(r'name="end_effector_joint".*?<origin[^>]*xyz="([^"]+)"', URDF.read_text(encoding="utf-8"), flags=re.S).group(1).split()])
        self.qadr = np.array([model.joint(n).qposadr[0] for n in JOINTS])
        self.dof = np.array([model.joint(n).dofadr[0] for n in JOINTS])
        self.act = np.array([model.actuator(n).id for n in JOINTS])
        self.arm_dof = np.array([model.joint(n).dofadr[0] for n in (*JOINTS, "gripper_joint_2")])
        self.mimic = model.joint("gripper_joint_2").qposadr[0]
        self.link5 = model.body("link5").id
        self.box_q = model.joint("box").qposadr[0]
        self.substeps = round(1 / FPS / model.opt.timestep)
        self.scratch = mujoco.MjData(model)
        self.renderer = mujoco.Renderer(model, *SHAPE)
        self.show_link5 = mujoco.MjvOption()
        self.show_link5.geomgroup[3] = 1

    def ik(self, q, pos, yaw, iterations=12):
        """Tool down at pos, fingers closing across the box width at yaw, inside the plan's joint limits."""
        model, data, q = self.model, self.scratch, q.copy()
        across = np.array([-math.sin(yaw), math.cos(yaw), 0])
        jacp, jacr = np.zeros((3, model.nv)), np.zeros((3, model.nv))
        for _ in range(iterations):
            data.qpos[self.qadr[:5]] = q[:5]
            mujoco.mj_kinematics(model, data)
            mujoco.mj_comPos(model, data)
            R = data.xmat[self.link5].reshape(3, 3)
            here = data.xpos[self.link5] + R @ self.tcp
            mujoco.mj_jac(model, data, jacp, jacr, here, self.link5)
            side = R[:, 1] if R[:, 1] @ across >= 0 else -R[:, 1]
            turn = np.cross(R[:, 0], [0, 0, -1.0]) + np.cross(side, across)
            J = np.vstack([jacp[:, self.dof[:5]], .3 * jacr[:, self.dof[:5]]])
            error = np.concatenate([pos - here, .3 * turn])
            q[:5] = np.clip(q[:5] + np.clip(J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(6), error), -.2, .2), *self.limits.T)
            if np.linalg.norm(pos - here) < 2e-4 and np.linalg.norm(turn) < .01:
                break
        return q

    def reset(self, seed, xy_range=TRAIN_XY, yaw_range=TRAIN_YAW):
        rng = np.random.default_rng(seed)
        data = mujoco.MjData(self.model)
        xy = np.array(self.pick["start"]) + rng.uniform(-xy_range, xy_range, 2)
        yaw = math.radians(self.pick["yaw_deg"]) + rng.uniform(-yaw_range, yaw_range)
        data.qpos[self.box_q:self.box_q + 7] = [*xy, self.pick["surface_z"] + BOX[2] / 2 + .0005, math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
        data.qpos[self.qadr] = self.home
        data.qpos[self.mimic] = -self.home[5]
        data.ctrl[self.act] = self.home
        mujoco.mj_forward(self.model, data)
        return data, xy, yaw

    def advance(self, data, target):
        data.ctrl[self.act] = target
        for _ in range(self.substeps):
            data.qfrc_applied[self.arm_dof] = data.qfrc_bias[self.arm_dof]  # shortcut: ideal gravity compensation, real servos sag
            mujoco.mj_step(self.model, data)

    def teacher(self, data, xy, yaw):
        """Commanded joints per frame: approach, grasp, lift, carry, lower, release, lift."""
        carry = .075
        grasp_z = self.pick["surface_z"] + BOX[2] / 2 + BOX_BELOW_TCP
        place = np.array(self.place["place"])
        release_z = self.place_surface() + BOX[2] / 2 + BOX_BELOW_TCP + self.place["place_dz"]
        place_yaw = math.radians(self.place["yaw_deg"])
        q, tcp = self.home.copy(), data.xpos[self.link5] + data.xmat[self.link5].reshape(3, 3) @ self.tcp
        for pos, want_yaw, grip, seconds in (((*xy, carry), yaw, self.open, 2.5), ((*xy, grasp_z), yaw, self.open, 1.5), (None, yaw, self.hold, 1.5),
                                             ((*xy, carry), yaw, self.hold, 1.5), ((*place, carry), place_yaw, self.hold, 2.0),
                                             ((*place, release_z), place_yaw, self.hold, 1.5), (None, place_yaw, self.open, 1.5), ((*place, carry), place_yaw, self.open, 1.5)):
            goal = tcp if pos is None else np.array(pos)
            grip_from, count = q[5], round(seconds * FPS)
            for i in range(1, count + 1):
                s = i / count
                s = s * s * (3 - 2 * s)
                q = self.ik(q, tcp + s * (goal - tcp), want_yaw)
                q[5] = grip_from + s * (grip - grip_from)
                yield q.copy()
            tcp = goal

    def judge(self, data, peak):
        pos, R = data.body("box").xpos, data.body("box").xmat.reshape(3, 3)
        xy_err = float(np.linalg.norm(pos[:2] - self.place["place"])) * 1000
        yaw = math.degrees(math.atan2(R[1, 0], R[0, 0])) - self.place["yaw_deg"]
        yaw_err = abs((yaw + 90) % 180 - 90)  # a box turned 180 deg sits the same
        z_err = (float(pos[2]) - (self.place_surface() + BOX[2] / 2)) * 1000
        tilt = math.degrees(math.acos(min(1.0, abs(R[2, 2]))))
        return ladder.judge(xy_err, yaw_err, z_err, tilt, peak - (self.pick["surface_z"] + BOX[2] / 2))

    def views(self, data):
        self.renderer.update_scene(data, camera="top", scene_option=self.show_link5)
        top = self.renderer.render().copy()
        self.renderer.update_scene(data, camera="wrist")
        return top, self.renderer.render().copy()


def check(cell, count):
    wins = 0
    for seed in range(count):
        data, xy, yaw = cell.reset(seed)
        peak = 0.0
        for target in cell.teacher(data, xy, yaw):
            cell.advance(data, target)
            peak = max(peak, float(data.body("box").xpos[2]))
        row = cell.judge(data, peak)
        wins += row["strict"]
        print(seed, json.dumps(row), flush=True)
    print("teacher strict", wins, "/", count, flush=True)
    return 0 if wins == count else 1


def collect(cell, episodes, extra, out):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    names = [f"{n}.pos" for n in ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")]
    vector = dict(dtype="float32", shape=(6,), names=names)  # radians, unlike the real recordings' normalised units
    image = dict(dtype="video", shape=(*SHAPE, 3), names=["height", "width", "channels"])
    dataset = LeRobotDataset.create("rosy/omx-ladder", FPS, root=out, robot_type="omx_follower", features={
        "observation.state": vector, "action": vector, "observation.images.top": image, "observation.images.wrist": image})
    # A failed evaluation seed comes back as a demonstration from the same wide range it failed in.
    plan = [(seed, EVAL_XY, EVAL_YAW) for seed in extra] + [(ladder.TRAIN_SEED_BASE + i, TRAIN_XY, TRAIN_YAW) for i in range(episodes * 2)]
    saved = 0
    goal = episodes + len(extra)
    for seed, xy_range, yaw_range in plan:
        if saved >= goal:
            break
        data, xy, yaw = cell.reset(seed, xy_range, yaw_range)
        peak = 0.0
        for target in cell.teacher(data, xy, yaw):
            top, wrist = cell.views(data)
            dataset.add_frame({"observation.state": data.qpos[cell.qadr].astype(np.float32), "action": target.astype(np.float32),
                               "observation.images.top": top, "observation.images.wrist": wrist, "task": TASK})
            cell.advance(data, target)
            peak = max(peak, float(data.body("box").xpos[2]))
        if cell.judge(data, peak)["strict"]:
            dataset.save_episode()
            saved += 1
        else:
            dataset.clear_episode_buffer()
        print("episodes", saved, "seed", seed, flush=True)
    dataset.finalize()
    if saved < goal:
        raise SystemExit(f"teacher placed only {saved} of {goal} episodes")
    return 0


def evaluate(cell, path, count, seed_base, out, artifacts):
    import torch
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors
    from PIL import Image
    policy = ACTPolicy.from_pretrained(path, local_files_only=True).to("cuda" if torch.cuda.is_available() else "cpu").eval()
    pre, post = make_pre_post_processors(policy.config, pretrained_path=str(path))
    device = next(policy.parameters()).device
    rows, kept = [], {}
    Path(artifacts).mkdir(parents=True, exist_ok=True)
    with torch.inference_mode():
        for offset in range(count):
            seed = seed_base + offset
            data, _, _ = cell.reset(seed, EVAL_XY, EVAL_YAW)
            policy.reset()
            peak = 0.0
            for _ in range(round(16 * FPS)):
                top, wrist = cell.views(data)
                batch = {"observation.state": torch.from_numpy(data.qpos[cell.qadr].astype(np.float32))[None].to(device),
                         "observation.images.top": (torch.from_numpy(top).permute(2, 0, 1)[None].float() / 255).to(device),
                         "observation.images.wrist": (torch.from_numpy(wrist).permute(2, 0, 1)[None].float() / 255).to(device),
                         "task": [TASK]}
                cell.advance(data, post(policy.select_action(pre(batch))).cpu().numpy()[0])
                peak = max(peak, float(data.body("box").xpos[2]))
            row = dict(seed=seed, **cell.judge(data, peak))
            rows.append(row)
            print(json.dumps(row), flush=True)
            name = "success.png" if row["strict"] else "failure.png"
            if name not in kept:
                kept[name] = True
                Image.fromarray(np.hstack(cell.views(data))).save(Path(artifacts) / name)
    Path(out).write_text(json.dumps(dict(rows=rows, artifacts=sorted(kept))), encoding="utf-8")
    return 0


def video(cell, seeds, out, model=None):
    """An mp4 of top and wrist views, one episode per seed: the teacher, or a trained ACT model when given."""
    import av
    policy = None
    if model:
        import torch
        from lerobot.policies.act.modeling_act import ACTPolicy
        from lerobot.policies.factory import make_pre_post_processors
        policy = ACTPolicy.from_pretrained(model, local_files_only=True).to("cuda" if torch.cuda.is_available() else "cpu").eval()
        pre, post = make_pre_post_processors(policy.config, pretrained_path=str(model))
        device = next(policy.parameters()).device
    container = av.open(str(out), "w")
    stream = container.add_stream("h264", rate=FPS)
    stream.width, stream.height, stream.pix_fmt = SHAPE[1] * 2, SHAPE[0], "yuv420p"
    rows = []

    def frame(data):
        image = av.VideoFrame.from_ndarray(np.hstack(cell.views(data)), format="rgb24")
        container.mux(stream.encode(image))

    for seed in seeds:
        data, xy, yaw = cell.reset(seed, EVAL_XY, EVAL_YAW)
        peak = 0.0
        if policy is not None:
            policy.reset()
        with torch.inference_mode() if policy is not None else contextlib.nullcontext():
            for _ in cell.teacher(data, xy, yaw) if policy is None else range(round(16 * FPS)):
                if policy is None:
                    target = _
                else:
                    top, wrist = cell.views(data)
                    batch = {"observation.state": torch.from_numpy(data.qpos[cell.qadr].astype(np.float32))[None].to(device),
                             "observation.images.top": (torch.from_numpy(top).permute(2, 0, 1)[None].float() / 255).to(device),
                             "observation.images.wrist": (torch.from_numpy(wrist).permute(2, 0, 1)[None].float() / 255).to(device),
                             "task": [TASK]}
                    target = post(policy.select_action(pre(batch))).cpu().numpy()[0]
                frame(data)
                cell.advance(data, target)
                peak = max(peak, float(data.body("box").xpos[2]))
        for _ in range(FPS):  # hold the last frame a second to show where the box ended
            frame(data)
        rows.append(dict(seed=seed, **cell.judge(data, peak)))
        print(json.dumps(rows[-1]), flush=True)
    container.mux(stream.encode(None))
    container.close()
    return 0


def real_q(state):
    """The real arm's six values (normalised joints, gripper 0-100) as this model's joint1-5 and gripper_joint_1 radians."""
    gap = float(np.clip((30 + (state[5] - 52.3) * 10.4) / 1000, .012, .06))  # cell_params mm rule; a 2026-11-07 top-view reading disagrees
    gap = min(max(gap, jaw.gap_m(-.2)), jaw.gap_m(1.2))  # a wide-open real reading past the modelled stroke poses fully open
    return np.append(norm_to_rad(state[:5]), jaw.angle_for_gap(gap))


def compare(cell, state_path, out):
    """Top, side and wrist at 640x480 for a real joint state, to lay over the real frames."""
    from PIL import Image
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))["state"]
    data = mujoco.MjData(cell.model)
    data.qpos[cell.qadr] = real_q(state)
    data.qpos[cell.mimic] = -data.qpos[cell.qadr[5]]
    data.qpos[cell.box_q:cell.box_q + 3] = [0, 0, -1]  # out of view: only the arm is compared
    mujoco.mj_forward(cell.model, data)
    large = mujoco.Renderer(cell.model, 480, 640)
    Path(out).mkdir(parents=True, exist_ok=True)
    for camera in ("top", "side", "wrist"):
        large.update_scene(data, camera=camera, scene_option=cell.show_link5 if camera != "wrist" else None)
        Image.fromarray(large.render()).save(Path(out) / f"sim_{camera}.png")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cell", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check").add_argument("count", type=int)
    one = commands.add_parser("collect")
    one.add_argument("--episodes", type=int, required=True)
    one.add_argument("--extra-seeds", default="")
    one.add_argument("--out", required=True)
    one = commands.add_parser("evaluate")
    one.add_argument("--model", required=True)
    one.add_argument("--episodes", type=int, required=True)
    one.add_argument("--seed-base", type=int, required=True)
    one.add_argument("--out", required=True)
    one.add_argument("--artifacts", required=True)
    one = commands.add_parser("video")
    one.add_argument("--seeds", required=True)
    one.add_argument("--out", required=True)
    one.add_argument("--model")
    one = commands.add_parser("compare")
    one.add_argument("state")
    one.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    cell = Cell(args.cell)
    if args.command == "check":
        return check(cell, args.count)
    if args.command == "collect":
        return collect(cell, args.episodes, [int(s) for s in args.extra_seeds.split(",") if s], args.out)
    if args.command == "evaluate":
        return evaluate(cell, args.model, args.episodes, args.seed_base, args.out, args.artifacts)
    if args.command == "video":
        return video(cell, [int(s) for s in args.seeds.split(",")], args.out, args.model)
    return compare(cell, args.state, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
