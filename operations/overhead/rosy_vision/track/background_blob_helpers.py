"""Persistence store and baked-suspect/ghost healing helpers for ``background_blob.py``."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import cv2
import numpy as np

from rosy_vision.track import body_split
from rosy_vision.track.model import ROTATION_RADIUS_M, Detection

logger = logging.getLogger("rosy_vision.track")

#: Detection runs on a copy whose long side is at most this many pixels.
WORK_LONG_SIDE = 640
#: Closing joins a robot top split by a thin floor-coloured gap (deck vs LiDAR). Start value.
CLOSE_KERNEL_PX = 5
_OPEN_KERNEL = np.ones((3, 3), np.uint8)  # removes speckle
_CLOSE_KERNEL = np.ones((CLOSE_KERNEL_PX, CLOSE_KERNEL_PX), np.uint8)
_NOMINAL_M = 2.0 * ROTATION_RADIUS_M
#: JPEG quality of kept background frames (the live frames are phone JPEGs already).
STORE_JPEG_QUALITY = 95
#: Kept frames hold the track plus this margin, so JPEG blocks at the edge do not ring into it.
STORE_MARGIN_PX = 8
#: D-547 baked suspects (start values). A background pixel is dark below this share of the
#: track's median brightness (max of B, G, R).
BAKED_DARK_RATIO = 0.6
#: Pixel count over convex hull pixel area; a sign base with its pole or a bent strip is lower.
BAKED_MIN_SOLIDITY = 0.8
#: Long over short side of the minimum-area rectangle; a strip of tape is longer.
BAKED_MAX_ASPECT = 2.0
#: Guesses are reported at most at this score (Fleet matches by distance, not by score).
BAKED_SCORE_MAX = 0.35
#: The spot still shows the background while less than this share of the blob is foreground.
BAKED_MATCH_MAX_FOREGROUND = 0.3
#: A ghost: at least this share of the blob has the floor colour in the live frame ...
GHOST_FLOOR_FRACTION = 0.9
#: ... within this BGR distance of a learned floor colour: the track median, or one of the
#: GHOST_RING_COLOURS commonest colours (16-level bins) in the ring just outside the suspect, so
#: lane paint beside a parked robot counts as floor ...
GHOST_COLOUR_TOL = 40.0
GHOST_RING_COLOURS = 32
#: ... on this many frames in a row (about 1 s at 3 fps), so a passing occluder is not healed.
GHOST_CONFIRM_FRAMES = 3
#: The ghost zone (not reported, relearned) is the blob dilated by this many pixels.
GHOST_MARGIN_PX = 4
#: Addendum: a ghost without a suspect is a blob between these factors of the footprint window ...
GHOST_SIZE_SLACK = (0.5, 1.5)
#: ... whose learned background is dark (below the suspect dark level) on at least this share ...
GHOST_BG_DARK_MIN = 0.5
#: ... found again within this many work pixels on the next frame to keep its streak.
GHOST_TRACK_PX = 8
_GHOST_GROW = np.ones((2 * GHOST_MARGIN_PX + 1,) * 2, np.uint8)  # blob -> ghost zone
_RING_GROW = np.ones((6 * GHOST_MARGIN_PX + 1,) * 2, np.uint8)   # blob -> outer edge of the ring


class BackgroundStore:
    """One file per source: the masked frames of the last operator relearn (D-539)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(self, revision: str, frames: list[np.ndarray], unknown: np.ndarray | None = None,
             camera: str | None = None) -> None:
        encoded = {} if unknown is None else {"unknown": np.packbits(unknown)}  # D-600
        for index, image in enumerate(frames):
            ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, STORE_JPEG_QUALITY])
            if not ok:
                raise ValueError("background frame did not encode")
            encoded[f"f{index:03d}"] = data.ravel()
        meta = {"revision": revision, "shape": list(frames[0].shape), "count": len(frames)}
        if camera is not None:
            meta["camera"] = camera
        meta = json.dumps(meta).encode("utf-8")
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

    def load(self, revision: str, shape: tuple[int, ...],
             camera: str | None = None) -> list[np.ndarray] | None:
        """The kept frames for this revision, work size and camera settings, else None."""
        try:
            with np.load(self.path, allow_pickle=False) as data:
                meta = json.loads(bytes(data["meta"]).decode("utf-8"))
                if (meta.get("revision") != revision or tuple(meta.get("shape") or ()) != tuple(shape)
                        or meta.get("camera") != camera):
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

    def load_unknown(self, shape: tuple[int, ...]) -> np.ndarray | None:
        """D-600: the kept unknown-floor mask, read right after a successful ``load``."""
        try:
            with np.load(self.path, allow_pickle=False) as data:
                if "unknown" not in data:
                    return None
                bits = np.unpackbits(data["unknown"])[:shape[0] * shape[1]]
        except Exception:
            return None
        return bits.reshape(shape[:2]).astype(bool) if bits.size == shape[0] * shape[1] else None


