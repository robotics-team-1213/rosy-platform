"""OMX-F v2.1 kinematics without MuJoCo: forward chain read from the palletizing URDF, tool-down inverse kinematics inside the plan's limits.

Used by the two-arm plan validator (no simulator needed) and by the MuJoCo teacher, so both judge reach with the same solver.
Geometry only (D-947). Joint values are radians; the real arm's normalised units convert with `norm_to_rad` (grasp_planner), not degrees.
"""
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
URDF = ROOT / "learning/envs/isaac/assets/omx_f_palletizing_description/urdf/omx_f_palletizing.urdf"
CELL_EXAMPLE = ROOT / "deploy/robot/omx/sim/ladder-cell.example.json"  # plan.home and plan.limits: the same numbers as cell_profile.yaml
JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5")
_REG_EYE6 = 1e-4 * np.eye(6)  # ik's damped-least-squares regulariser, built once
_CHAIN_CACHE = {}  # (resolved path, mtime_ns, size) -> (chain, tcp): every Arm() shares one URDF parse
_PLAN_VALUES_CACHE = {}  # same-key cache for the cell file's plan block


def _stat_key(path):
    """(resolved path, mtime_ns, size): a cache key that still sees the file change."""
    p = Path(path)
    st = p.stat()
    return str(p.resolve()), st.st_mtime_ns, st.st_size


def norm_to_rad(value):
    """grasp_planner.norm_to_rad: LeRobot RANGE_M100_100, tick 2048 = 0 rad. These are not degrees."""
    return (np.asarray(value, float) + 100) / 200 * 4095 * 2 * math.pi / 4096 - math.pi


