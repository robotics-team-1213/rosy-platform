#!/usr/bin/env python3
"""Domain Randomization Engine for Sim-to-Real SmolVLA & ACT Training (2026-11-11).
Synthesizes visual and physical robustness for 1/2/3-Tier Stacking on OMX robotic cells,
aligned with Unified AreaXYZ (D-1014, TIER_Z_M = {1: 0.0074, 2: 0.0398, 3: 0.0674})
and LeRobot 0.4.4 native action space (D-854 lerobot_norm_v1).

Features:
  1. Lighting Randomization: 200~800 lux simulation with gamma & contrast jitter.
  2. Real Cell Visual Hazards (Trial 11): Blue-violet overhead LED specular highlight,
     cyan pallet corners, and narrow 6mm inter-column shadow seams.
  3. Spatial Pose Perturbation: Tier-aware XY/Z/Yaw perturbation around TIER_Z_M stud targets.
  4. View Dropout & Proprioceptive Noise: Simulates Wrist camera self-occlusion at Tier 2 & Tier 3
     and injects bounded D-854 `lerobot_norm_v1` joint observation jitter.
"""
from __future__ import annotations

from dataclasses import dataclass
import random
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER = _ROOT / "middleware" / "devices" / "omx" / "adapter"
if str(_ADAPTER) not in sys.path:
    sys.path.insert(0, str(_ADAPTER))

try:
    from omx_adapter.area_xyz import AREA_RANGES_M, TIER_Z_M
except ImportError:
    TIER_Z_M = {1: 0.0074, 2: 0.0398, 3: 0.0674}
    AREA_RANGES_M = {
        "pallet": (0.095, 0.245, -0.145, 0.060, 0.005, 0.115),
    }


@dataclass
class RandomizationProfile:
    # Lighting & Color
    brightness_range: tuple[float, float] = (0.7, 1.3)
    contrast_range: tuple[float, float] = (0.8, 1.2)
    hue_jitter_deg: float = 15.0
    gamma_range: tuple[float, float] = (0.8, 1.25)

    # Sensor Occlusion, Cell Hazards & Noise
    sensor_dropout_prob: float = 0.15
    cell_hazard_prob: float = 0.50
    gaussian_noise_sigma: float = 0.02
    joint_state_noise_units: float = 0.25

    # Spatial Pose Jitter (mm / deg)
    pos_jitter_xy_mm: float = 15.0
    pos_jitter_z_mm: float = 2.0
    yaw_jitter_deg: float = 8.0


