"""Subject: ArUco dock detector lifecycle — frames to dock observations.

Wraps :func:`dock_tag.detect_dock_tag` with the `start` / `relative_pose` /
`stop` shape the docking state machine drives. The shape is structural: this
module never imports the docking package, so no control→core edge is added
(D-64). The manager only calls the three methods and reads `range_m`/`x`/`y`.

`start` on a bad tag contract raises instead of running blind — a detector
that cannot know the tag size must refuse, not guess (SRS: fail-closed).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Optional

import numpy as np

from .dock_tag import DockTagObservation, DockTagSpec, detect_dock_tag


class ArucoDockDetector:
    """Lifecycle wrapper. `frame_source` returns the latest BGR frame or None;
    `clock` stamps observations so the manager's loss accounting reads
    freshness, not frames."""

    def __init__(self, frame_source: Callable[[], Optional[np.ndarray]], *,
                 tag_id: int, tag_size_m: float,
                 camera_matrix: np.ndarray, dist_coeffs: np.ndarray,
                 revision: str = "dock-tag-v1",
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._frame_source = frame_source
        # Validated now: a detector that cannot know the tag size refuses
        # at construction, not mid-approach.
        self._spec = DockTagSpec(tag_id=tag_id, size_m=tag_size_m, revision=revision)
        self._camera_matrix = camera_matrix
        self._dist_coeffs = dist_coeffs
        self._clock = clock
        self._started = False

    def start(self, dock: Any = None) -> None:
        self._started = True

    def relative_pose(self) -> Optional[DockTagObservation]:
        if not self._started:
            return None
        frame = self._frame_source()
        if frame is None:
            return None
        obs = detect_dock_tag(frame, self._spec,
                              self._camera_matrix, self._dist_coeffs)
        if obs is None:
            return None
        return replace(obs, at=self._clock())

    def stop(self) -> None:
        self._started = False