def _rot(axis, angle):
    axis = np.asarray(axis, float)
    x, y, z = axis / np.linalg.norm(axis)
    c, s, k = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
    return np.array([[c + x * x * k, x * y * k - z * s, x * z * k + y * s],
                     [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
                     [z * x * k - y * s, z * y * k + x * s, c + z * z * k]])


def chain(urdf=URDF):
    """(origin, axis) of joint1..5 and the TCP point in link5, all read from the URDF; unit axes, copies of the cached parse."""
    key = _stat_key(urdf)
    if key not in _CHAIN_CACHE:
        root = ET.parse(key[0]).getroot()
        vec = lambda joint, tag: np.array([float(v) for v in joint.find(tag).get("xyz").split()])  # noqa: E731
        joints = {j.get("name"): j for j in root.iter("joint")}
        pairs = []
        for n in JOINTS:
            origin, axis = vec(joints[n], "origin"), vec(joints[n], "axis")
            pairs.append((origin, axis / np.linalg.norm(axis)))  # normalised once here, so _rot divides by exactly 1
        _CHAIN_CACHE[key] = (pairs, vec(joints["end_effector_joint"], "origin"))
    pairs, tcp = _CHAIN_CACHE[key]
    return [(o.copy(), a.copy()) for o, a in pairs], tcp.copy()


def plan_values(path=CELL_EXAMPLE):
    """(home joints rad with the gripper, limits (5, 2)) from the cell file's plan block; copies of the cached parse."""
    key = _stat_key(path)
    if key not in _PLAN_VALUES_CACHE:
        plan = json.loads(Path(key[0]).read_text(encoding="utf-8"))["plan"]
        home = np.append(norm_to_rad(plan["home"]), 1.0)
        limits = np.array([plan["limits"]["joints_rad"][n] for n in JOINTS])
        limits[:, 0] = np.minimum(limits[:, 0], home[:5])  # the real park pose sits past the nominal joint2 limit
        _PLAN_VALUES_CACHE[key] = (home, limits)
    home, limits = _PLAN_VALUES_CACHE[key]
    return home.copy(), limits.copy()


class Arm:
    """One arm: base position (x, y, z) and yaw in the shared world frame, the kinematic chain, tool-down IK."""

    def __init__(self, name, base_xyz, yaw, tcp_x=None, urdf=URDF, cell=CELL_EXAMPLE):
        self.name, self.base, self.yaw = name, np.array(base_xyz, float), float(yaw)
        self.chain, self.tcp = chain(urdf)
        if tcp_x is not None:
            self.tcp = np.array([tcp_x, self.tcp[1], self.tcp[2]])
        self.home, self.limits = plan_values(cell)
        self._limits_low, self._limits_high = self.limits.T  # ik's clip bounds, unpacked once
        self.R0 = _rot([0, 0, 1], self.yaw)

    def frames(self, q):
        """World points of the joint origins (j1..j5), the TCP, and link5's rotation matrix."""
        R, p, points = self.R0, self.base.copy(), []
        for (origin, axis), angle in zip(self.chain, q[:5]):
            p = p + R @ origin
            R = R @ _rot(axis, angle)
            points.append(p.copy())
        return points, p + R @ self.tcp, R

    def _tcp_and_R(self, q):
        """residual's half of frames(): the TCP point and link5's rotation, without the joint-origin points list."""
        R, p = self.R0, self.base
        for (origin, axis), angle in zip(self.chain, q[:5]):
            p = p + R @ origin
            R = R @ _rot(axis, angle)
        return p + R @ self.tcp, R

    def _res_vec(self, here, R, across):
        """The residual 6-vector [here, .3 * (tool-down + jaws square to `across`)], np.cross unrolled into components."""
        side = R[:, 1] if R[:, 1] @ across >= 0 else -R[:, 1]  # the jaw closes across the box either way round
        c0 = side[1] * across[2] - side[2] * across[1]  # cross(side, across)
        c1 = side[2] * across[0] - side[0] * across[2]
        c2 = side[0] * across[1] - side[1] * across[0]
        return np.concatenate([here, .3 * np.array([-R[1, 0] + c0, R[0, 0] + c1, c2])])  # cross(R[:, 0], [0, 0, -1]) = (-R10, R00, 0)

    def residual(self, q, pos, across):
        here, R = self._tcp_and_R(q)
        return here, self._res_vec(here, R, across)

    def ik(self, q, pos, yaw, iterations=80, tol=2e-4):
        """Tool pointing down at pos, jaws closing across a container of long-axis yaw; returns (q, position error m, orientation error)."""
        q, pos = np.array(q, float).copy(), np.asarray(pos, float)
        across = np.array([-math.sin(yaw), math.cos(yaw), 0.])
        chain, tcp = self.chain, self.tcp
        for _ in range(iterations):
            R_local, p_before, R_before = [], [], []
            R, p = self.R0, self.base
            for k, ((origin, axis), angle) in enumerate(zip(chain, q[:5])):
                R_local.append(_rot(axis, angle))  # the 5 local rotations, shared by this step and every FD column below
                p_before.append(p)
                R_before.append(R)
                p = p + R @ origin
                R = R @ R_local[k]
            here = p + R @ tcp
            r0 = self._res_vec(here, R, across)
            err = np.concatenate([pos - here, -r0[3:]])
            if np.linalg.norm(err[:3]) < tol and np.linalg.norm(err[3:]) < .01 * .3:
                break
            J = np.zeros((6, 5))
            for k in range(5):
                origin_k, axis_k = chain[k]
                R = R_before[k] @ _rot(axis_k, q[k] + 1e-6)  # one perturbed joint; the suffix multiplies the shared locals
                p = p_before[k] + R_before[k] @ origin_k
                for j in range(k + 1, 5):
                    p = p + R @ chain[j][0]
                    R = R @ R_local[j]
                J[:, k] = (self._res_vec(p + R @ tcp, R, across) - r0) / 1e-6
            step = J.T @ np.linalg.solve(J @ J.T + _REG_EYE6, err)
            q[:5] = np.clip(q[:5] + np.clip(step, -.2, .2), self._limits_low, self._limits_high)
        here, r0 = self.residual(q, pos, across)
        return q, float(np.linalg.norm(pos - here)), float(np.linalg.norm(r0[3:]) / .3)

    def reach(self, q, pos, yaw):
        """Whether pos is reachable tool-down inside the limits (1 mm, 0.03 rad); returns (ok, q nearest q, error m).

        The jaw closes the same way turned 180 deg, so joint5 has two branches: seeds on both, the one nearest q wins."""
        best = None
        for j5 in (q[4], -1.5, 0., 1.5):
            seed = np.array(q, float)
            seed[4] = j5
            found, e_pos, e_rot = self.ik(seed, pos, yaw, 200)
            if e_pos < 1e-3 and e_rot < .03 and (best is None or np.abs(found[:5] - q[:5]).sum() < np.abs(best[0][:5] - q[:5]).sum()):
                best = (found, e_pos)
        if best is None:
            return False, *self.ik(q, pos, yaw, 200)[:2]
        return True, best[0], best[1]

    def link_poses(self, q):
        """(R, p) of link1..link5 in the world (the frame after each joint, where the link meshes sit)."""
        R, p, out = self.R0, self.base.copy(), []
        for (origin, axis), angle in zip(self.chain, q[:5]):
            p = p + R @ origin
            R = R @ _rot(axis, angle)
            out.append((R.copy(), p.copy()))
        return out

    def segments(self, q):
        """Capsule axes of the arm in the world, base to TCP: a coarse stand-in for the links, for the arm-arm clearance check."""
        points, tcp, _ = self.frames(q)
        return [self.base, *points, tcp]


MESH_DIRS = (ROOT / "learning/envs/isaac/assets/open_manipulator_description/meshes/omx_f", ROOT / "learning/envs/isaac/assets/omx_f_palletizing_description/meshes/omx_f")
_POINTS = {}


def link_points(link, every=25, urdf=URDF):
    """Mesh vertices (m, link frame) of link2..link5 from the URDF's meshes, thinned: binary STL read with numpy only."""
    if link not in _POINTS:
        root = ET.parse(urdf).getroot()
        name = next(l for l in root.iter("link") if l.get("name") == link).find("collision/geometry/mesh").get("filename").rsplit("/", 1)[-1]
        path = next(d / name for d in MESH_DIRS if (d / name).exists())
        raw = np.fromfile(path, dtype=np.uint8)
        count = int(np.frombuffer(raw[80:84], dtype="<u4")[0])
        tri = np.frombuffer(raw[84:84 + 50 * count].tobytes(), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
        _POINTS[link] = np.unique(tri["v"].reshape(-1, 3)[::every].astype(float) * .001, axis=0)
    return _POINTS[link]