class VlaDomainRandomizer:
    """Applies domain randomization to training batches for Sim-to-Real transfer."""

    def __init__(self, profile: Optional[RandomizationProfile] = None):
        self.p = profile or RandomizationProfile()

    def inject_cell_visual_hazards(self, img_array: np.ndarray) -> np.ndarray:
        """Synthesizes real OMX cell visual hazards (Trial 11):
        - Cool LED top-face reflection band
        - Cyan pallet corner distractors
        - Dark 6mm inter-column shadow seam
        """
        out = img_array.copy()
        if out.ndim != 3:
            return out
        chw = out.shape[0] == 3
        h, w = (out.shape[1], out.shape[2]) if chw else (out.shape[0], out.shape[1])
        if h < 16 or w < 16:
            return out

        # 1. Cool LED specular reflection band near center
        ry0, ry1 = int(h * 0.32), int(h * 0.68)
        rx0, rx1 = int(w * 0.44), int(w * 0.56)
        # 2. Cyan corner patches at bottom corners
        cy0, cx_w = int(h * 0.75), max(2, int(w * 0.08))
        # 3. Inter-column dark seam at right edge of box
        sx0, sx1 = int(w * 0.68), min(w, int(w * 0.72))

        is_uint8 = out.dtype == np.uint8
        scale = 255.0 if is_uint8 else 1.0
        work = out.astype(np.float32) if is_uint8 else out.copy()

        if chw:
            work[:, ry0:ry1, rx0:rx1] = np.clip(work[:, ry0:ry1, rx0:rx1] * 0.7 + 0.25 * scale, 0.0, scale)
            work[0, cy0:, :cx_w] = 0.65 * scale
            work[1, cy0:, :cx_w] = 0.88 * scale
            work[2, cy0:, :cx_w] = 0.92 * scale
            work[:, ry0:ry1, sx0:sx1] = work[:, ry0:ry1, sx0:sx1] * 0.25
        else:
            work[ry0:ry1, rx0:rx1, :] = np.clip(work[ry0:ry1, rx0:rx1, :] * 0.7 + 0.25 * scale, 0.0, scale)
            work[cy0:, :cx_w, 0] = 0.65 * scale
            work[cy0:, :cx_w, 1] = 0.88 * scale
            work[cy0:, :cx_w, 2] = 0.92 * scale
            work[ry0:ry1, sx0:sx1, :] = work[ry0:ry1, sx0:sx1, :] * 0.25
        return np.clip(work, 0.0, 255.0).astype(np.uint8) if is_uint8 else work

    def augment_image_tensor(
        self,
        img_array: np.ndarray,
        is_wrist_cam: bool = False,
        tier: int = 3,
        inject_hazards: Optional[bool] = None,
    ) -> np.ndarray:
        """Applies photometric noise, contrast, gamma, cell hazards, and optional occlusion dropout."""
        out = img_array.copy()
        dropout_p = self.p.sensor_dropout_prob * (1.25 if int(tier) >= 3 else 1.0)

        do_hazards = inject_hazards if inject_hazards is not None else (random.random() < self.p.cell_hazard_prob)
        if is_wrist_cam and do_hazards:
            out = self.inject_cell_visual_hazards(out)

        # 1. Wrist Camera Occlusion Dropout (Tier 2/3 lower-jaw occlusion simulation)
        if is_wrist_cam and random.random() < dropout_p:
            if out.ndim == 3 and out.shape[0] == 3:  # (C, H, W)
                _, h, _ = out.shape
                out[:, h // 2 :, :] = out[:, h // 2 :, :] * 0.1
            elif out.ndim == 3 and out.shape[2] == 3:  # (H, W, C)
                h, _, _ = out.shape
                out[h // 2 :, :, :] = out[h // 2 :, :, :] * 0.1

        # 2. Brightness & Contrast Jitter
        brightness = random.uniform(*self.p.brightness_range)
        contrast = random.uniform(*self.p.contrast_range)
        out = (out - 0.5) * contrast + 0.5 + (brightness - 1.0)

        # 3. Gamma Correction (Lighting non-linearities)
        gamma = random.uniform(*self.p.gamma_range)
        out = np.clip(out, 1e-4, 1.0) ** (1.0 / gamma)

        # 4. Sensor Gaussian Noise
        noise = np.random.normal(0, self.p.gaussian_noise_sigma, out.shape).astype(out.dtype)
        out = np.clip(out + noise, 0.0, 1.0)

        return out

    def augment_state_vector(self, state: list[float] | np.ndarray) -> list[float]:
        """Injects bounded proprioceptive noise into 6-DOF D-854 `lerobot_norm_v1` joint states."""
        arr = [float(x) for x in state]
        out: list[float] = []
        for idx, val in enumerate(arr):
            jitter = random.gauss(0.0, self.p.joint_state_noise_units)
            lo, hi = (0.0, 100.0) if idx == 5 else (-100.0, 100.0)
            out.append(round(min(max(val + jitter, lo), hi), 4))
        return out

    def augment_pose(
        self,
        x_m: float,
        y_m: float,
        z_m: Optional[float] = None,
        yaw_deg: float = -90.0,
        *,
        tier: int = 1,
        area: str = "pallet",
    ) -> tuple[float, float, float, float]:
        """Perturbs target container pose around Unified AreaXYZ (D-1014) tier coordinates."""
        base_z = float(z_m) if z_m is not None else float(TIER_Z_M.get(int(tier), TIER_Z_M[1]))
        dx = random.uniform(-self.p.pos_jitter_xy_mm, self.p.pos_jitter_xy_mm) / 1000.0
        dy = random.uniform(-self.p.pos_jitter_xy_mm, self.p.pos_jitter_xy_mm) / 1000.0
        dz = random.uniform(-self.p.pos_jitter_z_mm, self.p.pos_jitter_z_mm) / 1000.0
        dyaw = random.uniform(-self.p.yaw_jitter_deg, self.p.yaw_jitter_deg)

        nx, ny, nz = x_m + dx, y_m + dy, base_z + dz
        if area in AREA_RANGES_M:
            xmin, xmax, ymin, ymax, zmin, zmax = AREA_RANGES_M[area]
            nx = min(max(nx, xmin), xmax)
            ny = min(max(ny, ymin), ymax)
            nz = min(max(nz, zmin), zmax)

        return (
            round(nx, 4),
            round(ny, 4),
            round(nz, 4),
            round(yaw_deg + dyaw, 2),
        )

    def process_batch(self, batch: Dict[str, Any], *, tier: int = 3) -> Dict[str, Any]:
        """Processes a LeRobot 0.4.4 batch dictionary."""
        augmented = dict(batch)
        for key in list(augmented.keys()):
            if "observation.images" in key and isinstance(augmented[key], np.ndarray):
                is_wrist = "wrist" in key or "camera2" in key
                augmented[key] = self.augment_image_tensor(augmented[key], is_wrist_cam=is_wrist, tier=tier)
            elif key == "observation.state" and isinstance(augmented[key], (list, np.ndarray)):
                augmented[key] = self.augment_state_vector(augmented[key])
        return augmented
