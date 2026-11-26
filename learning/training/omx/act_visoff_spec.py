"""Policy-dir VisualOffsetNet spec (V7/V8), the nominal 5-DoF kinematics and the coaxial SE(2) IK the runtime uses.

No torch here: reading and validating a spec, and the IK, run on hosts without it (D-427). Split out of
act_visoff_runtime.py on 2026-11-25 for the D-766 600-line file limit.
"""
from __future__ import annotations

from hashlib import sha256
import math
from pathlib import Path
import time
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET

import numpy as np

VISOFF_SPEC_FILE = "visoff.json"
VISOFF_SCHEMA = "rosy.omx-visoff-runtime.v1"
DEFAULT_URDF = (
    Path(__file__).resolve().parents[2]
    / "envs/isaac/assets/omx_f_palletizing_description/urdf/omx_f_palletizing.urdf"
)
_JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5")
_REG_DIAG6 = np.diag([1e-7, 1e-7, 1e-7, 1e-4, 1e-4, 1e-3])
_DEFAULT_PREC_W = (
    (0.85, 0.65, 0.25),
    (0.05, 0.25, 0.65),
    (0.10, 0.10, 0.10),
)
_CAM_MODES = frozenset({"auto", "fused", "wrist", "tiebreak"})


def _sha256_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    return float(value)


def _finite_vec(values: Any, length: int, label: str) -> list[float]:
    if not isinstance(values, (list, tuple)) or len(values) != length:
        raise ValueError(f"{label} must be length-{length} list")
    return [_finite_float(v, f"{label}[{i}]") for i, v in enumerate(values)]


def _pos_int(value: Any, label: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}, got {value!r}")
    return int(value)


