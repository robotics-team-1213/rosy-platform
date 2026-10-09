"""First tracking backend: frozen background and floor-sized blobs (D-457 3).

MOG2 learns the empty track while LEARNING (LEARNING_FRAMES frames and LEARNING_MIN_S
seconds), then runs with learning rate 0 so a parked robot stays foreground instead of
fading into the background. MOG2 shadows (127) are not foreground. Detection runs on a
copy whose long side is at most WORK_LONG_SIDE pixels; work pixels are mapped to the
calibration's own image size by pixel centres. Pixels whose floor point is outside the
calibrated track rectangle, or beyond the horizon, are cleared. Each connected component's
floor area is its pixel count times the homography's local pixel area; with a lens FOV the
camera position is solved from the homography and position and size are corrected for the
robot height. Only blobs whose floor-equivalent diameter is inside the footprint window are
kept; no heading is reported. More than SCENE_CHANGE_FRACTION of the track in the foreground
(light change, camera knocked) drops the frame as SCENE_CHANGED and learns again. A relearn
with robots on the track bakes them in: relearn on an empty track.

D-539: an operator relearn is the empty-track statement, so with a BackgroundStore the frames
of that learn are kept (track pixels plus STORE_MARGIN_PX; the rest is blacked out) under the calibration
revision. After a restart (site update, nightly reboot: robots are usually parked on the mat)
the first learn replays them instead of learning the parked robots. A different revision or
frame size learns live as before; a light change since then trips SCENE_CHANGED on the first
frame and learns live. Replay happens once per process, so that cannot loop.
"""

from __future__ import annotations

import collections
import json
import logging
import math
import os
from pathlib import Path

import cv2
import numpy as np

from rosy_vision.track import geometry
from rosy_vision.track.model import (
    FOOTPRINT_MAX_M, FOOTPRINT_MIN_M, LEARNING_FRAMES, LEARNING_MIN_S, MAX_DETECTIONS,
    ROBOT_TOP_HEIGHT_M, ROTATION_RADIUS_M, SCENE_CHANGE_FRACTION,
    Calibration, Detection, DetectorResult, Frame,
)

logger = logging.getLogger("rosy_vision.track")

PROCESSOR_REVISION = "background-blob/1"
#: Detection runs on a copy whose long side is at most this many pixels.
WORK_LONG_SIDE = 640
#: A frame whose width/height ratio differs from the calibration's by more than this is refused.
ASPECT_TOLERANCE = 0.01
#: MOG2 shadow ratio (OpenCV default; start value). A pixel between SHADOW_TAU and 1.0 times
#: the background brightness, with the same colour, is a shadow and dropped; darker is foreground.
SHADOW_TAU = 0.5
#: Closing joins a robot top split by a thin floor-coloured gap (deck vs LiDAR). Start value.
CLOSE_KERNEL_PX = 5
_FOREGROUND = 200  # MOG2 mask: 255 foreground, 127 shadow, 0 background
_OPEN_KERNEL = np.ones((3, 3), np.uint8)  # removes speckle
_CLOSE_KERNEL = np.ones((CLOSE_KERNEL_PX, CLOSE_KERNEL_PX), np.uint8)
_NOMINAL_M = 2.0 * ROTATION_RADIUS_M
#: JPEG quality of kept background frames (the live frames are phone JPEGs already).
STORE_JPEG_QUALITY = 95
#: Kept frames hold the track plus this margin, so JPEG blocks at the edge do not ring into it.
STORE_MARGIN_PX = 8


