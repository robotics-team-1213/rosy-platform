"""The two-arm OMX cell in one MuJoCo frame: both arms with v2.1 jaws, the stud ship plate, both temporary slot plates, the belt end, nine containers.

Cameras are the measured top and side PnP poses of cell_model_inventory.yaml (fixture frame) plus an overview; wrist cameras are the named
parameter `wrist_camera` of omx_two_arm_sites.CHOICES. MuJoCo answers GEOMETRY only here (reach, order, collision between arms, temporary space
capacity, D-947). Contact and friction numbers are not results.

    MUJOCO_GL=egl python tools/sim/omx_two_arm_world.py render OUT_DIR      # scene PNGs to compare with reality
"""
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("MUJOCO_GL", "egl")
import mujoco  # noqa: E402
import numpy as np  # noqa: E402
import omx_two_arm_kin as kin  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402
import palletizing_gripper as jaw  # noqa: E402
import ship_plate  # noqa: E402

JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")
BOX = np.array([.09, .03, .03])
MESHES = (sites.ISAAC / "assets/open_manipulator_description/meshes/omx_f", sites.ISAAC / "assets/omx_f_palletizing_description/meshes/omx_f")
PREFIX = {"arm_a": "a_", "arm_b": "b_"}
FPS = 15


def prism(polygon, z0, z1):
    """Vertices (flat list) of a convex polygon extruded from z0 to z1."""
    return [c for z in (z0, z1) for x, y in polygon for c in (x, y, z)]


def wall(section, length, along_x):
    """Convex wall mesh vertices: a (u, z) section extruded +-length/2 along x (section u is y) or along y (section u is x)."""
    return [c for s in (-1, 1) for u, z in section for c in ((s * length / 2, u, z) if along_x else (u, s * length / 2, z))]


def camera_axes(eye, focus, up):
    forward = np.array(focus, float) - eye
    forward /= np.linalg.norm(forward)
    up = np.array(up, float)
    up = up - forward * (up @ forward)
    up /= np.linalg.norm(up)
    return np.cross(forward, up), up


