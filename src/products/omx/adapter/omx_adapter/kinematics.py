"""OMX-F forward kinematics and analytic top-down IK (D-402 §5).

Pure Python, ROS-free. Geometry comes from the pinned URDF values in
``config/omx_f_kinematics.yaml``; protective limits come from the caller
(the simulation cell profile), never from the URDF's +/-2*pi.

Conventions (base frame = ``link0``):

* "Top-down" means the tool approach axis (``end_effector_link`` +x) points
  along -z_base. Because joints 2-4 rotate about +y and +y rotation turns +x
  toward -z, the joint condition is q2 + q3 + q4 = +pi/2.
* ``yaw`` is the heading of the TCP +z axis in the base xy plane. A top-down
  TCP orientation is exactly Rz(yaw) * Ry(+pi/2), so q5 = q1 - yaw (mod 2*pi).
* The planar 2-link solve uses the elbow-up branch only (elbow above the
  shoulder-wrist line): for table-top picking the elbow-down branch drives the
  elbow toward the table, and the vendor SRDF ``home`` pose is elbow-up.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import yaml


ARM_JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5")
DEFAULT_KINEMATICS_PATH = Path(__file__).resolve().parents[1] / "config" / "omx_f_kinematics.yaml"

IK_OK = "OK"
IK_OUTSIDE_WORKSPACE = "OUTSIDE_WORKSPACE"
IK_SINGULAR = "SINGULAR"
IK_UNREACHABLE = "UNREACHABLE"
IK_JOINT_LIMIT = "JOINT_LIMIT"
IK_YAW_LIMIT = "YAW_LIMIT"

_EPS = 1e-12

Matrix = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


def wrap_angle(value: float) -> float:
    """Wrap to (-pi, pi]."""
    wrapped = math.remainder(value, 2.0 * math.pi)
    return math.pi if wrapped == -math.pi else wrapped


def _finite(name: str, value: object) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _triple(name: str, value: object) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must contain 3 values")
    return tuple(_finite(name, item) for item in value)  # type: ignore[return-value]


def _matmul(a: Matrix, b: Matrix) -> Matrix:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
                 for i in range(3))  # type: ignore[return-value]


def _matvec(a: Matrix, v: Sequence[float]) -> tuple[float, float, float]:
    return tuple(sum(a[i][k] * v[k] for k in range(3)) for i in range(3))  # type: ignore[return-value]


def _rpy(roll: float, pitch: float, yaw: float) -> Matrix:
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return ((cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
            (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
            (-sp, cp * sr, cp * cr))


def _axis_angle(axis: Sequence[float], angle: float) -> Matrix:
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    return ((t * x * x + c, t * x * y - s * z, t * x * z + s * y),
            (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
            (t * x * z - s * y, t * y * z + s * x, t * z * z + c))


_IDENTITY: Matrix = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


@dataclass(frozen=True)
class ChainJoint:
    name: str
    joint_type: str
    xyz: tuple[float, float, float]
    rpy: tuple[float, float, float]
    axis: tuple[float, float, float] | None


@dataclass(frozen=True)
class TopDownPose:
    """Base-frame TCP target with the tool axis along -z_base."""

    x: float
    y: float
    z: float
    yaw: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "z", "yaw"):
            object.__setattr__(self, name, _finite(name, getattr(self, name)))


@dataclass(frozen=True)
class TcpPose:
    """FK result: TCP position, top-down yaw, and the tool-axis deviation from -z_base."""

    x: float
    y: float
    z: float
    yaw: float
    tool_down_error_rad: float
    rotation: Matrix


@dataclass(frozen=True)
class IkLimits:
    """Protective constraints supplied by the planning profile (never the URDF)."""

    position_limits: Mapping[str, tuple[float, float]]
    workspace_min_m: tuple[float, float, float]
    workspace_max_m: tuple[float, float, float]
    singularity_radius_m: float

    def __post_init__(self) -> None:
        if set(self.position_limits) != set(ARM_JOINTS):
            raise ValueError("IK limits must cover exactly joint1..joint5")
        for name, (lower, upper) in self.position_limits.items():
            if not (_finite(name, lower) < _finite(name, upper)):
                raise ValueError(f"position limit for {name} must be increasing")
        low = _triple("workspace_min_m", self.workspace_min_m)
        high = _triple("workspace_max_m", self.workspace_max_m)
        if any(a >= b for a, b in zip(low, high)):
            raise ValueError("workspace bounds must be increasing")
        if _finite("singularity_radius_m", self.singularity_radius_m) <= 0:
            raise ValueError("singularity_radius_m must be positive")


@dataclass(frozen=True)
class IkResult:
    reason: str
    joints: tuple[float, float, float, float, float] | None = None
    yaw: float | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.reason == IK_OK


class OmxKinematics:
    """FK over the URDF chain plus the closed-form top-down IK it admits."""

    def __init__(self, document: Mapping[str, object]) -> None:
        if document.get("schema") != "rosy.omx-kinematics.v1":
            raise ValueError("kinematics document schema must be rosy.omx-kinematics.v1")
        source = document.get("source")
        if not isinstance(source, Mapping) or not all(
                isinstance(source.get(key), str) and source.get(key)
                for key in ("repository", "revision", "file")):
            raise ValueError("kinematics document must cite repository, revision, and file")
        raw = document.get("joints")
        if not isinstance(raw, list):
            raise ValueError("kinematics document joints must be a list")
        chain = []
        for item in raw:
            if not isinstance(item, Mapping) or not isinstance(item.get("origin"), Mapping):
                raise ValueError("each joint needs a name and origin")
            joint_type = item.get("type")
            axis = None if joint_type == "fixed" else _triple("axis", item.get("axis"))
            chain.append(ChainJoint(
                name=str(item.get("name")), joint_type=str(joint_type),
                xyz=_triple("origin.xyz", item["origin"].get("xyz")),
                rpy=_triple("origin.rpy", item["origin"].get("rpy")), axis=axis,
            ))
        self.chain = tuple(chain)
        self.revision = hashlib.sha256(json.dumps(
            document, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest()
        self._derive_closed_form()

    @classmethod
    def load(cls, path: Path | str = DEFAULT_KINEMATICS_PATH) -> "OmxKinematics":
        with open(path, encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
        if not isinstance(document, Mapping):
            raise ValueError("kinematics document must be a mapping")
        return cls(document)

    @property
    def planning_scene_revision(self) -> str:
        # "kin:" marks a geometry-only revision; there is no collision scene (D-402 §2).
        return "kin:" + self.revision

    def _derive_closed_form(self) -> None:
        """Fail closed unless the chain has the shape the analytic IK assumes."""
        names = tuple(joint.name for joint in self.chain)
        if names != ARM_JOINTS + ("end_effector_joint",):
            raise ValueError("chain must be joint1..joint5 then end_effector_joint")
        expected_axes = ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (0.0, 1.0, 0.0),
                         (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
        for joint, axis in zip(self.chain[:5], expected_axes):
            if joint.joint_type != "revolute" or joint.axis != axis:
                raise ValueError(f"{joint.name} axis/type does not match the analytic IK shape")
        if self.chain[5].joint_type != "fixed":
            raise ValueError("end_effector_joint must be fixed")
        if any(value != 0.0 for joint in self.chain for value in joint.rpy):
            raise ValueError("analytic IK requires zero origin rpy on every chain joint")
        j1, j2, j3, j4, j5, tcp = (joint.xyz for joint in self.chain)
        if any(abs(value) > _EPS for value in (j2[1], j3[1], j4[1], j5[1], j5[2])):
            raise ValueError("joint2..joint5 origins must lie in the arm plane / on the roll axis")
        self.base_xy = (j1[0], j1[1])
        self.shoulder_offset_m = j2[0]
        self.shoulder_height_m = j1[2] + j2[2]
        self.link1 = (j3[0], j3[2])
        self.link2 = (j4[0], j4[2])
        self.l1 = math.hypot(*self.link1)
        self.l2 = math.hypot(*self.link2)
        self.alpha1 = math.atan2(self.link1[1], self.link1[0])
        self.alpha2 = math.atan2(self.link2[1], self.link2[0])
        self.wrist_length_m = j5[0]
        self.tcp_offset = tcp
        # Wrist point (joint4 axis) to TCP along the tool axis, for reach reporting.
        self.tool_length_m = j5[0] + tcp[0]

    def fk(self, joints: Sequence[float]) -> TcpPose:
        if len(joints) != 5:
            raise ValueError("FK requires joint1..joint5")
        q = [_finite("joint", value) for value in joints]
        rotation: Matrix = _IDENTITY
        position = (0.0, 0.0, 0.0)
        index = 0
        for joint in self.chain:
            offset = _matvec(rotation, joint.xyz)
            position = tuple(p + o for p, o in zip(position, offset))  # type: ignore[assignment]
            rotation = _matmul(rotation, _rpy(*joint.rpy))
            if joint.axis is not None:
                rotation = _matmul(rotation, _axis_angle(joint.axis, q[index]))
                index += 1
        approach = (rotation[0][0], rotation[1][0], rotation[2][0])
        error = math.acos(max(-1.0, min(1.0, -approach[2])))
        yaw = math.atan2(rotation[1][2], rotation[0][2])
        return TcpPose(position[0], position[1], position[2], yaw, error, rotation)

    def wrist_point(self, pose: TopDownPose) -> tuple[float, float, float]:
        """joint4-axis point for a top-down TCP target (independent of joint values)."""
        tx, ty, tz = self.tcp_offset
        c, s = math.cos(pose.yaw), math.sin(pose.yaw)
        return (pose.x - (tz * c - ty * s),
                pose.y - (tz * s + ty * c),
                pose.z + tx + self.wrist_length_m)

    def _solve_branch(
        self, pose: TopDownPose, singularity_radius_m: float,
    ) -> tuple[str, tuple[float, float, float, float] | None, str]:
        wx, wy, wz = self.wrist_point(pose)
        dx, dy = wx - self.base_xy[0], wy - self.base_xy[1]
        radial = math.hypot(dx, dy)
        q1 = math.atan2(dy, dx)
        r = radial - self.shoulder_offset_m
        h = wz - self.shoulder_height_m
        d = math.hypot(r, h)
        if radial < singularity_radius_m:
            return IK_SINGULAR, None, f"wrist radius {radial:.4f} m"
        if d > self.l1 + self.l2 or d < abs(self.l1 - self.l2):
            return IK_UNREACHABLE, None, f"planar wrist distance {d:.4f} m"
        cos_beta = (self.l1 * self.l1 + d * d - self.l2 * self.l2) / (2.0 * self.l1 * d)
        beta = math.acos(max(-1.0, min(1.0, cos_beta)))
        e1 = math.atan2(h, r) + beta  # elbow-up branch
        elbow_r, elbow_h = self.l1 * math.cos(e1), self.l1 * math.sin(e1)
        e2 = math.atan2(h - elbow_h, r - elbow_r)
        q2 = wrap_angle(self.alpha1 - e1)
        q3 = wrap_angle(self.alpha2 - e2 - q2)
        q4 = wrap_angle(math.pi / 2.0 - q2 - q3)
        return IK_OK, (q1, q2, q3, q4), ""

    def solve_top_down(self, pose: TopDownPose, limits: IkLimits, *,
                       reference_q5: float = 0.0) -> IkResult:
        """Return joint1..joint5 for a top-down target or a typed rejection.

        The gripper is symmetric under 180 deg about the tool axis, so ``yaw``
        and ``yaw + pi`` are both candidates; the in-limit q5 nearest
        ``reference_q5`` wins (D-402 §5).
        """
        if not isinstance(pose, TopDownPose) or not isinstance(limits, IkLimits):
            raise TypeError("solve_top_down requires TopDownPose and IkLimits")
        reference = _finite("reference_q5", reference_q5)
        position = (pose.x, pose.y, pose.z)
        if any(value < low or value > high for value, low, high in zip(
                position, limits.workspace_min_m, limits.workspace_max_m)):
            return IkResult(IK_OUTSIDE_WORKSPACE, detail="TCP target outside workspace bounds")
        candidates = []
        failure: tuple[str, str] | None = None
        arm_in_limits = False
        for yaw in (pose.yaw, pose.yaw + math.pi):
            candidate_pose = TopDownPose(pose.x, pose.y, pose.z, wrap_angle(yaw))
            reason, solved, detail = self._solve_branch(candidate_pose, limits.singularity_radius_m)
            if solved is None:
                failure = failure or (reason, detail)
                continue
            if any(not (limits.position_limits[name][0] <= value <= limits.position_limits[name][1])
                   for name, value in zip(ARM_JOINTS[:4], solved)):
                failure = failure or (IK_JOINT_LIMIT, "joint1..joint4 outside profile limits")
                continue
            arm_in_limits = True
            lower, upper = limits.position_limits["joint5"]
            base_q5 = wrap_angle(solved[0] - candidate_pose.yaw)
            for turns in (-1, 0, 1):
                q5 = base_q5 + turns * 2.0 * math.pi
                if lower <= q5 <= upper:
                    candidates.append((abs(q5 - reference), solved + (q5,), candidate_pose.yaw))
        if candidates:
            _, joints, yaw = min(candidates, key=lambda item: item[0])
            return IkResult(IK_OK, joints=joints, yaw=yaw)
        if arm_in_limits:
            return IkResult(IK_YAW_LIMIT, detail="no joint5 value within limits reaches the yaw")
        assert failure is not None
        return IkResult(failure[0], detail=failure[1])

    def tool_down_sum_error(self, joints: Sequence[float]) -> float:
        """|q2 + q3 + q4 - pi/2| wrapped; zero means exactly top-down."""
        return abs(wrap_angle(joints[1] + joints[2] + joints[3] - math.pi / 2.0))