def _learn_background(self, mask: np.ndarray) -> None:
    """At ready and after a heal: the learned background image, its dark level and map, and
    its floor (track) colour."""
    background = self._model.getBackgroundImage()
    if background is None or background.ndim != 3:
        self._background = None
        return
    bright = background.max(axis=2)
    self._dark_level = BAKED_DARK_RATIO * float(np.median(bright[mask > 0]))
    self._bg_dark = bright < self._dark_level
    floor = (mask > 0) & ~self._bg_dark
    self._track_colour = np.median(background[floor], axis=0) if floor.any() else np.zeros(3)
    self._background = background


def _find_baked(self, mask: np.ndarray, work_to_map, camera) -> None:
    """D-547: robot-sized dark compact blobs in the learned background become suspects."""
    self._suspects = []
    background = self._background
    if background is not None:
        bright = background.max(axis=2)
        dark = np.where((bright < self._dark_level) & (mask > 0), 255, 0).astype(np.uint8)
        dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, _OPEN_KERNEL)
        dark = cv2.bitwise_and(cv2.morphologyEx(dark, cv2.MORPH_CLOSE, _CLOSE_KERNEL), mask)
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(dark, connectivity=8)
        count, labels, stats, centroids = body_split.split_rejected(  # robots parked side by side
            count, labels, stats, centroids, lambda *row: self._baked_shape_ok(*row, work_to_map, camera))
        height, width = dark.shape
        floor = (mask > 0) & (dark == 0)
        for label in range(1, count):
            if not self._baked_shape_ok(labels, stats, centroids, label, work_to_map, camera):
                continue
            left, top, w, h = (int(stats[label, i]) for i in range(4))
            detection = self._measure(int(stats[label, cv2.CC_STAT_AREA]), centroids[label], work_to_map, camera)
            pad = 3 * GHOST_MARGIN_PX  # room for the ring
            y0, x0 = max(0, top - pad), max(0, left - pad)
            y1, x1 = min(height, top + h + pad), min(width, left + w + pad)
            blob = labels[y0:y1, x0:x1] == label
            zone = cv2.dilate(blob.astype(np.uint8), _GHOST_GROW) > 0
            ring = (cv2.dilate(blob.astype(np.uint8), _RING_GROW) > 0) & ~zone & floor[y0:y1, x0:x1]
            refs = self._floor_refs(background[y0:y1, x0:x1], ring)
            # The dark core is smaller than the robot: report the nominal footprint.
            guess = Detection(detection.x, detection.y, _NOMINAL_M, min(detection.score, BAKED_SCORE_MAX))
            self._suspects.append([(y0, y1, x0, x1), blob, zone, guess, refs, 0])
        if self._suspects:
            logger.info("baked robot suspects count=%d", len(self._suspects))


def _baked_shape_ok(self, labels, stats, centroids, label, work_to_map, camera) -> bool:  # D-547 tests
    pixels = int(stats[label, cv2.CC_STAT_AREA])
    return (pixels > 0 and self._measure(pixels, centroids[label], work_to_map, camera) is not None
            and body_split.compact(labels, stats, label, BAKED_MAX_ASPECT, BAKED_MIN_SOLIDITY))


