"""Ceiling camera. The only games module that may import cv2."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from games.field.geometry import goal_mouth
from games.field.homography import field_corners, fit
from games.game import Observation
from games.host.project import observation_from_pixels
from games.host.robots import MatchSetup

Point = tuple[float, float]


class OverheadCamera:
    def __init__(self, setup: MatchSetup, *, capture: Any = None) -> None:
        self.setup = setup
        self._owns = capture is None
        self._cap = capture
        self.last_markers: tuple[int, ...] = ()
        self.last_jpeg: bytes | None = None
        if capture is None:
            self._cap = cv2.VideoCapture(setup.camera.index)
            if not self._cap.isOpened():
                raise RuntimeError(f"cannot open camera {setup.camera.index}")

    def observe(self) -> Observation:
        ok, frame = self._cap.read()
        if not ok:
            return self._lost()
        return self.observe_frame(frame)

    def observe_frame(self, bgr: np.ndarray) -> Observation:
        markers = detect_markers(bgr)
        self.last_markers = tuple(sorted(markers))
        self.last_jpeg = _jpeg(bgr)
        homography = _homography(markers, self.setup)
        ball = detect_ball(bgr, self.setup.camera.hsv_low, self.setup.camera.hsv_high)
        robots = _robot_pixels(markers, self.setup)
        home_goal, away_goal = _goal_polygons(bgr, markers, homography, self.setup)
        return observation_from_pixels(
            field=self.setup.field,
            homography=homography,
            ball_uv=ball,
            robots=robots,
            roster=(self.setup.field.home_id, self.setup.field.away_id),
            home_goal=home_goal,
            away_goal=away_goal,
        )

    def close(self) -> None:
        if self._owns and self._cap is not None:
            self._cap.release()
            self._cap = None

    def _lost(self) -> Observation:
        self.last_markers = ()
        self.last_jpeg = None
        return observation_from_pixels(
            field=self.setup.field,
            homography=None,
            ball_uv=None,
            robots={},
            roster=(self.setup.field.home_id, self.setup.field.away_id),
        )


def detect_markers(bgr: np.ndarray) -> dict[int, np.ndarray]:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    corners, ids, _ = _detect(bgr, dictionary)
    if ids is None:
        return {}
    return {int(i): c[0] for i, c in zip(ids.flatten(), corners)}


def detect_ball(
    bgr: np.ndarray,
    hsv_low: tuple[int, int, int],
    hsv_high: tuple[int, int, int],
    *,
    min_area: float = 20.0,
) -> Point | None:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(hsv_low), np.array(hsv_high))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    blob = max(contours, key=cv2.contourArea)
    if cv2.contourArea(blob) < min_area:
        return None
    moments = cv2.moments(blob)
    if moments["m00"] == 0:
        return None
    return moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]


def _detect(bgr: np.ndarray, dictionary: Any):
    try:
        detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
        return detector.detectMarkers(bgr)
    except AttributeError:
        return cv2.aruco.detectMarkers(bgr, dictionary)


def _homography(markers: dict[int, np.ndarray], setup: MatchSetup):
    pixels = []
    for marker_id in setup.camera.corner_ids:
        quad = markers.get(marker_id)
        if quad is None:
            return None
        pixels.append(_center(quad))
    return fit(tuple(pixels), field_corners(setup.field))


def _robot_pixels(markers: dict[int, np.ndarray], setup: MatchSetup) -> dict[str, tuple[Point, Point]]:
    out: dict[str, tuple[Point, Point]] = {}
    for robot in setup.robots:
        quad = markers.get(robot.aruco_id)
        if quad is None:
            continue
        center = _center(quad)
        tip = (float(quad[1][0]), float(quad[1][1]))
        out[robot.id] = (center, tip)
    return out


def _jpeg(bgr: np.ndarray) -> bytes | None:
    ok, buf = cv2.imencode(".jpg", bgr)
    if not ok:
        return None
    return buf.tobytes()


def _center(quad: np.ndarray) -> Point:
    return float(quad[:, 0].mean()), float(quad[:, 1].mean())


def _goal_polygons(bgr: np.ndarray, markers: dict[int, np.ndarray], homography, setup: MatchSetup):
    if homography is None:
        return None, None
    half = setup.field.goal_width_m / 2
    home = _mouth_from_marker(markers, setup.goals.home_id, homography, home=True, half_width=half)
    away = _mouth_from_marker(markers, setup.goals.away_id, homography, home=False, half_width=half)
    if setup.goals.hsv_low is not None and setup.goals.hsv_high is not None:
        hsv_home, hsv_away = _mouths_from_hsv(
            bgr,
            homography,
            setup.goals.hsv_low,
            setup.goals.hsv_high,
        )
        if hsv_home is not None:
            home = hsv_home
        if hsv_away is not None:
            away = hsv_away
    return home, away


def _mouth_from_marker(
    markers: dict[int, np.ndarray],
    marker_id: int,
    homography,
    *,
    home: bool,
    half_width: float,
):
    quad = markers.get(marker_id)
    if quad is None:
        return None
    x, y = homography.apply(*_center(quad))
    return goal_mouth(x, y, home=home, half_width=half_width)


def _mouths_from_hsv(bgr: np.ndarray, homography, hsv_low, hsv_high):
    regions = detect_regions(bgr, hsv_low, hsv_high)
    home = None
    away = None
    for pixels in regions:
        field_pts = tuple(homography.apply(u, v) for u, v in pixels)
        cx = sum(p[0] for p in field_pts) / len(field_pts)
        if cx < 0:
            home = field_pts
        else:
            away = field_pts
    return home, away


def detect_regions(
    bgr: np.ndarray,
    hsv_low: tuple[int, int, int],
    hsv_high: tuple[int, int, int],
    *,
    min_area: float = 20.0,
) -> list[list[Point]]:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(hsv_low), np.array(hsv_high))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out: list[list[Point]] = []
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue
        xs = contour[:, 0, 0]
        ys = contour[:, 0, 1]
        out.append(
            [
                (float(xs.min()), float(ys.min())),
                (float(xs.max()), float(ys.min())),
                (float(xs.max()), float(ys.max())),
                (float(xs.min()), float(ys.max())),
            ]
        )
    return out
