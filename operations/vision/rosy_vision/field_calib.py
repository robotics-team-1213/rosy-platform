"""Field-boundary auto calibration state machine (D-484).

Turns the D-360 field-boundary detections of one ceiling camera into a measured
image-to-map calibration: an accepted quad, an orientation (which image corner
maps to which configured map corner) resolved from a D-375 paint registration,
and the resulting ``games`` homography. Pure Python — OpenCV stays in the
detection and registration modules.

Safety direction: every unsure outcome (no field, jump, aspect flip, unresolved
orientation) means *no homography*, never a guessed one. Losing the field also
clears the orientation, because a camera that was moved while the field was out
of view could have rotated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from games.field.homography import Homography, fit

CALIB_VERSION = "field-calib/1"

STATES = ("no_field", "orientation_pending", "calibrated", "stale")

#: Acceptance move between detections, as a share of the image diagonal. The
#: camera is fixed; anything larger is a jump, not noise.
MOVE_FRACTION = 0.015
#: A paint-projected map corner must sit within this share of the image
#: diagonal of the matched detected corner for the orientation to count.
ORIENT_GATE_FRACTION = 0.05
#: Consecutive failed detections before the calibration is lost entirely.
LOST_FAILURES = 5
#: Consistent detections at the new position before a jumped quad is accepted.
REACQUIRE_RUNS = 3
#: A re-acquired quad whose aspect ratio flipped by more than this factor
#: clears the orientation (the camera probably rotated about its axis).
ASPECT_FLIP = 1.5


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])

def _max_move(old: tuple[tuple[float, float], ...],
              new: tuple[tuple[float, float], ...]) -> float:
    return max(_distance(o, n) for o, n in zip(old, new))


def _aspect(quad: tuple[tuple[float, float], ...]) -> float:
    """Width over height of the ordered (TL, TR, BR, BL) quad."""
    top = _distance(quad[0], quad[1])
    bottom = _distance(quad[3], quad[2])
    left = _distance(quad[0], quad[3])
    right = _distance(quad[1], quad[2])
    return (top + bottom) / max(1e-9, left + right)


@dataclass(frozen=True)
class FieldCalibState:
    """What one feed reported; ``corners`` are image pixels of the accepted quad."""

    state: str
    reason: str
    confidence: float | None
    corners: tuple[tuple[float, float], ...] | None
    image_size: tuple[int, int]
    orientation: int | None

    def to_dict(self) -> dict:
        width, height = self.image_size
        normalized = None
        if self.corners is not None:
            normalized = [[round(x / max(1, width - 1), 5), round(y / max(1, height - 1), 5)]
                          for x, y in self.corners]
        return {
            "version": CALIB_VERSION,
            "state": self.state,
            "reason": self.reason,
            "confidence": None if self.confidence is None else round(self.confidence, 3),
            "corners": None if self.corners is None else [[round(x, 2), round(y, 2)]
                                                          for x, y in self.corners],
            "corners_normalized": normalized,
            "orientation": self.orientation,
        }


class FieldCalibrator:
    """One source's field-boundary calibration."""

    def __init__(self, corner_world_m, *,
                 move_fraction: float = MOVE_FRACTION,
                 orient_gate_fraction: float = ORIENT_GATE_FRACTION,
                 lost_failures: int = LOST_FAILURES,
                 reacquire_runs: int = REACQUIRE_RUNS) -> None:
        if len(corner_world_m) != 4 or len(set(map(tuple, corner_world_m))) != 4:
            raise ValueError("four distinct map corner coordinates are required")
        if any(len(point) != 2 or any(not math.isfinite(value) for value in point)
               for point in corner_world_m):
            raise ValueError("map corner coordinates must be finite x/y pairs")
        for name, value in (("move_fraction", move_fraction),
                            ("orient_gate_fraction", orient_gate_fraction)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if type(lost_failures) is not int or lost_failures < 1:
            raise ValueError("lost_failures must be a positive integer")
        if type(reacquire_runs) is not int or reacquire_runs < 1:
            raise ValueError("reacquire_runs must be a positive integer")
        self.corner_world_m = tuple((float(x), float(y)) for x, y in corner_world_m)
        self.move_fraction = float(move_fraction)
        self.orient_gate_fraction = float(orient_gate_fraction)
        self.lost_failures = lost_failures
        self.reacquire_runs = reacquire_runs
        self._corners: tuple[tuple[float, float], ...] | None = None
        self._image_size: tuple[int, int] = (0, 0)
        self._orientation: int | None = None
        self._confidence: float | None = None
        self._failures = 0
        self._candidate: tuple[tuple[float, float], ...] | None = None
        self._candidate_runs = 0
        self._reason = "no detection yet"

    # -- inputs -------------------------------------------------------------

    def feed(self, detection) -> FieldCalibState:
        """Consume one D-360 ``FieldDetection``; returns the state after it."""
        width, height = detection.image_size
        if width < 2 or height < 2:
            raise ValueError("detection image size must be at least 2x2")
        if detection.proposal is None:
            self._failures += 1
            self._reason = detection.reason or "field not seen"
            if self._corners is not None and self._failures >= self.lost_failures:
                self._clear(lost=True)
            return self._state()
        corners = tuple((float(x), float(y)) for x, y in detection.proposal.corners)
        if len(corners) != 4:
            self._reason = "detection did not carry four corners"
            return self._state()
        self._failures = 0
        self._image_size = (width, height)
        diagonal = math.hypot(width - 1, height - 1)
        if self._corners is None:
            self._accept(corners, detection.proposal.confidence)
        elif _max_move(self._corners, corners) <= self.move_fraction * diagonal:
            self._accept(corners, detection.proposal.confidence)
        else:
            self._jumped(corners, diagonal, detection.proposal.confidence)
        return self._state()

    def resolve_orientation(self, map_to_image, image_size) -> tuple[bool, str]:
        """Match paint-projected map corners to the accepted quad's corners.

        ``map_to_image`` is the accepted D-375 registration's 3x3 matrix (map
        metres -> full-resolution image pixels). Succeeds only when every
        projected corner lands within the gate of a distinct detected corner and
        the pairing is one cyclic rotation; anything else keeps the orientation
        unset and reports why.
        """
        if self._corners is None:
            return False, "no accepted quad"
        if (len(map_to_image) != 3 or any(len(row) != 3 for row in map_to_image)
                or any(not math.isfinite(value) for row in map_to_image for value in row)):
            raise ValueError("map_to_image must be a finite 3x3 matrix")
        width, height = image_size
        if (width, height) != self._image_size:
            return False, "registration frame size differs from the detection"
        rotations = []
        for world_index, (wx, wy) in enumerate(self.corner_world_m):
            hx = map_to_image[0][0] * wx + map_to_image[0][1] * wy + map_to_image[0][2]
            hy = map_to_image[1][0] * wx + map_to_image[1][1] * wy + map_to_image[1][2]
            hw = map_to_image[2][0] * wx + map_to_image[2][1] * wy + map_to_image[2][2]
            if abs(hw) < 1e-12:
                return False, "projected map corner is at infinity"
            distances = [_distance((hx / hw, hy / hw), corner) for corner in self._corners]
            nearest = min(range(4), key=lambda i: distances[i])
            if distances[nearest] > self.orient_gate_fraction * math.hypot(width - 1, height - 1):
                return False, (f"map corner {world_index} does not sit on a detected corner "
                               f"({distances[nearest]:.1f} px away)")
            rotations.append((world_index - nearest) % 4)
        if len(set(rotations)) != 1:
            return False, "corner pairing is not one cyclic rotation (check corner_world_m order)"
        self._orientation = rotations[0]
        return True, "ok"

    # -- outputs ------------------------------------------------------------

    def needs_orientation(self) -> bool:
        return self._corners is not None and self._orientation is None

    def snapshot(self) -> FieldCalibState:
        """The current state without feeding a detection."""
        return self._state()

    def homography(self) -> Homography | None:
        """Image-to-map homography, or None unless quad and orientation are set.

        Also None while a jump is being re-acquired (stale): the old quad's
        calibration no longer describes the camera, and a wrong pose is worse
        than no sighting.
        """
        if self._corners is None or self._orientation is None or self._candidate is not None:
            return None
        rotated = tuple(self.corner_world_m[(index + self._orientation) % 4]
                        for index in range(4))
        try:
            return fit(self._corners, rotated)
        except (ValueError, ZeroDivisionError):
            return None

    @property
    def state(self) -> str:
        if self._corners is None:
            return "no_field"
        if self._candidate is not None:
            return "stale"
        return "calibrated" if self._orientation is not None else "orientation_pending"

    # -- internals ----------------------------------------------------------

    def _accept(self, corners, confidence) -> None:
        self._corners = corners
        self._confidence = float(confidence)
        self._candidate = None
        self._candidate_runs = 0
        self._reason = "ok" if self._orientation is not None else "orientation unresolved"

    def _jumped(self, corners, diagonal: float, confidence) -> None:
        if (self._candidate is not None
                and _max_move(self._candidate, corners) <= self.move_fraction * diagonal):
            self._candidate_runs += 1
        else:
            self._candidate_runs = 1
        self._candidate = corners
        self._reason = "corner jump; waiting for a stable quad"
        if self._candidate_runs >= self.reacquire_runs:
            old_aspect = _aspect(self._corners)
            if max(_aspect(corners) / max(1e-9, old_aspect),
                   old_aspect / max(1e-9, _aspect(corners))) > ASPECT_FLIP:
                self._orientation = None
                self._reason = "re-acquired with a flipped aspect; orientation cleared"
            else:
                self._reason = "re-acquired"
            self._corners = self._candidate
            self._confidence = float(confidence)
            self._candidate = None
            self._candidate_runs = 0

    def _clear(self, *, lost: bool) -> None:
        self._corners = None
        self._orientation = None
        self._confidence = None
        self._candidate = None
        self._candidate_runs = 0
        if lost:
            self._reason = "field lost"

    def _state(self) -> FieldCalibState:
        return FieldCalibState(
            state=self.state,
            reason=self._reason,
            confidence=self._confidence,
            corners=self._corners,
            image_size=self._image_size,
            orientation=self._orientation,
        )