def _floor_refs(self, background: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """Floor colours: the track median and the ring's commonest background colours."""
    bins, counts = np.unique(background[ring] // 16, axis=0, return_counts=True)
    common = bins[np.argsort(counts)[::-1][:GHOST_RING_COLOURS]] * 16 + 8
    return np.vstack([self._track_colour, common]).astype(np.float32)


def _unsuspected_ghost(self, label, labels, stat, centroid, image, mask, work_to_map, camera):
    """(box, heal mask, (x, y, footprint)) when this foreground blob is a ghost no suspect
    covers, else None."""
    if self._background is None:
        return None
    left, top, w, h, total = (int(stat[i]) for i in range(5))
    blob = labels[top:top + h, left:left + w] == label
    if np.count_nonzero(self._bg_dark[top:top + h, left:left + w][blob]) < GHOST_BG_DARK_MIN * total:
        return None  # the background there was not dark: floor, paint, tape or a blue square
    low, high = self._footprint
    window = (GHOST_SIZE_SLACK[0] * low, GHOST_SIZE_SLACK[1] * high)
    measured = self._measure(total, centroid, work_to_map, camera, window)
    if measured is None:
        return None
    pad, (height, width) = 3 * GHOST_MARGIN_PX, labels.shape
    y0, x0 = max(0, top - pad), max(0, left - pad)
    y1, x1 = min(height, top + h + pad), min(width, left + w + pad)
    blob = (labels[y0:y1, x0:x1] == label).astype(np.uint8)
    zone = cv2.dilate(blob, _GHOST_GROW) > 0
    background = self._background[y0:y1, x0:x1]
    ring = ((cv2.dilate(blob, _RING_GROW) > 0) & ~zone & (mask[y0:y1, x0:x1] > 0)
            & ~self._bg_dark[y0:y1, x0:x1])
    live = _floor_like(image[y0:y1, x0:x1], self._floor_refs(background, ring))
    if np.count_nonzero(live[blob > 0]) < GHOST_FLOOR_FRACTION * total:
        return None  # a robot or an occluder is there now
    return (y0, y1, x0, x1), zone & live, (measured.x, measured.y, measured.footprint_m)


def _check_suspects(self, image: np.ndarray, foreground: np.ndarray, held: bool = False) -> tuple[list, list]:
    """Guesses for suspects whose spot still shows the background, and (suspect, confirmed)
    ghosts; confirmed ghosts leave the suspect list and are healed by the caller. ``held``
    (D-596 1): nothing is confirmed, and a spot that is not floor coloured stays a guess
    (its blobs are skipped like a ghost's, so the lamp's own blob is not a second robot)."""
    guesses, kept, ghosts = [], [], []
    for suspect in self._suspects:
        (y0, y1, x0, x1), blob, _zone, guess, refs, streak = suspect
        total = int(np.count_nonzero(blob))
        if np.count_nonzero(foreground[y0:y1, x0:x1][blob]) < BAKED_MATCH_MAX_FOREGROUND * total:
            suspect[5] = 0
            guesses.append(guess)
            kept.append(suspect)
            continue
        floor = _floor_like(image[y0:y1, x0:x1], refs)
        if np.count_nonzero(floor[blob]) >= GHOST_FLOOR_FRACTION * total:
            suspect[5] = streak + 1
            confirmed = suspect[5] >= GHOST_CONFIRM_FRAMES and not held
            ghosts.append((suspect, confirmed))
            if confirmed:
                continue
        elif held:
            guesses.append(guess)
            ghosts.append((suspect, False))
        else:
            suspect[5] = 0  # something not floor is there now: the live path decides
        kept.append(suspect)
    self._suspects = kept
    return guesses, ghosts


def _heal(self, image: np.ndarray, heals: list) -> None:
    """Relearn MOG2 from the learning frames with live floor pixels in each ghost zone."""
    for (y0, y1, x0, x1), where in heals:
        stack = np.stack([frame[y0:y1, x0:x1] for frame in self._frames]).astype(np.float32)
        noisy = np.clip(image[y0:y1, x0:x1] + (stack - stack.mean(axis=0)), 0, 255).astype(np.uint8)
        for frame, patch in zip(self._frames, noisy):
            frame[y0:y1, x0:x1][where] = patch[where]
    self._rebuild()
    healed = np.zeros(self._frames[0].shape[:2], bool)
    for (y0, y1, x0, x1), where in heals:
        healed[y0:y1, x0:x1] |= where
    # A suspect whose zone was healed by an unsuspected ghost is gone too.
    self._suspects = [suspect for suspect in self._suspects
                      if not healed[suspect[0][0]:suspect[0][1], suspect[0][2]:suspect[0][3]][suspect[2]].all()]


def _floor_like(image: np.ndarray, refs: np.ndarray) -> np.ndarray:
    """Pixels within GHOST_COLOUR_TOL (BGR distance) of any reference floor colour."""
    distance = np.linalg.norm(image[:, :, None, :].astype(np.float32) - refs, axis=3)
    return distance.min(axis=2) <= GHOST_COLOUR_TOL


def _work_image(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    long_side = max(width, height)
    if long_side <= WORK_LONG_SIDE:
        return image
    factor = WORK_LONG_SIDE / long_side
    size = (max(1, round(width * factor)), max(1, round(height * factor)))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)
