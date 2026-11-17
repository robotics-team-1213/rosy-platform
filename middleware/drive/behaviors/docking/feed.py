"""core_features.docking.feed — control 의 `dock/observation` 증거를 받는 자리.

CORE 는 프레임도 OpenCV 도 갖지 않는다(D-66). 태그 검출은 control 의
dock_observer_node 가 하고, 여기서는 그 결과(base_link 기준 태그 중심과 안쪽 축
방위)를 받아 도킹 매니저의 검출기 경계(`DockDetector`) 뒤에 놓는다.

시계: 수신 시각은 ros_bridge 가 라인 시계(use_sim_time 이면 sim 시계)로 찍는다.
관측 시각은 `received_at - (source_now - stamp)` — 촬영 시각을 매니저 시계로 옮긴
것이다. 매니저가 같은 시계로 묶여 있어야 신선도가 맞는다.

ROS 무의존.
"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

from core_features.docking.detector import DockObservation

SOURCE = "CAMERA_TAG"
LIDAR_V = "LIDAR_V"   # rear dock V marker (D-950 follow-up), from dock_lidar_observer_node
CAMERA_LINE = "CAMERA_LINE"  # charge-bay pink guide line (D-1013), from bay_line_observer_node
SOURCES = (SOURCE, LIDAR_V, CAMERA_LINE)


def _finite(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("expected a finite number")
    return value


class DockObservationFeed:
    """The latest observation per source (camera tag, rear LiDAR V). A
    not-visible payload clears its own source: a lost dock must read as lost,
    not as its last sighting, and one sensor's miss does not erase another's."""

    def __init__(self) -> None:
        self._latest: dict[str, tuple[Optional[int], DockObservation]] = {}

    def ingest(self, payload, *, received_at: float, source_now: float) -> bool:
        """One wire payload; True when it carried a visible dock. Raises
        ValueError on a malformed payload (and clears that source first)."""
        source = payload.get("source") if isinstance(payload, dict) else None
        try:
            if source not in SOURCES:
                raise ValueError("not a CAMERA_TAG, LIDAR_V or CAMERA_LINE dock observation")
            if type(payload.get("visible")) is not bool:
                raise ValueError("visible must be a boolean")
            stamp = _finite(payload.get("stamp"))
            if not payload["visible"]:
                self._latest.pop(source, None)
                return False
            tag_id = payload.get("tag_id")
            # The V marker has no identity; a tag without an integer id is malformed.
            if (type(tag_id) is not int) if source == SOURCE else tag_id is not None:
                raise ValueError("tag_id must be an integer (CAMERA_TAG) or null (LIDAR_V)")
            age = max(0.0, _finite(source_now) - stamp)
            observation = DockObservation(
                x=_finite(payload.get("x")), y=_finite(payload.get("y")),
                yaw=_finite(payload.get("yaw")),
                confidence=min(1.0, max(0.0, _finite(payload.get("confidence")))),
                at=_finite(received_at) - age)
        except (ValueError, TypeError):
            # Garbage of unknown origin clears every source: lost, not guessed.
            if source in SOURCES:
                self._latest.pop(source, None)
            else:
                self._latest.clear()
            raise
        self._latest[source] = (tag_id, observation)
        return True

    def latest(self, tag_id: Optional[int] = None, source: str = SOURCE) -> Optional[DockObservation]:
        if source not in self._latest:
            return None
        seen_id, observation = self._latest[source]
        if tag_id is not None and seen_id != tag_id:
            return None
        return observation


class FeedDetector:
    """`DockDetector` over a feed: the latest observation of our tag, if it
    is younger than `staleness_s` on `clock` and was captured after
    `start` minus that same window."""

    def __init__(self, feed: DockObservationFeed, *, tag_id: Optional[int],
                 clock: Callable[[], float] = time.monotonic,
                 staleness_s: float = 0.6, source: str = SOURCE) -> None:
        self._feed = feed
        self._tag_id = tag_id
        self._source = source
        self._clock = clock
        self._staleness_s = float(staleness_s)
        self._started = False

    def start(self, dock=None) -> None:
        self._started = True

    def relative_pose(self) -> Optional[DockObservation]:
        if not self._started:
            return None
        observation = self._feed.latest(self._tag_id, self._source)
        if observation is None:
            return None
        age = self._clock() - observation.at
        if not 0.0 <= age <= self._staleness_s:
            return None
        return observation

    def stop(self) -> None:
        self._started = False