def read_visoff_spec(policy_dir: Path, *, chunk_size: int) -> dict[str, Any] | None:
    """Validate optional ``visoff.json`` in ``policy_dir`` (None when plain ACT)."""
    import json

    spec_path = policy_dir / VISOFF_SPEC_FILE
    if spec_path.is_symlink():
        raise ValueError(f"{VISOFF_SPEC_FILE} cannot be a symlink")
    if not spec_path.exists():
        return None
    if not spec_path.is_file():
        raise ValueError(f"{VISOFF_SPEC_FILE} must be a regular file")

    raw = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{VISOFF_SPEC_FILE} must contain a JSON object")
    if raw.get("schema") != VISOFF_SCHEMA:
        raise ValueError(f"unsupported visoff schema {raw.get('schema')!r}; expected {VISOFF_SCHEMA!r}")
    version = raw.get("version")
    if version not in ("v7", "v8"):
        raise ValueError(f"unsupported visoff version {version!r}; expected 'v7' or 'v8'")

    weights_rel = raw.get("weights")
    if not isinstance(weights_rel, str) or not weights_rel.strip():
        raise ValueError("weights must be a non-empty relative path")
    rel_path = Path(weights_rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise ValueError(f"weights path {weights_rel!r} must stay inside policy_dir")
    weights_path = policy_dir / rel_path
    if weights_path.is_symlink():
        raise ValueError(f"weights file {weights_rel!r} cannot be a symlink")
    if not weights_path.is_file():
        raise ValueError(f"missing weights file {weights_path}")
    resolved_root = policy_dir.resolve()
    if not weights_path.resolve().is_relative_to(resolved_root):
        raise ValueError(f"weights path {weights_rel!r} escapes policy_dir")

    weights_sha = raw.get("weights_sha256")
    if not _is_hex64(weights_sha):
        raise ValueError("weights_sha256 must be 64-char lowercase hex")
    actual_sha = _sha256_file(weights_path)
    if actual_sha != weights_sha:
        raise ValueError(f"{weights_rel} sha256 {actual_sha} != pinned {weights_sha}")

    base_xyz = _finite_vec(raw.get("base_xyz"), 3, "base_xyz")
    yaw = _finite_float(raw.get("yaw"), "yaw")
    tcp_xyz = _finite_vec(raw.get("tcp_xyz"), 3, "tcp_xyz")
    limits_low = _finite_vec(raw.get("limits_low"), 5, "limits_low")
    limits_high = _finite_vec(raw.get("limits_high"), 5, "limits_high")
    for i, (lo, hi) in enumerate(zip(limits_low, limits_high)):
        if lo >= hi:
            raise ValueError(f"limits_low[{i}]={lo} must be < limits_high[{i}]={hi}")

    arm_yaw_nom: float | None = None
    if version == "v8":
        if "arm_yaw_nom" not in raw:
            raise ValueError("v8 visoff.json requires arm_yaw_nom")
        arm_yaw_nom = _finite_float(raw.get("arm_yaw_nom"), "arm_yaw_nom")
    elif raw.get("arm_yaw_nom") is not None:
        arm_yaw_nom = _finite_float(raw.get("arm_yaw_nom"), "arm_yaw_nom")

    n_action_steps: int | None = None
    if raw.get("n_action_steps") is not None:
        n_action_steps = _pos_int(raw["n_action_steps"], "n_action_steps", minimum=1)
        if n_action_steps > chunk_size:
            raise ValueError(f"n_action_steps={n_action_steps} > chunk_size={chunk_size}")

    raw_lock = raw.get("lock_steps")
    if not isinstance(raw_lock, list) or not raw_lock:
        raise ValueError("lock_steps must be a non-empty list of integers >= 0")
    lock_steps = [_pos_int(v, f"lock_steps[{i}]", minimum=0) for i, v in enumerate(raw_lock)]
    if sorted(set(lock_steps)) != lock_steps:
        raise ValueError("lock_steps must be strictly increasing integers")
    ramp_frames = _pos_int(raw.get("ramp_frames"), "ramp_frames", minimum=1)

    max_dq_deg = _finite_float(raw.get("max_dq_deg", 6.0), "max_dq_deg")
    if not (0.0 < max_dq_deg <= 15.0):
        raise ValueError(f"max_dq_deg must be in (0, 15], got {max_dq_deg}")
    clip_xy_mm = _finite_float(raw.get("clip_xy_mm", 13.0), "clip_xy_mm")
    clip_yaw_deg = _finite_float(raw.get("clip_yaw_deg", 3.0), "clip_yaw_deg")
    if clip_xy_mm <= 0.0 or clip_yaw_deg <= 0.0:
        raise ValueError("clip_xy_mm and clip_yaw_deg must be > 0")
    deadzone_xy_mm = _finite_float(raw.get("deadzone_xy_mm", 0.8), "deadzone_xy_mm")
    deadzone_yaw_deg = _finite_float(raw.get("deadzone_yaw_deg", 0.35), "deadzone_yaw_deg")
    if deadzone_xy_mm < 0.0 or deadzone_yaw_deg < 0.0:
        raise ValueError("deadzone thresholds must be >= 0")

    cam_mode = raw.get("cam_mode", "auto")
    if version == "v8":
        if cam_mode not in _CAM_MODES:
            raise ValueError(f"unsupported cam_mode {cam_mode!r}; expected {sorted(_CAM_MODES)}")
    agree_thresh_mm = _finite_float(raw.get("agree_thresh_mm", 3.8), "agree_thresh_mm")
    mad_xy_mm = _finite_float(raw.get("mad_xy_mm", 2.5), "mad_xy_mm")
    mad_wrist_xy_mm = _finite_float(raw.get("mad_wrist_xy_mm", 1.8), "mad_wrist_xy_mm")
    mad_yaw_deg = _finite_float(raw.get("mad_yaw_deg", 1.0), "mad_yaw_deg")
    if min(agree_thresh_mm, mad_xy_mm, mad_wrist_xy_mm, mad_yaw_deg) <= 0.0:
        raise ValueError("agree_thresh_mm and MAD limits must be > 0")

    prec_w = _DEFAULT_PREC_W
    if raw.get("prec_w") is not None:
        pw_raw = raw["prec_w"]
        if not isinstance(pw_raw, list) or len(pw_raw) != 3:
            raise ValueError("prec_w must be a 3x3 matrix")
        rows = [_finite_vec(r, 3, f"prec_w[{i}]") for i, r in enumerate(pw_raw)]
        if any(v <= 0.0 for r in rows for v in r):
            raise ValueError("prec_w entries must be > 0")
        prec_w = tuple(tuple(r) for r in rows)

    episode_timeout_s = _finite_float(raw.get("episode_timeout_s", 10.0), "episode_timeout_s")
    if episode_timeout_s <= 0.0:
        raise ValueError("episode_timeout_s must be > 0")

    in_hw_raw = raw.get("in_hw", [240, 320])
    if not isinstance(in_hw_raw, (list, tuple)) or len(in_hw_raw) != 2:
        raise ValueError("in_hw must be [height, width]")
    in_hw = (_pos_int(in_hw_raw[0], "in_hw[0]"), _pos_int(in_hw_raw[1], "in_hw[1]"))

    urdf_raw = raw.get("urdf_path")
    urdf_path = Path(urdf_raw).expanduser() if isinstance(urdf_raw, str) and urdf_raw.strip() else DEFAULT_URDF
    if not urdf_path.is_file():
        raise ValueError(f"missing URDF file {urdf_path}")

    return {
        "schema": VISOFF_SCHEMA,
        "version": version,
        "weights": weights_rel,
        "weights_path": str(weights_path),
        "weights_sha256": weights_sha,
        "base_xyz": base_xyz,
        "yaw": yaw,
        "arm_yaw_nom": arm_yaw_nom,
        "tcp_xyz": tcp_xyz,
        "limits_low": limits_low,
        "limits_high": limits_high,
        "n_action_steps": n_action_steps,
        "lock_steps": lock_steps,
        "ramp_frames": ramp_frames,
        "max_dq_deg": max_dq_deg,
        "clip_xy_mm": clip_xy_mm,
        "clip_yaw_deg": clip_yaw_deg,
        "deadzone_xy_mm": deadzone_xy_mm,
        "deadzone_yaw_deg": deadzone_yaw_deg,
        "cam_mode": cam_mode,
        "agree_thresh_mm": agree_thresh_mm,
        "mad_xy_mm": mad_xy_mm,
        "mad_wrist_xy_mm": mad_wrist_xy_mm,
        "mad_yaw_deg": mad_yaw_deg,
        "prec_w": prec_w,
        "episode_timeout_s": episode_timeout_s,
        "in_hw": in_hw,
        "urdf_path": str(urdf_path),
    }


def _rot_axis(axis: np.ndarray, angle: float) -> np.ndarray:
    x, y, z = axis / np.linalg.norm(axis)
    c, s, k = math.cos(angle), math.sin(angle), 1.0 - math.cos(angle)
    return np.array([
        [c + x * x * k, x * y * k - z * s, x * z * k + y * s],
        [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
        [z * x * k - y * s, z * y * k + x * s, c + z * z * k],
    ], dtype=np.float64)


class OmxNominalKinematics:
    """Pure-NumPy 5-DoF URDF forward kinematics compatible with coaxial SE(2) IK."""

    def __init__(
        self,
        base_xyz: Sequence[float],
        yaw: float,
        tcp_xyz: Sequence[float],
        limits_low: Sequence[float],
        limits_high: Sequence[float],
        urdf_path: Path = DEFAULT_URDF,
    ):
        root = ET.parse(str(urdf_path)).getroot()
        joints = {j.get("name"): j for j in root.iter("joint")}
        vec = lambda j, tag: np.array([float(v) for v in j.find(tag).get("xyz").split()], dtype=np.float64)  # noqa: E731
        pairs = []
        for name in _JOINTS:
            origin, axis = vec(joints[name], "origin"), vec(joints[name], "axis")
            pairs.append((origin, axis / np.linalg.norm(axis)))
        # Match omx_two_arm_kin.Arm convention: base[:2] sits on the joint1 axis.
        pairs[0] = (np.array([0.0, 0.0, pairs[0][0][2]], dtype=np.float64), pairs[0][1])
        self.chain = pairs
        self.base = np.asarray(base_xyz, dtype=np.float64)
        self.yaw = float(yaw)
        self.R0 = _rot_axis(np.array([0.0, 0.0, 1.0], dtype=np.float64), self.yaw)
        self.tcp = np.asarray(tcp_xyz, dtype=np.float64)
        self._limits_low = np.asarray(limits_low, dtype=np.float64)
        self._limits_high = np.asarray(limits_high, dtype=np.float64)

    @classmethod
    def from_spec(cls, spec: Mapping[str, Any]) -> "OmxNominalKinematics":
        return cls(
            spec["base_xyz"],
            spec["yaw"],
            spec["tcp_xyz"],
            spec["limits_low"],
            spec["limits_high"],
            Path(spec["urdf_path"]),
        )

    def _tcp_and_R(self, q: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
        R, p = self.R0, self.base
        for (origin, axis), angle in zip(self.chain, q[:5]):
            p = p + R @ origin
            R = R @ _rot_axis(axis, float(angle))
        return p + R @ self.tcp, R


def ik_delta_xy(nom_arm: OmxNominalKinematics, q: Sequence[float], dx_m: float, dy_m: float, max_dq_rad: float, iters: int = 2) -> np.ndarray:
    """Compute joint delta dq[:5] shifting TCP by (dx_m, dy_m, 0) in world while holding R and Z."""
    q0 = np.asarray(q[:5], dtype=np.float64).copy()
    p0, R0 = nom_arm._tcp_and_R(q0)
    target_p = p0 + np.array([float(dx_m), float(dy_m), 0.0], dtype=np.float64)
    q_cur = q0.copy()
    eps = 1e-6

    for _ in range(max(1, iters)):
        p_cur, R_cur = nom_arm._tcp_and_R(q_cur)
        dR = R_cur @ R0.T
        rot_err = 0.5 * np.array([dR[2, 1] - dR[1, 2], dR[0, 2] - dR[2, 0], dR[1, 0] - dR[0, 1]], dtype=np.float64)
        err = np.concatenate([target_p - p_cur, -0.3 * rot_err])
        J = np.zeros((6, 5), dtype=np.float64)
        for k in range(5):
            qp = q_cur.copy()
            qp[k] += eps
            pk, Rk = nom_arm._tcp_and_R(qp)
            dRk = Rk @ R_cur.T
            rk_vec = 0.5 * np.array([dRk[2, 1] - dRk[1, 2], dRk[0, 2] - dRk[2, 0], dRk[1, 0] - dRk[0, 1]], dtype=np.float64)
            J[:3, k] = (pk - p_cur) / eps
            J[3:, k] = 0.3 * rk_vec / eps
        step = J.T @ np.linalg.solve(J @ J.T + _REG_DIAG6, err)
        q_cur = np.clip(q_cur + step, nom_arm._limits_low, nom_arm._limits_high)

    dq = np.clip(q_cur - q0, -float(max_dq_rad), float(max_dq_rad))
    q_final = np.clip(q0 + dq, nom_arm._limits_low, nom_arm._limits_high)
    return q_final - q0


def ik_delta_se2(
    nom_arm: OmxNominalKinematics,
    q: Sequence[float],
    comp_dx_m: float,
    comp_dy_m: float,
    comp_dyaw_rad: float,
    max_dq_rad: float,
    iters: int = 2,
) -> np.ndarray:
    """Exact coaxial SE(2) correction: unclipped XY IK first, then joint1 += comp_dyaw_rad, then clip."""
    q0 = np.asarray(q[:5], dtype=np.float64).copy()
    dq = ik_delta_xy(nom_arm, q0, comp_dx_m, comp_dy_m, max_dq_rad=math.pi, iters=iters)
    dq[0] += float(comp_dyaw_rad)
    dq = np.clip(dq, -float(max_dq_rad), float(max_dq_rad))
    q_final = np.clip(q0 + dq, nom_arm._limits_low, nom_arm._limits_high)
    return q_final - q0
