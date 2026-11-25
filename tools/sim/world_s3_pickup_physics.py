"""MuJoCo joints, real contact and replay for the arm-local S3 prototype."""

from dataclasses import asdict
from hashlib import sha256
import math
from pathlib import Path

import mujoco
import numpy as np

from omx_cell_sim import ISAAC, JOINTS, URDF, Cell, _parsed_cell_urdf, norm_to_rad
import arm_s_cell_fixture as fixture
from omx_mujoco_backend import GRIP_SOLIMP, GRIP_SOLREF, adjacent_links, mjcf_urdf
import omx_physics as physics
import palletizing_gripper as jaw

DT = .002
FRAME_HZ = 20
# This pose and the box/tool offset are prototype controls, not arm S calibration.
BOX_CENTRE_BELOW_TCP = .00201
SAFE_HEIGHT = .125


class Scene:
    # Reuse the cell's damped tool-down IK with this model's own joints and TCP.
    ik = Cell.ik
    geometry = {"tray": fixture.TRAY, "belt": fixture.BELT, "pinky_frame": fixture.FRAME,
                "box_size_m": fixture.BOX}

    def __init__(self):
        self.physics = physics.Physics()
        self.model = self.build()
        self.scratch = mujoco.MjData(self.model)
        self._jacp = np.zeros((3, self.model.nv))
        self._jacr = np.zeros((3, self.model.nv))
        self.tcp = np.asarray(_parsed_cell_urdf()[2])
        self.link5 = self.model.body("link5").id
        joints = [self.model.joint(name) for name in JOINTS]
        self.qadr = np.array([joint.qposadr[0] for joint in joints])
        self.dof = np.array([joint.dofadr[0] for joint in joints])
        self.actuators = np.array([self.model.actuator(name).id for name in JOINTS])
        self.limits = np.array([joint.range for joint in joints[:5]])
        self.mimic = self.model.joint("gripper_joint_2").qposadr[0]
        self.box_q = self.model.joint("s3-cargo").qposadr[0]
        self.box_dof = self.model.joint("s3-cargo").dofadr[0]
        self.hold_dofs = self.physics.hold_dofs(self.model)
        self.box_geom = self.model.geom("s3-cargo").id
        self.belt = self.model.geom("belt").id
        self.frame = self.model.geom("pinky-frame").id
        self.tray = self.model.geom("tray").id
        self.floor = self.model.geom("floor").id
        self.jaws = {self.model.geom(name).id for name in ("jaw-left", "jaw-right")}
        self.arm = {index for index, body in enumerate(self.model.geom_bodyid)
                    if 0 < body < self.model.body("s3-cargo").id}
        self.open = jaw.angle_for_gap_clipped(.059)
        self.hold = jaw.angle_for_gap(fixture.BOX - jaw.SQUEEZE_M)
        # A clear folded start seed. Clamp to the imported arm's joint limits.
        start = norm_to_rad((.8, -62.2, 53.1, 51.6, 45.2))
        self.home = np.append(np.clip(start, *self.limits.T), self.open)
        fingerprint = sha256(mujoco.__version__.encode("ascii"))
        for path in (Path(__file__), Path(fixture.__file__), Path(physics.__file__), physics.FILE,
                     Path(jaw.__file__), URDF):
            fingerprint.update(sha256(path.read_bytes()).digest())
        model_bytes = np.empty(mujoco.mj_sizeModel(self.model), dtype=np.uint8)
        mujoco.mj_saveModel(self.model, None, model_bytes)
        fingerprint.update(model_bytes)
        self.digest = fingerprint.hexdigest()

    def build(self):
        urdf = URDF.read_text(encoding="utf-8")
        spec = mujoco.MjSpec.from_string(mjcf_urdf(urdf, (ISAAC / "assets").as_posix(), "palletizing-v2.1"))
        spec.option.timestep = DT
        spec.option.cone, spec.option.impratio = mujoco.mjtCone.mjCONE_ELLIPTIC, 10
        spec.add_equality(type=mujoco.mjtEq.mjEQ_JOINT, name1="gripper_joint_2", name2="gripper_joint_1",
                          data=[0, -1, 0, 0, 0] + [0] * 6)
        for parent, child in adjacent_links(urdf):
            spec.add_exclude(bodyname1=parent, bodyname2=child)
        spec.add_exclude(bodyname1="link6", bodyname2="link7")
        for joint in spec.joints:
            physics.apply_joint(joint, self.physics.joint("arm_s", joint.name))
        for name in JOINTS:
            physics.add_actuator(spec, name, self.physics.joint("arm_s", name))
        box = mujoco.mjtGeom.mjGEOM_BOX
        contact = dict(solref=GRIP_SOLREF, solimp=GRIP_SOLIMP, friction=[fixture.FIXTURE["friction"], .005, .0001])
        for finger, side, name in (("link6", 1, "jaw-left"), ("link7", -1, "jaw-right")):
            for part in spec.body(finger).geoms:
                part.contype = part.conaffinity = 0
            pos, size, angle = jaw.pad_box(side)
            spec.body(finger).add_geom(name=name, type=box, pos=pos, size=[s / 2 for s in size],
                                       quat=[math.cos(angle / 2), 0, 0, math.sin(angle / 2)], mass=.004, **contact)
        world = spec.worldbody
        world.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE,
                       size=[.6, .6, .01], pos=[0, 0, -.005])
        for name, support in (("tray", fixture.TRAY), ("belt", fixture.BELT), ("pinky-frame", fixture.FRAME)):
            half_z = support["top"] / 2
            world.add_geom(name=name, type=box, size=[*(s / 2 for s in support["size"]), half_z],
                           pos=[*support["center"], half_z], **contact)
        cargo = world.add_body(name="s3-cargo")
        cargo.add_freejoint(name="s3-cargo")
        cargo.add_geom(name="s3-cargo", type=box, size=[fixture.BOX / 2] * 3,
                       mass=fixture.FIXTURE["box_mass_kg"], **contact)
        return spec.compile()

    def state(self, data, phase):
        tcp = data.xpos[self.link5] + data.xmat[self.link5].reshape(3, 3) @ self.tcp
        return dict(sim_time_s=round(float(data.time), 5), phase=phase,
                    arm_joints_rad=data.qpos[self.qadr].round(5).tolist(),
                    tcp_m=tcp.round(6).tolist(),
                    box_pose_m_wxyz=data.qpos[self.box_q:self.box_q + 7].round(6).tolist())

    def contacts(self, data):
        for contact in data.contact:
            pair = {contact.geom1, contact.geom2}
            if (self.frame in pair and (self.box_geom in pair or pair & self.arm)
                    or pair & {self.tray, self.belt, self.floor} and pair & self.arm):
                return True
        return False

    def rollout(self, condition, correction, *, attempted, capture=False):
        model, data = self.model, mujoco.MjData(self.model)
        yaw = math.radians(fixture.BOX_YAW_DEG)
        offset = condition.box_yaw_rad + yaw
        start_z = fixture.TRAY["top"] + fixture.BOX / 2
        x, y = fixture.TRAY["center"]
        data.qpos[self.box_q:self.box_q + 7] = (
            x + condition.box_dx_m, y + condition.box_dy_m, start_z,
            math.cos(offset / 2), 0, 0, math.sin(offset / 2),
        )
        data.qpos[self.qadr] = self.home
        data.qpos[self.mimic] = -self.home[-1]
        data.ctrl[self.actuators] = self.home
        mujoco.mj_forward(model, data)
        frames = [self.state(data, "ready")] if capture else []
        final_z = fixture.BELT["top"] + fixture.BOX / 2
        bx, by = fixture.BELT["center"]
        peak = start_z
        stable, forbidden = 0, False
        held_by_both = False
        if attempted:
            dx, dy, dyaw = correction
            px = x + condition.observed_dx_m + dx
            py = y + condition.observed_dy_m + dy
            aim = yaw + condition.observed_yaw_rad + dyaw
            targets = (
                ("approach", (px, py, SAFE_HEIGHT), aim, self.open, 2.0),
                ("lower", (px, py, start_z + BOX_CENTRE_BELOW_TCP), aim, self.open, 1.0),
                ("close", None, aim, self.hold, 1.0),
                ("lift", (px, py, SAFE_HEIGHT), aim, self.hold, 1.0),
                ("transfer", (bx, by, SAFE_HEIGHT), yaw, self.hold, 1.0),
                ("place", (bx, by, final_z + BOX_CENTRE_BELOW_TCP + .003), yaw, self.hold, 1.0),
                ("release", None, yaw, self.open, .8),
                ("retreat", (bx, by, SAFE_HEIGHT), yaw, self.open, 1.0),
                ("settle", None, yaw, self.open, .6),
            )
            q = self.home.copy()
            start = data.xpos[self.link5] + data.xmat[self.link5].reshape(3, 3) @ self.tcp
            settled_steps = 0
            for phase, position, angle, grip, seconds in targets:
                goal = start if position is None else np.array(position)
                grip_start, count = q[-1], round(seconds * FRAME_HZ)
                for tick in range(1, count + 1):
                    alpha = tick / count
                    alpha = alpha * alpha * (3 - 2 * alpha)
                    q = self.ik(q, start + alpha * (goal - start), angle)
                    q[-1] = grip_start + alpha * (grip - grip_start)
                    data.ctrl[self.actuators] = q
                    for _ in range(round(1 / FRAME_HZ / DT)):
                        data.qfrc_applied[self.hold_dofs] = data.qfrc_bias[self.hold_dofs]
                        mujoco.mj_step(model, data)
                        peak = max(peak, float(data.qpos[self.box_q + 2]))
                        forbidden = self.contacts(data)
                        if forbidden:
                            break
                        if phase == "lift" and data.qpos[self.box_q + 2] - start_z >= .02:
                            touched = {c.geom2 if c.geom1 == self.box_geom else c.geom1
                                       for c in data.contact if self.box_geom in (c.geom1, c.geom2)}
                            held_by_both |= self.jaws <= touched
                        if phase == "settle":
                            pairs = [{c.geom1, c.geom2} for c in data.contact]
                            box_supported = {self.box_geom, self.belt} in pairs
                            has_arm_contact = any(self.box_geom in pair and pair & self.arm for pair in pairs)
                            velocity = data.qvel[self.box_dof:self.box_dof + 6]
                            slow = np.linalg.norm(velocity[:3]) < .012 and np.linalg.norm(velocity[3:]) < .25
                            settled_steps = settled_steps + 1 if box_supported and not has_arm_contact and slow else 0
                    if capture:
                        frames.append(self.state(data, phase))
                    if forbidden:
                        break
                if forbidden:
                    break
                start = goal
            stable = settled_steps * DT
        xyz = data.qpos[self.box_q:self.box_q + 3]
        xy_error = math.hypot(xyz[0] - bx, xyz[1] - by)
        upright = abs(data.body("s3-cargo").xmat[8]) >= math.cos(math.radians(12))
        placement_valid = xy_error <= .015 and abs(xyz[2] - final_z) <= .006 and upright
        lifted = peak - start_z >= .02
        if not attempted:
            result = "guard_refusal" if condition.stratum == "nominal" else "safe_refusal"
            reward = -2. if condition.stratum == "nominal" else 0.
        elif forbidden:
            result, reward = "forbidden_contact", -3.
        elif held_by_both and stable >= .30 and placement_valid:
            result, reward = "placed", 2. - xy_error
        else:
            result = "lifted_not_placed" if lifted else "not_lifted"
            reward = float(lifted) + min(.02, max(0., peak - start_z)) - xy_error
        return dict(condition=asdict(condition), attempted=attempted, result=result,
                    placement_error_m=xy_error if attempted else None, apex_m=peak, settled_s=stable,
                    held_by_both=held_by_both, elapsed_sim_s=float(data.time), reward=reward), frames
