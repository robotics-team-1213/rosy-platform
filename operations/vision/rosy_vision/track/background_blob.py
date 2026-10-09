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

D-547: when the background was learned with robots parked (no kept background), the learned
background image is searched once, when the model becomes ready, for robot-sized dark compact
blobs in the track (darkness is the max of B, G, R against the track median, so blue tape is
not dark; the footprint window and a solidity/aspect test reject sign bases with poles and
tape). Each is a baked suspect. Per frame only the suspects' patches are checked: while the
live patch still shows the background the suspect is reported as a guess (score at most
BAKED_SCORE_MAX, footprint the nominal 2 x rotation radius: the blob is only the dark core).
When the patch is foreground and its live pixels have the learned floor colour (the ring just
outside the suspect or the track median) for GHOST_CONFIRM_FRAMES frames in a row, the robot
left and the spot is a ghost. A one-frame occluder (hand, paper) does not count. Ghost blobs
are never reported; on confirmation the learning frames get live floor pixels in the ghost
zone and in every foreground blob touching it (keeping each frame's own noise), MOG2 is
relearned from them and the suspect is dropped.

D-547 addendum: the suspect search can miss a parked robot (a cable across it, a neighbour
touching it), so ghosts are also found without a suspect. Any foreground blob of roughly robot
size (GHOST_SIZE_SLACK around the footprint window) whose live pixels have the floor colour
while the learned background at the same pixels is mostly dark (robots are dark; blue squares,
tape stripes and lighter patches are not) is a ghost candidate. Until it has been seen for
GHOST_CONFIRM_FRAMES frames in a row near the place it first appeared it is still reported,
with the score capped at BAKED_SCORE_MAX, so a wrong call is visible; then it is healed like a
suspect ghost and logged with its map position. A dark robot or an occluder such as a chair is
not floor coloured live, so it is never healed. The learning frames are kept for the whole process so
any ghost can be healed: at most LEARNING_FRAMES frames at WORK_LONG_SIDE.

D-596 1: ``hold(until)`` freezes the background for an LED identify window (frames captured up to
``until``), so a standing, blinking robot is never learned or healed away: no learning frame is
taken (a learn waits), a scene change drops the frame without starting a learn, no ghost is
confirmed or healed, and a baked suspect whose spot turned foreground but not floor coloured (its
lamp is blinking) is still reported as its guess. After the window everything runs as before.
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
        self._hold_until = -math.inf  # D-596 1: capture time up to which the background is frozen
        self.reset()

    def reset(self) -> None:
        """Learn the background again from the next frames (scene change, new frame size)."""
        self._model = self._new_model()
        self._learned = 0
        self._first_at: float | None = None
        self._ready = False
        self._save = False  # D-539: this learn is an operator relearn to keep
        self._frames: collections.deque | None = collections.deque(maxlen=self._learning_frames)
        self._suspects: list[list] = []  # D-547: [box, blob, zone, guess, floor colours, ghost streak]
        self._pending: list[list] = []  # D-547 addendum: unsuspected ghosts [u0, v0, streak]
        self._background: np.ndarray | None = None  # the learned background image, while ready

    def _new_model(self):
        model = cv2.createBackgroundSubtractorMOG2(
            history=self._learning_frames, varThreshold=16, detectShadows=True)
        model.setShadowThreshold(SHADOW_TAU)
        return model

    def hold(self, until: float) -> None:
        """D-596 1: freeze learning and healing for frames captured up to ``until``."""
        self._hold_until = max(self._hold_until, until)

    def relearn(self) -> None:
        """Operator relearn: the track is empty, so these frames are kept for restarts (D-539)."""
        self.reset()
        self._restore_pending = False
        self._save = self._store is not None

    def detect(self, frame: Frame, calib: Calibration) -> DetectorResult:
        image = _work_image(frame.image)
        work_height, work_width = image.shape[:2]
        calib_width, calib_height = calib.image_size
        if abs((work_width / work_height) / (calib_width / calib_height) - 1.0) > ASPECT_TOLERANCE:
            self._pending = []
            return DetectorResult((), "CALIBRATION_REQUIRED")
        work_to_map, mask, track_px, camera = self._view_for(calib, (work_height, work_width))
        if track_px == 0:
            self._pending = []
            return DetectorResult((), "CALIBRATION_REQUIRED")  # track out of view or beyond the horizon
        if image.shape != self._shape:
            save = self._save
            self.reset()
            self._save = save  # an operator relearn restarts, still kept
            self._shape = image.shape
        if self._restore_pending and not self._ready and self._learned == 0:
            self._restore_pending = False
            kept = self._store.load(calib.revision, image.shape)
            if kept is not None:
                for background in kept:
                    self._model.apply(background, learningRate=-1)
                self._frames.extend(kept)
                self._ready = True
                self._learn_background(mask)
                self._find_baked(mask, work_to_map, camera)
        held = frame.captured_at <= self._hold_until
        if not self._ready and held:
            return DetectorResult((), "LEARNING")  # D-596 1: a blinking robot must not be learned
        if not self._ready:
            self._model.apply(image, learningRate=-1)
            self._frames.append(cv2.bitwise_and(image, image, mask=self._keep_mask(mask)))
            if self._first_at is None or frame.captured_at < self._first_at:
                self._first_at = frame.captured_at  # first frame, or the clock stepped back
            self._learned += 1
            if (self._learned >= self._learning_frames
                    and frame.captured_at - self._first_at >= self._learning_min_s):
                self._ready = True
                if self._save:
                    self._save = False
                    try:
                        self._store.save(calib.revision, list(self._frames))
                    except Exception as exc:  # tracking goes on; the next restart learns live
                        logger.warning("background not kept path=%s error=%s", self._store.path, type(exc).__name__)
                self._learn_background(mask)
                self._find_baked(mask, work_to_map, camera)
            return DetectorResult((), "LEARNING")
        raw = self._model.apply(image, learningRate=0)
        foreground = np.where(raw >= _FOREGROUND, 255, 0).astype(np.uint8)
        foreground = cv2.morphologyEx(cv2.bitwise_and(foreground, mask), cv2.MORPH_OPEN, _OPEN_KERNEL)
        foreground = cv2.bitwise_and(cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, _CLOSE_KERNEL), mask)
        if np.count_nonzero(foreground) > self._scene_change_fraction * track_px:
            if not held:
                self.reset()
            return DetectorResult((), "SCENE_CHANGED")
        found, ghosts = self._check_suspects(image, foreground, held) if self._suspects else ([], [])
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(foreground, connectivity=8)
        # A ghost's foreground can reach past its zone (MOG2 edge, closing): drop whole blobs.
        skip, heals = set(), []
        for suspect, confirmed in ghosts:
            (y0, y1, x0, x1), _blob, zone, _guess, refs, _streak = suspect
            touching = set(np.unique(labels[y0:y1, x0:x1][zone]).tolist()) - {0}
            skip |= touching
            if confirmed:  # heal the zone and the whole ghost blob, where it has the floor colour
                where = np.isin(labels, list(touching))
                where[y0:y1, x0:x1] |= zone
                rows, cols = np.nonzero(where)
                box = (int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1)
                part = where[box[0]:box[1], box[2]:box[3]]
                heals.append((box, part & _floor_like(image[box[0]:box[1], box[2]:box[3]], refs)))
                logger.info("ghost healed suspect x=%.2f y=%.2f", _guess.x, _guess.y)
        pending = []
        for label in range(1, count):
            if label in skip:
                continue
            pixels = int(stats[label, cv2.CC_STAT_AREA])
            detection = self._measure(pixels, centroids[label], work_to_map, camera)
            ghost = self._unsuspected_ghost(label, labels, stats[label], centroids[label], image, mask,
                                            work_to_map, camera)
            if ghost is not None:
                u, v = centroids[label]
                start = next((old for old in self._pending
                              if abs(old[0] - u) <= GHOST_TRACK_PX and abs(old[1] - v) <= GHOST_TRACK_PX), None)
                u0, v0, streak = (u, v, 1) if start is None else (start[0], start[1], start[2] + 1)
                if streak >= GHOST_CONFIRM_FRAMES and not held:
                    heals.append(ghost[:2])
                    logger.info("ghost healed x=%.2f y=%.2f footprint_m=%.3f", *ghost[2])
                    continue
                pending.append([float(u0), float(v0), streak])
                if detection is not None:  # unconfirmed: visible, at a guess's score
                    detection = Detection(detection.x, detection.y, detection.footprint_m,
                                          min(detection.score, BAKED_SCORE_MAX))
            if detection is not None:
                found.append(detection)
        self._pending = pending
        if heals:
            self._heal(image, heals)
            self._learn_background(mask)
        found.sort(key=lambda item: item.score, reverse=True)
        return DetectorResult(tuple(found[:MAX_DETECTIONS]), "OK")

    def _measure(self, pixels: int, centroid, work_to_map, camera, window=None) -> Detection | None:
        """A blob of ``pixels`` work pixels at ``centroid`` as a detection; None outside the window
        (the footprint window unless ``window`` is given)."""
        u, v = float(centroid[0]), float(centroid[1])
        points = geometry.apply(work_to_map, [[u, v], [u + 1.0, v], [u, v + 1.0]])
        if not np.all(np.isfinite(points)):
            return None  # on or beyond the horizon
        (ax, ay), (bx, by) = points[1] - points[0], points[2] - points[0]
        area_m2 = pixels * abs(float(ax * by - ay * bx))
        shrink = 1.0 if camera is None else (camera[2] - self._robot_height_m) / camera[2]
        diameter = 2.0 * math.sqrt(area_m2 / math.pi) * shrink
        low, high = window or self._footprint
        if not low <= diameter <= high:
            return None
        x, y = float(points[0][0]), float(points[0][1])
        if camera is not None:
            x, y = geometry.parallax_correct((x, y), camera, self._robot_height_m)
        return Detection(x=float(x), y=float(y), footprint_m=diameter, score=self._score(diameter))

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
            height, width = dark.shape
            floor = (mask > 0) & (dark == 0)
            for label in range(1, count):
                pixels = int(stats[label, cv2.CC_STAT_AREA])
                detection = self._measure(pixels, centroids[label], work_to_map, camera)
                if detection is None:
                    continue
                left, top, w, h = (int(stats[label, i]) for i in range(4))
                points = cv2.findNonZero((labels[top:top + h, left:left + w] == label).astype(np.uint8))
                short, long = sorted(cv2.minAreaRect(points)[1])
                hull = cv2.convexHull(points)
                # Hull of pixel centres plus half its perimeter and one: about its pixel count.
                hull_px = cv2.contourArea(hull) + cv2.arcLength(hull, True) / 2 + 1
                if long + 1 > BAKED_MAX_ASPECT * (short + 1) or pixels < BAKED_MIN_SOLIDITY * hull_px:
                    continue
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
        self._model = self._new_model()
        for frame in self._frames:
            self._model.apply(frame, learningRate=-1)
        healed = np.zeros(self._frames[0].shape[:2], bool)
        for (y0, y1, x0, x1), where in heals:
            healed[y0:y1, x0:x1] |= where
        # A suspect whose zone was healed by an unsuspected ghost is gone too.
        self._suspects = [suspect for suspect in self._suspects
                          if not healed[suspect[0][0]:suspect[0][1], suspect[0][2]:suspect[0][3]][suspect[2]].all()]

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