class BackgroundStore:
    """One file per source: the masked frames of the last operator relearn (D-539)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(self, revision: str, frames: list[np.ndarray]) -> None:
        encoded = {}
        for index, image in enumerate(frames):
            ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, STORE_JPEG_QUALITY])
            if not ok:
                raise ValueError("background frame did not encode")
            encoded[f"f{index:03d}"] = data.ravel()
        meta = json.dumps({"revision": revision, "shape": list(frames[0].shape),
                           "count": len(frames)}).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".new")
        try:
            with temporary.open("wb") as stream:
                np.savez(stream, meta=np.frombuffer(meta, np.uint8), **encoded)
                stream.flush()
                os.fsync(stream.fileno())  # a power cut must not leave an empty file in place
            os.replace(temporary, self.path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def load(self, revision: str, shape: tuple[int, ...]) -> list[np.ndarray] | None:
        """The kept frames for this revision and work size, else None (missing or unreadable)."""
        try:
            with np.load(self.path, allow_pickle=False) as data:
                meta = json.loads(bytes(data["meta"]).decode("utf-8"))
                if meta.get("revision") != revision or tuple(meta.get("shape") or ()) != tuple(shape):
                    return None
                frames = [cv2.imdecode(data[f"f{index:03d}"], cv2.IMREAD_COLOR)
                          for index in range(int(meta["count"]))]
        except Exception as exc:  # empty, truncated or foreign file: learn live (EOFError, BadZipFile, ...)
            if self.path.exists():
                logger.warning("kept background unreadable path=%s error=%s", self.path, type(exc).__name__)
            return None
        if not frames or any(image is None or image.shape != tuple(shape) for image in frames):
            return None
        return frames


class BackgroundBlobDetector:
    """One detector per camera source, called from a single thread (it holds MOG2 state).

    Known limit: robots that touch or nearly touch (a gap the closing step fills) merge into
    one blob whose floor-equivalent diameter is above the window (0.26 m), so neither is
    detected while they are that close.
    """

    processor_revision = PROCESSOR_REVISION

    def __init__(self, *, learning_frames: int = LEARNING_FRAMES,
                 learning_min_s: float = LEARNING_MIN_S,
                 scene_change_fraction: float = SCENE_CHANGE_FRACTION,
                 footprint_m: tuple[float, float] = (FOOTPRINT_MIN_M, FOOTPRINT_MAX_M),
                 robot_height_m: float = ROBOT_TOP_HEIGHT_M,
                 store: BackgroundStore | None = None) -> None:
        low, high = footprint_m
        if not 0.0 < low < high:
            raise ValueError("footprint window must be 0 < min < max")
        if learning_frames < 1 or learning_min_s < 0:
            raise ValueError("learning needs at least one frame and a non-negative duration")
        if not 0.0 < scene_change_fraction <= 1.0:
            raise ValueError("scene change fraction must be in (0, 1]")
        if not 0.0 <= robot_height_m < geometry.MIN_CAMERA_HEIGHT_M:
            raise ValueError("robot height must be non-negative and below the lowest camera")
        self._learning_frames = learning_frames
        self._learning_min_s = learning_min_s
        self._scene_change_fraction = scene_change_fraction
        self._footprint = (low, high)
        self._robot_height_m = robot_height_m
        self._shape: tuple[int, ...] | None = None
        self._view_key: tuple | None = None
        self._view: tuple = ()
        self._store = store
        self._restore_pending = store is not None  # D-539: once per process, at the first learn
        self.reset()

    def reset(self) -> None:
        """Learn the background again from the next frames (scene change, new frame size)."""
        self._model = cv2.createBackgroundSubtractorMOG2(
            history=self._learning_frames, varThreshold=16, detectShadows=True)
        self._model.setShadowThreshold(SHADOW_TAU)
        self._learned = 0
        self._first_at: float | None = None
        self._ready = False
        self._keep: list[np.ndarray] | None = None

    def relearn(self) -> None:
        """Operator relearn: the track is empty, so these frames are kept for restarts (D-539)."""
        self.reset()
        self._restore_pending = False
        if self._store is not None:
            self._keep = collections.deque(maxlen=self._learning_frames)

    def detect(self, frame: Frame, calib: Calibration) -> DetectorResult:
        image = _work_image(frame.image)
        work_height, work_width = image.shape[:2]
        calib_width, calib_height = calib.image_size
        if abs((work_width / work_height) / (calib_width / calib_height) - 1.0) > ASPECT_TOLERANCE:
            return DetectorResult((), "CALIBRATION_REQUIRED")
        work_to_map, mask, track_px, camera = self._view_for(calib, (work_height, work_width))
        if track_px == 0:
            return DetectorResult((), "CALIBRATION_REQUIRED")  # track out of view or beyond the horizon
        if image.shape != self._shape:
            keep = self._keep
            self.reset()
            if keep is not None:  # an operator relearn restarts, still kept
                self._keep = collections.deque(maxlen=self._learning_frames)
            self._shape = image.shape
        if self._restore_pending and not self._ready and self._learned == 0:
            self._restore_pending = False
            kept = self._store.load(calib.revision, image.shape)
            if kept is not None:
                for background in kept:
                    self._model.apply(background, learningRate=-1)
                self._ready = True
        if not self._ready:
            self._model.apply(image, learningRate=-1)
            if self._keep is not None:
                self._keep.append(cv2.bitwise_and(image, image, mask=self._keep_mask(mask)))
            if self._first_at is None or frame.captured_at < self._first_at:
                self._first_at = frame.captured_at  # first frame, or the clock stepped back
            self._learned += 1
            if (self._learned >= self._learning_frames
                    and frame.captured_at - self._first_at >= self._learning_min_s):
                self._ready = True
                if self._keep:
                    keep, self._keep = list(self._keep), None
                    try:
                        self._store.save(calib.revision, keep)
                    except Exception as exc:  # tracking goes on; the next restart learns live
                        logger.warning("background not kept path=%s error=%s", self._store.path, type(exc).__name__)
            return DetectorResult((), "LEARNING")
        raw = self._model.apply(image, learningRate=0)
        foreground = np.where(raw >= _FOREGROUND, 255, 0).astype(np.uint8)
        foreground = cv2.morphologyEx(cv2.bitwise_and(foreground, mask), cv2.MORPH_OPEN, _OPEN_KERNEL)
        foreground = cv2.bitwise_and(cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, _CLOSE_KERNEL), mask)
        if np.count_nonzero(foreground) > self._scene_change_fraction * track_px:
            self.reset()
            return DetectorResult((), "SCENE_CHANGED")
        shrink = 1.0 if camera is None else (camera[2] - self._robot_height_m) / camera[2]
        found: list[Detection] = []
        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(foreground, connectivity=8)
        for label in range(1, count):
            pixels = int(stats[label, cv2.CC_STAT_AREA])
            u, v = float(centroids[label][0]), float(centroids[label][1])
            points = geometry.apply(work_to_map, [[u, v], [u + 1.0, v], [u, v + 1.0]])
            if not np.all(np.isfinite(points)):
                continue  # on or beyond the horizon
            (ax, ay), (bx, by) = points[1] - points[0], points[2] - points[0]
            area_m2 = pixels * abs(float(ax * by - ay * bx))
            diameter = 2.0 * math.sqrt(area_m2 / math.pi) * shrink
            if not self._footprint[0] <= diameter <= self._footprint[1]:
                continue
            x, y = float(points[0][0]), float(points[0][1])
            if camera is not None:
                x, y = geometry.parallax_correct((x, y), camera, self._robot_height_m)
            found.append(Detection(x=float(x), y=float(y), footprint_m=diameter,
                                   score=self._score(diameter)))
        found.sort(key=lambda item: item.score, reverse=True)
        return DetectorResult(tuple(found[:MAX_DETECTIONS]), "OK")

    def _keep_mask(self, mask: np.ndarray) -> np.ndarray:
        if getattr(self, "_keep_mask_for", None) is not mask:
            size = 2 * STORE_MARGIN_PX + 1
            self._keep_mask_for = mask
            self._keep_mask_px = cv2.dilate(mask, np.ones((size, size), np.uint8))
        return self._keep_mask_px

    def _score(self, diameter: float) -> float:
        """1 at the nominal diameter, falling linearly to 0 at each window edge."""
        low, high = self._footprint
        if diameter < _NOMINAL_M:  # then low <= diameter < nominal, so the divisor is positive
            return max(0.0, 1.0 - (_NOMINAL_M - diameter) / (_NOMINAL_M - low))
        if high <= _NOMINAL_M:
            return 1.0
        return max(0.0, 1.0 - (diameter - _NOMINAL_M) / (high - _NOMINAL_M))

    def _view_for(self, calib: Calibration, shape: tuple[int, int]) -> tuple:
        """Work-to-map homography, track mask (255 inside), its pixel count and camera (cached)."""
        key = (calib.image_to_map, calib.image_size, calib.track_bounds_m, calib.hfov_deg, shape)
        if key != self._view_key:
            height, width = shape
            work_to_map = geometry.as_matrix(calib.image_to_map) @ geometry.centre_scale(
                calib.image_size[0] / width, calib.image_size[1] / height)
            vs, us = np.mgrid[0:height, 0:width]
            floor = geometry.apply(work_to_map, np.c_[us.ravel(), vs.ravel()])
            min_x, min_y, max_x, max_y = calib.track_bounds_m
            with np.errstate(invalid="ignore"):
                inside = ((floor[:, 0] >= min_x) & (floor[:, 0] <= max_x)
                          & (floor[:, 1] >= min_y) & (floor[:, 1] <= max_y))
            mask = np.where(inside, 255, 0).astype(np.uint8).reshape(height, width)
            camera = geometry.camera_from_homography(calib.image_to_map, calib.image_size, calib.hfov_deg)
            if camera is not None and camera[2] <= self._robot_height_m:
                camera = None
            self._view = (work_to_map, mask, int(np.count_nonzero(mask)), camera)
            self._view_key = key
        return self._view


def _work_image(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    long_side = max(width, height)
    if long_side <= WORK_LONG_SIDE:
        return image
    factor = WORK_LONG_SIDE / long_side
    size = (max(1, round(width * factor)), max(1, round(height * factor)))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)
