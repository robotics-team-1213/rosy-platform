"""Runtime VisualOffsetNet (V7/V8) + SE(2) IK + Open-Loop Lock adapter for ACT HTTP serving.

Keeps zero top-level imports of ``torch``, ``lerobot``, ``mujoco``, ``deploy/``, or ``tools/`` so
lightweight host unit tests run without GPU dependencies (D-427).
"""
from __future__ import annotations

from hashlib import sha256
import math
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence
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
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)
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


def _build_torch_models():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class _SpatialSoftmaxV7(nn.Module):
        def __init__(self, height: int, width: int):
            super().__init__()
            pos_x, pos_y = torch.meshgrid(
                torch.linspace(-1.0, 1.0, height),
                torch.linspace(-1.0, 1.0, width),
                indexing="ij",
            )
            self.register_buffer("pos_x", pos_x.reshape(-1))
            self.register_buffer("pos_y", pos_y.reshape(-1))

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            b, c, h, w = x.shape
            attn = torch.softmax(x.reshape(b, c, h * w), dim=-1)
            return torch.cat([torch.sum(attn * self.pos_x, dim=-1), torch.sum(attn * self.pos_y, dim=-1)], dim=-1)

    def _branch_v7() -> nn.Sequential:
        return nn.Sequential(
            nn.Conv2d(4, 24, kernel_size=5, stride=2, padding=2),
            nn.GroupNorm(4, 24),
            nn.SiLU(inplace=True),
            nn.Conv2d(24, 48, kernel_size=3, stride=2, padding=1),
            nn.GroupNorm(8, 48),
            nn.SiLU(inplace=True),
            nn.Conv2d(48, 64, kernel_size=3, stride=2, padding=1),
            nn.GroupNorm(8, 64),
            nn.SiLU(inplace=True),
            nn.Conv2d(64, 32, kernel_size=3, stride=1, padding=1),
            nn.GroupNorm(4, 32),
            nn.SiLU(inplace=True),
        )

    class _VisualOffsetNetV7(nn.Module):
        def __init__(self, in_hw: tuple[int, int] = (240, 320)):
            super().__init__()
            self.in_hw = in_hw
            self.top_net, self.side_net, self.wrist_net = _branch_v7(), _branch_v7(), _branch_v7()
            self.softmax = _SpatialSoftmaxV7(in_hw[0] // 8, in_hw[1] // 8)
            self.head = nn.Sequential(
                nn.Linear(192, 128), nn.SiLU(inplace=True), nn.Dropout(0.1),
                nn.Linear(128, 64), nn.SiLU(inplace=True), nn.Linear(64, 3),
            )
            self.aux_top, self.aux_side, self.aux_wrist = nn.Linear(64, 3), nn.Linear(64, 3), nn.Linear(64, 3)
            self.register_buffer("mean", torch.tensor(_IMAGENET_MEAN).view(1, 3, 1, 1))
            self.register_buffer("std", torch.tensor(_IMAGENET_STD).view(1, 3, 1, 1))
            self.register_buffer("luma_w", torch.tensor((0.299, 0.587, 0.114)).view(1, 3, 1, 1))
            sx = torch.tensor([[-1.0, 0.0, 1.0], [-2.0, 0.0, 2.0], [-1.0, 0.0, 1.0]]).view(1, 1, 3, 3) / 4.0
            sy = torch.tensor([[-1.0, -2.0, -1.0], [0.0, 0.0, 0.0], [1.0, 2.0, 1.0]]).view(1, 1, 3, 3) / 4.0
            self.register_buffer("sobel_x", sx)
            self.register_buffer("sobel_y", sy)

        def _norm(self, x: torch.Tensor) -> torch.Tensor:
            if x.dtype == torch.uint8:
                x = x.float() / 255.0
            if x.shape[-2:] != self.in_hw:
                x = F.interpolate(x, size=self.in_hw, mode="bilinear", align_corners=False)
            rgb = (x - self.mean) / self.std
            lum = torch.sum(x * self.luma_w, dim=1, keepdim=True)
            gx = F.conv2d(lum, self.sobel_x, padding=1)
            gy = F.conv2d(lum, self.sobel_y, padding=1)
            edge = torch.sqrt(gx * gx + gy * gy + 1e-6)
            edge_norm = ((edge - edge.mean(dim=(-2, -1), keepdim=True)) / edge.std(dim=(-2, -1), keepdim=True).clamp_min(1e-4)).clamp(-3.0, 3.0)
            return torch.cat([rgb, edge_norm], dim=1)

        def forward(self, top: torch.Tensor, side: torch.Tensor, wrist: torch.Tensor):
            ft = self.softmax(self.top_net(self._norm(top)))
            fs = self.softmax(self.side_net(self._norm(side)))
            fw = self.softmax(self.wrist_net(self._norm(wrist)))
            return self.head(torch.cat([ft, fs, fw], dim=-1))

    class _RelativeSpatialSoftmaxV8(nn.Module):
        def __init__(self, height: int, width: int):
            super().__init__()
            pos_x, pos_y = torch.meshgrid(
                torch.linspace(-1.0, 1.0, height),
                torch.linspace(-1.0, 1.0, width),
                indexing="ij",
            )
            self.register_buffer("pos_x", pos_x.reshape(-1))
            self.register_buffer("pos_y", pos_y.reshape(-1))
            self.log_beta = nn.Parameter(torch.zeros(1))

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            b, c, h, w = x.shape
            beta = F.softplus(self.log_beta) + 0.5
            attn = torch.softmax(beta * x.reshape(b, c, h * w), dim=-1)
            return torch.cat([torch.sum(attn * self.pos_x, dim=-1), torch.sum(attn * self.pos_y, dim=-1)], dim=-1)

    def _branch_v8() -> nn.Sequential:
        return nn.Sequential(
            nn.Conv2d(3, 24, kernel_size=5, stride=2, padding=2),
            nn.InstanceNorm2d(24, affine=True),
            nn.SiLU(inplace=True),
            nn.Conv2d(24, 48, kernel_size=3, stride=2, padding=1),
            nn.GroupNorm(8, 48),
            nn.SiLU(inplace=True),
            nn.Conv2d(48, 64, kernel_size=3, stride=2, padding=1),
            nn.GroupNorm(8, 64),
            nn.SiLU(inplace=True),
            nn.Conv2d(64, 32, kernel_size=3, stride=1, padding=1),
            nn.GroupNorm(4, 32),
            nn.SiLU(inplace=True),
        )

    def _head_v8() -> nn.Sequential:
        return nn.Sequential(nn.Linear(64, 64), nn.SiLU(inplace=True), nn.Dropout(0.1), nn.Linear(64, 3))

    class _VisualOffsetNetV8(nn.Module):
        def __init__(self, arm_yaw_nom: float = 0.0, in_hw: tuple[int, int] = (240, 320)):
            super().__init__()
            self.in_hw = in_hw
            self.register_buffer("arm_yaw_nom", torch.tensor(float(arm_yaw_nom), dtype=torch.float32))
            self.top_net, self.side_net, self.wrist_net = _branch_v8(), _branch_v8(), _branch_v8()
            self.softmax = _RelativeSpatialSoftmaxV8(in_hw[0] // 8, in_hw[1] // 8)
            self.head_top, self.head_side, self.head_wrist = _head_v8(), _head_v8(), _head_v8()
            self.gate = nn.Sequential(nn.Linear(192, 32), nn.SiLU(inplace=True), nn.Linear(32, 9))

        def _norm(self, x: torch.Tensor) -> torch.Tensor:
            if x.dtype == torch.uint8:
                x = x.float() / 255.0
            if x.shape[-2:] != self.in_hw:
                x = F.interpolate(x, size=self.in_hw, mode="bilinear", align_corners=False)
            mu = x.mean(dim=(-2, -1), keepdim=True)
            sd = x.std(dim=(-2, -1), keepdim=True).clamp_min(0.05)
            return ((x - mu) / sd).clamp(-4.0, 4.0)

        def forward(self, top: torch.Tensor, side: torch.Tensor, wrist: torch.Tensor, q0: torch.Tensor):
            b, dev = top.shape[0], top.device
            ft = self.softmax(self.top_net(self._norm(top)))
            fs = self.softmax(self.side_net(self._norm(side)))
            fw = self.softmax(self.wrist_net(self._norm(wrist)))
            y_t, y_s, rw = self.head_top(ft), self.head_side(fs), self.head_wrist(fw)
            theta = self.arm_yaw_nom + q0.to(dev).reshape(b)
            ct, st = torch.cos(theta), torch.sin(theta)
            y_w = torch.stack([ct * rw[:, 0] - st * rw[:, 1], st * rw[:, 0] + ct * rw[:, 1], rw[:, 2]], dim=-1)
            w = torch.softmax(self.gate(torch.cat([ft, fs, fw], dim=-1)).view(b, 3, 3), dim=-1)
            w_w = w[:, :, 2].clamp(0.30, 0.60)
            scale = (1.0 - w_w) / (w[:, :, 0] + w[:, :, 1]).clamp_min(1e-6)
            w = torch.stack([w[:, :, 0] * scale, w[:, :, 1] * scale, w_w], dim=-1)
            pred = (w * torch.stack([y_t, y_s, y_w], dim=-1)).sum(dim=-1)
            return pred, y_t, y_s, y_w

    return _VisualOffsetNetV7, _VisualOffsetNetV8


def _clip3(vec: Sequence[float], clip_xy: float, clip_yaw: float) -> tuple[float, float, float]:
    return (
        float(np.clip(float(vec[0]), -clip_xy, clip_xy)),
        float(np.clip(float(vec[1]), -clip_xy, clip_xy)),
        float(np.clip(float(vec[2]), -clip_yaw, clip_yaw)),
    )


def load_visoff_predictor(policy_dir: Path, spec: Mapping[str, Any], device: str) -> Callable[[Mapping[str, Any], float], dict[str, Any]]:
    """Load V7 or V8 VisualOffsetNet weights lazily onto ``device``."""
    import torch

    net_v7_cls, net_v8_cls = _build_torch_models()
    target_device = torch.device(device)
    weights_path = policy_dir / spec["weights"]
    ckpt = torch.load(str(weights_path), map_location=target_device, weights_only=False)
    state_dict = ckpt["model"] if isinstance(ckpt, dict) and "model" in ckpt else ckpt
    in_hw = tuple(spec["in_hw"])
    version = spec["version"]
    if version == "v8":
        if isinstance(ckpt, dict) and ckpt.get("arm_yaw_nom") is not None:
            if abs(float(ckpt["arm_yaw_nom"]) - float(spec["arm_yaw_nom"])) > 1e-4:
                raise ValueError(f"checkpoint arm_yaw_nom {ckpt['arm_yaw_nom']} != visoff.json {spec['arm_yaw_nom']}")
        net = net_v8_cls(arm_yaw_nom=float(spec["arm_yaw_nom"]), in_hw=in_hw).to(target_device).eval()
    else:
        net = net_v7_cls(in_hw=in_hw).to(target_device).eval()
    net.load_state_dict(state_dict, strict=True)

    clip_xy, clip_yaw = float(spec["clip_xy_mm"]), float(spec["clip_yaw_deg"])

    def _to_tensor(img: Any) -> torch.Tensor:
        arr = np.ascontiguousarray(img)
        if arr.ndim != 3 or arr.shape[2] != 3:
            raise ValueError(f"expected HxWx3 RGB frame, got {arr.shape}")
        return torch.from_numpy(arr).to(target_device).permute(2, 0, 1).unsqueeze(0)

    def predict_offset(frames_rgb: Mapping[str, Any], q0_rad: float) -> dict[str, Any]:
        with torch.inference_mode():
            t = _to_tensor(frames_rgb["top"])
            s = _to_tensor(frames_rgb["side"])
            w_img = _to_tensor(frames_rgb["wrist"])
            if version == "v8":
                q0_t = torch.tensor([float(q0_rad)], dtype=torch.float32, device=target_device)
                pred, yt, ys, yw = net(t, s, w_img, q0_t)
                yt_c = _clip3(yt[0].detach().cpu().tolist(), clip_xy, clip_yaw)
                ys_c = _clip3(ys[0].detach().cpu().tolist(), clip_xy, clip_yaw)
                yw_c = _clip3(yw[0].detach().cpu().tolist(), clip_xy, clip_yaw)
                return {
                    "fused": _clip3(pred[0].detach().cpu().tolist(), clip_xy, clip_yaw),
                    "top": yt_c,
                    "side": ys_c,
                    "wrist": yw_c,
                    "agree_tw_mm": round(float(torch.linalg.norm(yt[0, :2] - yw[0, :2]).item()), 3),
                }
            pred = net(t, s, w_img)
            return {"fused": _clip3(pred[0].detach().cpu().tolist(), clip_xy, clip_yaw)}

    return predict_offset


class VisoffEpisodeController:
    """Stateful per-episode wrapper: decoupled q_obs -> ACT chunk + Open-Loop Lock + SE(2) IK ramp."""

    def __init__(
        self,
        base_predict: Callable[[dict[str, Any]], Sequence[Sequence[float]]],
        visoff_fn: Callable[[Mapping[str, Any], float], Mapping[str, Any]],
        kin: OmxNominalKinematics,
        spec: Mapping[str, Any],
        n_action_steps: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._base_predict = base_predict
        self._visoff_fn = visoff_fn
        self._kin = kin
        self._spec = spec
        self._n_exec = int(n_action_steps)
        self._clock = clock
        self._lock_steps = tuple(int(v) for v in spec["lock_steps"])
        self._lock_start = self._lock_steps[0]
        self._lock_end = self._lock_steps[-1]
        self._max_dq_rad = math.radians(float(spec["max_dq_deg"]))
        self._reset_state(episode_id=None)

    def _reset_state(self, *, episode_id: str | None) -> None:
        self._episode_id = episode_id
        self._step_idx = 0
        self._last_call_t: float | None = None
        self._last_applied_dq = np.zeros(5, dtype=np.float64)
        self._buf_fused: list[tuple[float, float, float]] = []
        self._buf_top: list[tuple[float, float, float]] = []
        self._buf_side: list[tuple[float, float, float]] = []
        self._buf_wrist: list[tuple[float, float, float]] = []
        self._agree_tw: list[float] = []
        self._locked_dxyw: tuple[float, float, float] | None = None
        self._eff_dxyw: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._fallback_wrist = False
        self._abstained = False
        self._keep_cams: list[int] | None = None

    def _freeze_lock(self) -> None:
        arr_f = np.asarray(self._buf_fused, dtype=np.float64)
        version = self._spec["version"]
        if version == "v7":
            med = np.median(arr_f, axis=0)
            self._locked_dxyw = (float(med[0]), float(med[1]), float(med[2]))
        else:
            cam_mode = self._spec["cam_mode"]
            arr_w = np.asarray(self._buf_wrist, dtype=np.float64)
            med_w = np.median(arr_w, axis=0)
            if cam_mode == "tiebreak":
                bt = np.asarray(self._buf_top, dtype=np.float64)
                bs = np.asarray(self._buf_side, dtype=np.float64)
                mt, ms = np.median(bt, axis=0), np.median(bs, axis=0)
                d_ts_y, d_ts_w = abs(mt[1] - ms[1]), abs(mt[2] - ms[2])
                d_ts_xy = math.hypot(mt[0] - ms[0], mt[1] - ms[1])
                d_tw = math.hypot(mt[0] - med_w[0], mt[1] - med_w[1])
                if d_ts_y <= 3.0 and d_ts_w <= 1.5 and d_ts_xy <= 5.0 and d_tw <= 8.0:
                    keep = np.array([1.0, 1.0, 0.0 if d_tw > 3.8 else 1.0], dtype=np.float64)
                elif abs(ms[1] - med_w[1]) <= 3.0 and abs(ms[2] - med_w[2]) <= 1.0:
                    keep = np.array([0.0, 1.0, 1.0], dtype=np.float64)
                else:
                    keep = np.array([0.0, 0.0, 1.0], dtype=np.float64)
                self._keep_cams = [int(k) for k in keep]
                pw = np.asarray(self._spec["prec_w"], dtype=np.float64)
                w = pw * keep[:, None]
                w = w / np.maximum(w.sum(axis=0, keepdims=True), 1e-9)
                active = w[0] * bt + w[1] * bs + w[2] * arr_w
                self._fallback_wrist = bool(keep[0] == 0.0 and keep[1] == 0.0)
            else:
                agr_med = float(np.median(self._agree_tw))
                self._fallback_wrist = bool(cam_mode == "auto" and agr_med > float(self._spec["agree_thresh_mm"]))
                use_wrist = bool(cam_mode == "wrist" or self._fallback_wrist)
                active = arr_w if use_wrist else arr_f

            med = np.median(active, axis=0)
            self._locked_dxyw = (float(med[0]), float(med[1]), float(med[2]))
            if len(active) >= 2:
                mad_xy = float(np.median(np.hypot(active[:, 0] - med[0], active[:, 1] - med[1])))
                mad_yaw = float(np.median(np.abs(active[:, 2] - med[2])))
                mad_lim = float(self._spec["mad_wrist_xy_mm"] if self._fallback_wrist else self._spec["mad_xy_mm"])
                if mad_xy > mad_lim or mad_yaw > float(self._spec["mad_yaw_deg"]):
                    self._abstained = True
                    self._eff_dxyw = (0.0, 0.0, 0.0)
                    return

        if math.hypot(self._locked_dxyw[0], self._locked_dxyw[1]) >= float(self._spec["deadzone_xy_mm"]):
            ex, ey = self._locked_dxyw[0], self._locked_dxyw[1]
        else:
            ex, ey = 0.0, 0.0
        ew = self._locked_dxyw[2] if abs(self._locked_dxyw[2]) >= float(self._spec["deadzone_yaw_deg"]) else 0.0
        self._eff_dxyw = (ex, ey, ew)

    def __call__(self, obs: dict[str, Any]) -> tuple[list[list[float]], dict[str, Any]]:
        now = float(self._clock())
        req_ep = obs.get("episode_id")
        req_step = obs.get("step_idx")
        req_reset = bool(obs.get("reset"))
        timeout_expired = (
            req_ep is None
            and self._last_call_t is not None
            and (now - self._last_call_t) > float(self._spec["episode_timeout_s"])
        )
        ep_changed = req_ep is not None and req_ep != self._episode_id
        if req_reset or ep_changed or timeout_expired or req_step == 0:
            self._reset_state(episode_id=req_ep)
        elif req_ep is not None and self._episode_id is None:
            self._episode_id = req_ep

        step_idx = int(req_step) if req_step is not None else self._step_idx
        raw_state = np.asarray(obs["state"], dtype=np.float64)
        decoupled = raw_state.copy()
        decoupled[:5] -= self._last_applied_dq
        base_obs = {**obs, "state": [float(v) for v in decoupled]}

        raw_chunk = np.asarray(self._base_predict(base_obs), dtype=np.float64)
        chunk = raw_chunk[: self._n_exec].copy()
        n_steps = len(chunk)
        chunk_end = step_idx + max(n_steps, 1) - 1

        sample: dict[str, Any] | None = None
        if step_idx == 0 or (self._locked_dxyw is None and chunk_end >= self._lock_start):
            sample = dict(self._visoff_fn(obs["frames_rgb"], float(raw_state[0])))

        if self._locked_dxyw is None and sample is not None and chunk_end >= self._lock_start:
            clip_xy, clip_yaw = float(self._spec["clip_xy_mm"]), float(self._spec["clip_yaw_deg"])
            self._buf_fused.append(_clip3(sample["fused"], clip_xy, clip_yaw))
            if self._spec["version"] == "v8":
                self._buf_top.append(_clip3(sample["top"], clip_xy, clip_yaw))
                self._buf_side.append(_clip3(sample["side"], clip_xy, clip_yaw))
                self._buf_wrist.append(_clip3(sample["wrist"], clip_xy, clip_yaw))
                self._agree_tw.append(float(sample["agree_tw_mm"]))
            if chunk_end >= self._lock_end:
                self._freeze_lock()

        ramp_frames = float(self._spec["ramp_frames"])
        applied = np.zeros(5, dtype=np.float64)
        eff = self._eff_dxyw
        any_eff = eff[0] != 0.0 or eff[1] != 0.0 or eff[2] != 0.0
        for k in range(n_steps):
            frame_idx = step_idx + k
            if self._locked_dxyw is not None and frame_idx >= self._lock_end and any_eff:
                ramp = min(1.0, (frame_idx - (self._lock_end - 1)) / ramp_frames)
                dq = ik_delta_se2(
                    self._kin,
                    chunk[k],
                    -eff[0] / 1000.0,
                    -eff[1] / 1000.0,
                    -math.radians(eff[2]),
                    self._max_dq_rad,
                    iters=2,
                )
                applied = ramp * dq
                chunk[k, :5] = chunk[k, :5] + applied
            else:
                applied = np.zeros(5, dtype=np.float64)

        self._last_applied_dq = applied
        self._step_idx = step_idx + n_steps
        self._last_call_t = now

        diag: dict[str, Any] = {
            "version": self._spec["version"],
            "step_idx": step_idx,
            "locked": self._locked_dxyw is not None,
            "locked_dxyw": [round(v, 3) for v in self._locked_dxyw] if self._locked_dxyw is not None else None,
            "eff_dxyw": [round(v, 3) for v in self._eff_dxyw],
            "fallback_wrist": self._fallback_wrist,
            "abstained": self._abstained,
            "ramp_end": round(float(np.max(np.abs(np.degrees(applied)))), 3),
        }
        if self._keep_cams is not None:
            diag["keep_cams"] = self._keep_cams
        if sample is not None:
            diag["preview_dxyw"] = [round(v, 3) for v in sample["fused"]]
            if "agree_tw_mm" in sample:
                diag["agree_tw_mm"] = round(float(sample["agree_tw_mm"]), 3)
                diag["branches"] = {
                    role: [round(v, 3) for v in sample[role]]
                    for role in ("top", "side", "wrist")
                    if role in sample
                }
        return [[float(x) for x in row] for row in chunk], diag


def build_visoff_controller(
    policy_dir: Path,
    spec: Mapping[str, Any],
    base_predict: Callable[[dict[str, Any]], Sequence[Sequence[float]]],
    n_action_steps: int,
    device: str,
) -> VisoffEpisodeController:
    """Instantiate kinematics + GPU VisualOffsetNet + stateful episode controller."""
    kin = OmxNominalKinematics.from_spec(spec)
    visoff_fn = load_visoff_predictor(policy_dir, spec, device)
    return VisoffEpisodeController(base_predict, visoff_fn, kin, spec, n_action_steps)
