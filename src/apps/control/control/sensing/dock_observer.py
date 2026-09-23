"""Subject: dock tag evidence — one camera frame to one wire observation.

The stage-3 parking marker is observed here, in control, because frames and
OpenCV live here (D-66: CORE has neither). This subject only reports where
the tag is in base_link; CORE's docking manager decides whether and how the
robot moves and remains the sole final ``cmd_vel`` publisher.

Wire shape (``dock/observation``, std_msgs/String JSON), in the style of
``line/observation``: ``source`` CAMERA_TAG, ``stamp`` (the frame's capture
stamp), ``visible``, ``tag_id``, ``x``/``y`` (tag centre, base_link, m),
``yaw`` (the tag's inward axis in base_link, rad; 0 when squarely faced),
``range_m``, ``confidence`` and ``revision``. Not visible: the pose fields
are None and confidence is 0 — a lost tag reads as lost, never as a guess.

ROS-free: dock_observer_node only feeds frames and publishes the dict.
"""

from __future__ import annotations

import math

import numpy as np

from .dock_tag import CameraMount, DockTagObservation, DockTagSpec, detect_dock_tag

SOURCE = "CAMERA_TAG"


def camera_matrix_from_hfov(width: int, height: int, hfov_rad: float) -> np.ndarray | None:
    """Pinhole matrix of a distortion-free camera (Gazebo's), principal point
    at the image centre as camera_ground.simulation_ground_plane has it.
    None when the geometry is unusable."""
    try:
        width, height, hfov_rad = float(width), float(height), float(hfov_rad)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (width, height, hfov_rad)):
        return None
    if width <= 0 or height <= 0 or not 0.0 < hfov_rad < math.pi:
        return None
    focal = (width / 2.0) / math.tan(hfov_rad / 2.0)
    return np.array([[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]])


def dock_observation_payload(stamp: float, observation: DockTagObservation | None) -> dict:
    """The one wire shape (module docstring)."""
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) \
            or not math.isfinite(float(stamp)):
        raise ValueError("dock observation stamp must be finite")
    if observation is None:
        return {"source": SOURCE, "stamp": float(stamp), "visible": False,
                "tag_id": None, "x": None, "y": None, "yaw": None, "range_m": None,
                "confidence": 0.0, "revision": None}
    return {"source": SOURCE, "stamp": float(stamp), "visible": True,
            "tag_id": int(observation.tag_id), "x": float(observation.x),
            "y": float(observation.y), "yaw": float(observation.yaw),
            "range_m": float(observation.range_m),
            "confidence": float(observation.confidence),
            "revision": observation.revision}


class DockTagObserver:
    """Frames in, payloads out. The camera matrix follows the frame size
    (built from `hfov_rad` once per size); `mount` places the camera on
    base_link. Construction validates the tag contract and the mount: an
    observer that cannot know the tag size or where the camera sits
    refuses to start rather than publish a wrong pose."""

    def __init__(self, *, tag_id: int, tag_size_m: float, mount: CameraMount,
                 hfov_rad: float) -> None:
        self._spec = DockTagSpec(tag_id=tag_id, size_m=tag_size_m)
        if not isinstance(mount, CameraMount):
            raise ValueError("a CameraMount is required")
        if camera_matrix_from_hfov(320, 180, hfov_rad) is None:
            raise ValueError("hfov_rad must be in (0, pi)")
        self._mount = mount
        self._hfov = float(hfov_rad)
        self._matrix_key = None
        self._matrix = None
        self._dist = np.zeros(5)

    def observe(self, frame: np.ndarray, stamp: float) -> dict:
        if not isinstance(frame, np.ndarray) or frame.ndim not in (2, 3) or frame.size == 0:
            raise ValueError("camera frame must be a non-empty grayscale or BGR array")
        key = (frame.shape[1], frame.shape[0])
        if key != self._matrix_key:
            self._matrix = camera_matrix_from_hfov(key[0], key[1], self._hfov)
            self._matrix_key = key
        observation = detect_dock_tag(frame, self._spec, self._matrix, self._dist,
                                      mount=self._mount)
        return dock_observation_payload(stamp, observation)