class World:
    def __init__(self, layout=None, wrist=None, **choices):
        self.layout = layout or sites.Layout(**choices)
        self.wrist = wrist or self.layout.choices["wrist_camera"]
        self.meshes = tempfile.TemporaryDirectory()
        self.pairs = {}
        spec = self._spec()
        self.model = spec.compile()
        self.renderers = {}
        self.show3 = mujoco.MjvOption()
        self.show3.geomgroup[3] = 1
        self._bind()

    # -- model ---------------------------------------------------------------------------------------------------------------
    def _urdf(self):
        text = jaw.URDF.read_text(encoding="utf-8")
        text = re.sub(r"<(gazebo|ros2_control)\b.*?</\1>", "", text, flags=re.S)
        for pattern in (r'<joint name="end_effector_joint".*?</joint>', r'<link name="end_effector_link">.*?</link>',
                        r'<joint name="world_fixed".*?</joint>', r'<link name="world"/>'):
            text = re.sub(pattern, "", text, flags=re.S)
        inner = re.search(r"<robot\b[^>]*>(.*)</robot>", text, flags=re.S).group(1)
        out = ['<link name="world"/>']
        for arm, p in PREFIX.items():
            body = re.sub(r'(<(?:link|joint)\s+name=")', r"\1" + p, inner)
            body = re.sub(r'(<(?:parent|child)\s+link=")', r"\1" + p, body)
            body = re.sub(r'(<mimic\s+joint=")', r"\1" + p, body)
            self.pairs[arm] = re.findall(r'<joint\s[^>]*>.*?<parent link="([^"]+)"/>\s*<child link="([^"]+)"/>', body, flags=re.S)
            for name in set(re.findall(r"package://[a-z_]+/meshes/omx_f/([^\"]+)", body)):
                for folder in MESHES:
                    if (folder / name).exists():
                        shutil.copy(folder / name, Path(self.meshes.name) / (p + name))
            body = re.sub(r"package://[a-z_]+/meshes/omx_f/", "" + p, body)
            a = self.layout.arms[arm]
            out.append(f'<joint name="{p}mount" type="fixed"><parent link="world"/><child link="{p}link0"/>'
                       f'<origin xyz="{a.base[0]} {a.base[1]} {a.base[2]}" rpy="0 0 {a.yaw}"/></joint>{body}')
        head = f'<mujoco><compiler meshdir="{self.meshes.name}" balanceinertia="true" discardvisual="false" fusestatic="false"/></mujoco>'
        return f'<robot name="two_arm">{head}{"".join(out)}</robot>'

    def _spec(self):
        L, c = self.layout, self.layout.choices
        spec = mujoco.MjSpec.from_string(self._urdf())
        spec.option.timestep = .0005
        spec.option.cone, spec.option.impratio = mujoco.mjtCone.mjCONE_ELLIPTIC, 10
        spec.visual.global_.offwidth, spec.visual.global_.offheight = 1280, 960
        spec.default.geom.solref, spec.default.geom.solimp = [.002, 1], [.95, .99, .001, .5, 2]
        world, box = spec.worldbody, mujoco.mjtGeom.mjGEOM_BOX
        f = L.fixture
        wc, ws = f["workplate_center_m"], f["workplate_size_m"]
        world.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[2, 2, .1], rgba=[.3, .3, .3, 1])
        world.add_geom(name="table", type=box, size=[ws[0] / 2, ws[1] / 2, ws[2] / 2], pos=wc, rgba=[.55, .5, .42, 1])
        bx = sites.BELT_STOP_X
        world.add_geom(name="belt", type=box, size=[.15, .0425, .002], pos=[bx + .15, f["pickup_center_m"][1], L.belt_top - .002], rgba=[.15, .15, .15, 1])
        world.add_geom(name="belt_stop", type=box, size=[.002, .0425, .004], pos=[bx, f["pickup_center_m"][1], L.belt_top + .004], rgba=[.6, .6, .6, 1])
        for arm, a in L.arms.items():  # the 12 mm base plate under each arm (size ASSUMED 120 mm square, visual only)
            world.add_geom(name=f"{PREFIX[arm]}plate", type=box, size=[.06, .06, .006], pos=[*a.base[:2], a.base[2] - .006], contype=0, conaffinity=0, rgba=[.2, .2, .2, 1])
        self._ship(spec)
        self._temp(spec)
        for k, (cid, _) in enumerate(L.containers()):
            body = world.add_body(name=cid, pos=[-1.4, 1.0 + .1 * k, .05])
            body.add_freejoint(name=cid)
            body.add_geom(name=cid, type=box, size=[*(BOX / 2)], mass=.016, condim=4, friction=[1, .005, .0001], rgba=[.85, .35, .08, 1])
        for arm, p in PREFIX.items():
            for k, (finger, side) in enumerate((("link6", 1), ("link7", -1))):
                for part in spec.body(p + finger).geoms:
                    part.contype = part.conaffinity = 0
                centre, size, angle = jaw.pad_box(side)
                spec.body(p + finger).add_geom(name=f"{p}pad{k}", type=box, pos=centre, size=[s / 2 for s in size],
                                               quat=[math.cos(angle / 2), 0, 0, math.sin(angle / 2)], mass=.004, rgba=[0, 0, 0, 0])
            for joint in spec.joints:
                if joint.name.startswith(p):
                    joint.damping, joint.armature = .3, .01
            for name in JOINTS:
                force = .2 if name == "gripper_joint_1" else 2.0
                spec.add_actuator(name=p + name, target=p + name, trntype=mujoco.mjtTrn.mjTRN_JOINT, gaintype=mujoco.mjtGain.mjGAIN_FIXED,
                                  gainprm=[40.0] + [0] * 9, biastype=mujoco.mjtBias.mjBIAS_AFFINE, biasprm=[0, -40.0, -6.3] + [0] * 7,
                                  forcelimited=mujoco.mjtLimited.mjLIMITED_TRUE, forcerange=[-force, force])
            for parent, child in self.pairs[arm]:
                spec.add_exclude(bodyname1=parent, bodyname2=child)
            spec.add_exclude(bodyname1=p + "link6", bodyname2=p + "link7")
            spec.add_equality(type=mujoco.mjtEq.mjEQ_JOINT, name1=p + "gripper_joint_2", name2=p + "gripper_joint_1", data=([0, -1, 0, 0, 0] + [0] * 7)[:mujoco.mjNEQDATA])
            if self.wrist != "none":
                self._wrist(spec, p)
        world.add_light(pos=[.1, 0, 1.2], dir=[0, 0, -1], diffuse=[.8, .8, .8])
        real = f["real_cameras"]
        for name, cam in (("top", real["top"]), ("side", real["side"])):
            right, up = camera_axes(cam["eye"], cam["focus"], cam["up"])
            world.add_camera(name=name, pos=cam["eye"], xyaxes=[*right, *up], fovy=math.degrees(2 * math.atan(cam["height"] / 2 / cam["f_px"])))
        right, up = camera_axes([.62, -.55, .5], [.0, .0, .1], [0, 0, 1])
        world.add_camera(name="overview", pos=[.62, -.55, .5], xyaxes=[*right, *up], fovy=55)
        return spec

    def _wrist(self, spec, p):
        base = dict(jaw.WRIST_CAMERA_B)
        if self.wrist == "stock":
            cell = json.loads(kin.CELL_EXAMPLE.read_text(encoding="utf-8"))["wrist_camera"]
            base.update(lens_m=cell["lens_m"], axis_hit_x_m=cell["axis_hit_x_m"])
        lens, (w, x, y, z) = jaw.wrist_camera_pose(base)
        spec.body(p + "link5").add_camera(name=p + "wrist", pos=lens, quat=[-z, y, -x, w], fovy=base["vfov_deg"])  # image turned 180 deg as in omx_cell_sim
        for part in spec.body(p + "link5").geoms:
            part.group = 3

    def _ship(self, spec):
        L = self.layout
        f, top, thick = L.fixture, ship_plate.top_z(L.fixture), L.fixture["ship_plate"]["thickness_m"]
        spec.add_mesh(name="ship_deck", uservert=prism(ship_plate.outline(f), top - thick, top))
        spec.worldbody.add_geom(name="ship_deck", type=mujoco.mjtGeom.mjGEOM_MESH, meshname="ship_deck", rgba=[.08, .12, .3, 1])
        solid, _ = ship_plate.stud_solid(f["ship_plate"])
        spec.add_mesh(name="stud", uservert=[c for point in solid for c in point])
        for i, (x, y) in enumerate(ship_plate.stud_positions(f)):
            spec.worldbody.add_geom(name=f"stud{i}", type=mujoco.mjtGeom.mjGEOM_MESH, meshname="stud", pos=[x, y, top], rgba=[.08, .12, .3, 1])

    def _temp(self, spec):
        """Both temporary plates: a convex deck, and per lane the vertical 0.6 mm seat plus the 45 degree funnel as four convex walls (SCAD v7)."""
        L, S = self.layout, sites.SCAD
        width, length, _, _, _ = sites.lane_geometry(L.choices["temp_radius_m"])
        seat, catch, rim = S["seat_h"], S["catch"], S["rim"]
        section = lambda h: [(h, 0), (h, seat), (h + catch, seat + catch), (h + catch + rim, seat + catch), (h + catch + rim, 0)]  # noqa: E731
        deck_z = L.deck_z
        spec.add_mesh(name="wall_side", uservert=wall(section(width / 2), length + 2 * (catch + rim), True))
        spec.add_mesh(name="wall_end", uservert=wall(section(length / 2), width + 2 * (catch + rim), False))
        for tag, plate in L.plates.items():
            spec.add_mesh(name=f"deck_{tag}", uservert=prism(plate["outline"], deck_z - S["deck_t"], deck_z))
            colour = [.64, .86, .91, 1]
            spec.worldbody.add_geom(name=f"deck_{tag}", type=mujoco.mjtGeom.mjGEOM_MESH, meshname=f"deck_{tag}", rgba=[.08, .15, .29, 1])
            for i, (xy, yaw) in enumerate(plate["lanes"], 1):
                for mesh, turn in (("wall_side", 0), ("wall_side", math.pi), ("wall_end", 0), ("wall_end", math.pi)):
                    a = yaw + turn
                    spec.worldbody.add_geom(name=f"w{tag}{i}{mesh[5]}{int(turn > 0)}", type=mujoco.mjtGeom.mjGEOM_MESH, meshname=mesh,
                                            pos=[*xy, deck_z], quat=[math.cos(a / 2), 0, 0, math.sin(a / 2)], rgba=colour)
        if L.choices["temp_source"] == "stl":
            raise NotImplementedError("temp_source=stl: pass the downloaded STL as a visual mesh here; collision stays the SCAD shape")

    # -- state ---------------------------------------------------------------------------------------------------------------
    def _bind(self):
        m = self.model
        self.q, self.dof, self.act, self.mimic, self.link5, self.arm_dof = {}, {}, {}, {}, {}, {}
        for arm, p in PREFIX.items():
            self.q[arm] = np.array([m.joint(p + n).qposadr[0] for n in JOINTS])
            self.act[arm] = np.array([m.actuator(p + n).id for n in JOINTS])
            self.mimic[arm] = m.joint(p + "gripper_joint_2").qposadr[0]
            self.link5[arm] = m.body(p + "link5").id
            self.arm_dof[arm] = np.array([m.joint(p + n).dofadr[0] for n in (*JOINTS, "gripper_joint_2")])
        self.box_q = {c: m.joint(c).qposadr[0] for c, _ in self.layout.containers()}
        self.box_v = {c: m.joint(c).dofadr[0] for c, _ in self.layout.containers()}
        self.substeps = round(1 / FPS / m.opt.timestep)
        self.body_name = [m.body(i).name for i in range(m.nbody)]
        self.geom_name = [m.geom(i).name for i in range(m.ngeom)]

    def reset(self):
        data = mujoco.MjData(self.model)
        for arm in PREFIX:
            home = self.layout.arms[arm].home
            data.qpos[self.q[arm]] = home
            data.qpos[self.mimic[arm]] = -home[5]
            data.ctrl[self.act[arm]] = home
        for k, (cid, _) in enumerate(self.layout.containers()):
            self.put(data, cid, None, k)
        mujoco.mj_forward(self.model, data)
        return data

    def put(self, data, cid, site, parked=0, lift=.0005):
        """Teleport a container onto a site (or park it off the cell) at rest."""
        if site is None:
            pose = [-1.4, 1.0 + .1 * parked, .016, 1, 0, 0, 0]
        else:
            s = self.layout.sites[site]
            pose = [*s["xy"], s["z"] + lift, math.cos(s["yaw"] / 2), 0, 0, math.sin(s["yaw"] / 2)]
        data.qpos[self.box_q[cid]:self.box_q[cid] + 7] = pose
        data.qvel[self.box_v[cid]:self.box_v[cid] + 6] = 0

    def advance(self, data, targets, frames=1):
        """Command {arm: 6 joint targets} for `frames` frames; ideal gravity compensation on both arms (real servos sag: shortcut)."""
        for arm, t in targets.items():
            data.ctrl[self.act[arm]] = t
        for _ in range(self.substeps * frames):
            for arm in PREFIX:
                data.qfrc_applied[self.arm_dof[arm]] = data.qfrc_bias[self.arm_dof[arm]]
            mujoco.mj_step(self.model, data)

    def pose(self, data, cid):
        """(position, long-axis yaw rad, tilt deg) of a container."""
        b = data.body(cid)
        R = b.xmat.reshape(3, 3)
        return b.xpos.copy(), math.atan2(R[1, 0], R[0, 0]), math.degrees(math.acos(min(1., abs(R[2, 2]))))

    def tcp(self, data, arm):
        R = data.xmat[self.link5[arm]].reshape(3, 3)
        return data.xpos[self.link5[arm]] + R @ self.layout.sim_arms[arm].tcp, R

    def contact_report(self, data, carried=None):
        """Contacts of this instant as sets: arm-arm pairs, arm links (not pads) on containers or plates, pads on containers other than the carried one."""
        out = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set())
        for c in data.contact[:data.ncon]:
            names = [self.geom_name[g] for g in (c.geom1, c.geom2)]
            bodies = [self.body_name[self.model.geom_bodyid[g]] for g in (c.geom1, c.geom2)]
            arms = [b[:2] if b[:2] in ("a_", "b_") else None for b in bodies]
            if arms[0] and arms[1] and arms[0] != arms[1]:
                out["arm_arm"].add(tuple(sorted(bodies)))
            for k in (0, 1):
                if arms[k] and not arms[1 - k]:
                    other = names[1 - k] or bodies[1 - k]
                    if "pad" in names[k] and other.startswith("bar-"):
                        if other != carried:
                            out["pad_neighbour"].add(other)
                    else:
                        out["arm_other"].add((bodies[k], other))
        return out

    # -- views ---------------------------------------------------------------------------------------------------------------
    def render(self, data, camera, size=(480, 640)):
        if size not in self.renderers:
            self.renderers[size] = mujoco.Renderer(self.model, *size)
        r = self.renderers[size]
        r.update_scene(data, camera=camera, scene_option=None if "wrist" in camera else self.show3)
        return r.render().copy()


def main(argv):
    from PIL import Image
    out = Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    world = World(wrist="stock")
    data = world.reset()
    for cid, site in zip((c for c, _ in world.layout.containers()), [s for _, s, _ in world.layout.plan_order()]):
        world.put(data, cid, site)
    world.advance(data, {}, 30)
    for cam in ("top", "side", "overview", "a_wrist", "b_wrist"):
        Image.fromarray(world.render(data, cam)).save(out / f"scene_{cam}.png")
    print("rendered", sorted(p.name for p in out.glob("scene_*.png")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
