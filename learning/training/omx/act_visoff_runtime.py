"""Runtime VisualOffsetNet (V7/V8) Open-Loop Lock adapter and server glue for ACT HTTP serving.

Keeps zero top-level imports of ``torch``, ``lerobot``, ``mujoco``, ``deploy/``, or ``tools/`` so
lightweight host unit tests run without GPU dependencies (D-427). The policy-dir spec, the nominal kinematics and
the IK live in act_visoff_spec.py; their names are re-exported here for the server and the tests.
"""
from __future__ import annotations

import math
import time
from typing import Any, Callable, Mapping, Sequence

import numpy as np

_IMAGENET_MEAN = (0.485, 0.456, 0.406)

_IMAGENET_STD = (0.229, 0.224, 0.225)

try:
    from act_visoff_spec import OmxNominalKinematics, VISOFF_SCHEMA, VISOFF_SPEC_FILE, ik_delta_se2, read_visoff_spec
except ImportError:
    from learning.training.omx.act_visoff_spec import (  # noqa: E402
        OmxNominalKinematics,
        VISOFF_SCHEMA,
        VISOFF_SPEC_FILE,
        ik_delta_se2,
        read_visoff_spec,
    )


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

def parse_episode_fields(req: Any) -> tuple[dict[str, Any], str | None]:
    """The optional episode fields of an /infer request, and why they are malformed (None when they are fine)."""
    episode_id, step_idx, reset = req.get("episode_id"), req.get("step_idx"), req.get("reset")
    if episode_id is not None and (not isinstance(episode_id, str) or not (1 <= len(episode_id) <= 128) or not episode_id.strip()):
        return {}, "episode_id must be a non-empty string (<=128 chars)"
    if step_idx is not None and (isinstance(step_idx, bool) or not isinstance(step_idx, int) or step_idx < 0):
        return {}, "step_idx must be a non-negative integer"
    if reset is not None and not isinstance(reset, bool):
        return {}, "reset must be a boolean"
    return {k: v for k, v in (("episode_id", episode_id), ("step_idx", step_idx), ("reset", reset)) if v is not None}, None


def visoff_output(raw_out: Any) -> tuple[Any, dict[str, Any] | None]:
    """A controller answers (chunk, diagnostics); a plain policy answers the chunk alone."""
    if isinstance(raw_out, tuple) and len(raw_out) == 2 and isinstance(raw_out[1], dict):
        return raw_out
    return raw_out, None


def visoff_entry(policy_dir, spec, predict, n_steps: int, device: str, plain: bool, builder=None):
    """Wrap a plain ACT predict with the VisualOffsetNet controller when the policy dir carries a visoff spec.

    `plain`: no loader was injected, so the real controller is built; a test's `builder` makes its own."""
    if not spec:  # None, or {} where the server already read a policy dir without a visoff.json
        return predict, None
    if builder is not None:
        predict = builder(policy_dir, spec, predict, n_steps, device)
    elif plain:
        predict = build_visoff_controller(policy_dir, spec, predict, n_steps, device)
    return predict, {
        "version": spec["version"],
        "weights_sha256": spec["weights_sha256"],
        "cam_mode": spec.get("cam_mode") if spec["version"] == "v8" else None,
        "lock_steps": list(spec["lock_steps"]),
    }
