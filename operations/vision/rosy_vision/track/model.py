"""Fixed tracking interface (D-457 3). Backends change; these types do not."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np

Status = Literal["OK", "LEARNING", "CALIBRATION_REQUIRED", "SCENE_CHANGED"]

#: Pinky Pro URDF NOMINAL (D-397, products/pinky_pro/profile/config/geometry.yaml; the drift
#: test is test_overhead_track_model.py). The silhouette seen from above is the top deck and
#: the LiDAR, the highest part listed, so the parallax height is the LiDAR height.
ROBOT_TOP_HEIGHT_M = 0.125
ROTATION_RADIUS_M = 0.08257
#: Floor-equivalent diameter window around 2 x rotation radius (0.165 m). Start values.
FOOTPRINT_MIN_M = 0.12
FOOTPRINT_MAX_M = 0.26
#: The first LEARNING_FRAMES frames and LEARNING_MIN_S seconds learn the empty track (3 fps).
LEARNING_FRAMES = 30
LEARNING_MIN_S = 10.0
#: More foreground than this share of the track area is a light or camera change.
SCENE_CHANGE_FRACTION = 0.30
MAX_DETECTIONS = 16


@dataclass(frozen=True, eq=False)
class Frame:
    image: np.ndarray   # BGR uint8 at the frame's own resolution
    captured_at: float  # Vision clock (D-261)


@dataclass(frozen=True)
class Calibration:
    source_id: str
    map_id: str
    revision: str
    image_to_map: tuple[float, ...]                    # 9, row-major: frame pixels -> map metres
    image_size: tuple[int, int]                        # (width, height) of the frames it is for
    track_bounds_m: tuple[float, float, float, float]  # min_x, min_y, max_x, max_y
    hfov_deg: float | None = None                      # lens FOV across the long side; None = no parallax

    def __post_init__(self) -> None:
        if len(self.image_to_map) != 9 or not all(math.isfinite(v) for v in self.image_to_map):
            raise ValueError("image_to_map must be nine finite numbers")
        matrix = np.asarray(self.image_to_map, dtype=float).reshape(3, 3)
        if abs(np.linalg.det(matrix)) < 1e-12 or np.linalg.cond(matrix) > 1e12:
            raise ValueError("image_to_map must be an invertible, well-conditioned homography")
        if (len(self.image_size) != 2 or min(self.image_size) <= 0
                or not all(isinstance(v, int) and not isinstance(v, bool) for v in self.image_size)):
            raise ValueError("calibration image size must be two positive integers")
        min_x, min_y, max_x, max_y = self.track_bounds_m
        if (not all(math.isfinite(v) for v in self.track_bounds_m)
                or min_x >= max_x or min_y >= max_y):
            raise ValueError("track bounds must be a finite non-empty rectangle")
        ids = (self.revision, self.source_id, self.map_id)
        if not all(isinstance(v, str) and v.strip() for v in ids):
            raise ValueError("source, map and calibration revision are required")
        if self.hfov_deg is not None and not (
                isinstance(self.hfov_deg, (int, float)) and 0.0 < self.hfov_deg < 180.0):
            raise ValueError("hfov_deg must be None or between 0 and 180 degrees")


@dataclass(frozen=True)
class Detection:
    x: float            # map m
    y: float            # map m
    footprint_m: float  # floor-projected equivalent diameter
    score: float        # 0..1
    marker_id: int | None = None  # configured ArUco identity, never a robot id


@dataclass(frozen=True)
class DetectorResult:
    detections: tuple[Detection, ...]
    status: Status


class RobotDetector(Protocol):
    processor_revision: str

    def detect(self, frame: Frame, calib: Calibration) -> DetectorResult: ...

    def reset(self) -> None: ...
