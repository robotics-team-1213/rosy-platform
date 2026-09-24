"""core_features.docking.detector — 도크 검출 경계와 시뮬레이션 구현.

**감지 방식은 여기서 정하지 않는다.** LiDAR 역반사판이냐 IR 비콘이냐 카메라
태그냐는 카메라가 실기 드라이버를 갖느냐에 달렸고 그것은 별도 스펙이다. 이
모듈이 하는 일은 그 선택을 경계 뒤로 밀어 상태머신이 먼저 만들어지고 먼저
검증되게 하는 것이다.

경계 위의 어떤 코드도 스캔·이미지·IR 값을 보지 않는다. 전부 `DockObservation`
하나만 소비한다.

설계: docs/plans/2026-09-02-docking-station-design.md §"검출은 경계 뒤에 둔다"
"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional, Protocol, Sequence, runtime_checkable

import logging

from pydantic import BaseModel, Field

from core_features.docking.database import DockInstance


log = logging.getLogger(__name__)


def select_detector(dock: DockInstance, dock_type, *,
                    provider=None, frame_source=None,
                    camera_matrix=None, dist_coeffs=None,
                    clock: Callable[[], float] = time.monotonic,
                    feed=None):
    """Choose the detector for one docking run (DNC-007, D-138).

    `detector="observation"` reads control's `dock/observation` evidence
    through `feed` (stage-3 parking; the tag is detected in control, CORE
    keeps no frames and no OpenCV). Without a feed it falls back to the
    empty script like every other incomplete stack.

    The ArUco vision detector is selected only when the whole stack is
    present: `detector="aruco"` naming it, a complete tag spec on the dock
    type, a provider exposing `make_dock_detector` (resolved through the
    `rosy.sensor_provider` port — never a static control import), and a frame
    source plus camera geometry. Anything missing falls back to an empty
    script, whose observations are always None: the state machine times out
    into `DOCK_FAILED` instead of driving on a guess. A provider that raises
    (no cv2 on this image) falls back the same way, with a warning.
    """
    if dock_type.detector == "observation" and feed is not None:
        from core_features.docking.feed import FeedDetector

        return FeedDetector(feed, tag_id=getattr(dock_type, "tag_id", None), clock=clock)
    if (dock_type.detector == "aruco"
            and getattr(dock_type, "tag_id", None) is not None
            and getattr(dock_type, "tag_size_m", None) is not None
            and provider is not None
            and callable(getattr(provider, "make_dock_detector", None))
            and frame_source is not None
            and camera_matrix is not None):
        try:
            return provider.make_dock_detector(
                tag_id=dock_type.tag_id, tag_size_m=dock_type.tag_size_m,
                frame_source=frame_source, camera_matrix=camera_matrix,
                dist_coeffs=dist_coeffs, clock=clock)
        except Exception as exc:
            log.warning("aruco detector unavailable, staying simulated: %s", exc)
    return SimulatedDetector(script=[])


class DockObservation(BaseModel):
    """`base_link` 기준 도크 상대 포즈 1건.

    맵 좌표가 아니라 상대 좌표인 것이 핵심이다. 최종 접근은 맵을 쓰지 않는다 —
    로컬라이제이션 오차(±10 cm)가 접점 공차(±5 mm)보다 두 자릿수 크기 때문이다.
    """

    x: float
    y: float
    yaw: float
    confidence: float = Field(ge=0.0, le=1.0)
    at: float                       # 관측 시각 (주입 시계 기준)

    @property
    def range_m(self) -> float:
        return math.hypot(self.x, self.y)


@runtime_checkable
class DockDetector(Protocol):
    """도크 검출기. 상태머신이 아는 유일한 감지 인터페이스."""

    def start(self, dock: DockInstance) -> None: ...

    def relative_pose(self) -> Optional[DockObservation]: ...

    def stop(self) -> None: ...


class SimulatedDetector:
    """대본을 재생하는 검출기 — 하드웨어 없이 상태머신을 검증한다.

    실물 검출기가 아직 없어서 만든 임시물이 아니다. 실물이 생긴 뒤에도 접근
    실패·도크 상실·정지 관측 같은 경로를 결정론적으로 재현하려면 이것이 필요하다.
    """

    def __init__(self, script: Sequence[tuple[float, float, float]],
                 clock: Callable[[], float] = time.monotonic,
                 step_s: float = 0.2,
                 staleness_s: float = 1.0,
                 confidence: float = 1.0) -> None:
        self._script = list(script)
        self._clock = clock
        self._step_s = step_s
        self._staleness_s = staleness_s
        self._confidence = confidence

        self._started_at: Optional[float] = None
        self._lost = False
        self._frozen_at: Optional[float] = None

    # --- DockDetector ---------------------------------------------------------

    def start(self, dock: DockInstance) -> None:
        # 재시작은 이전 회차를 완전히 지운다. 재시도가 직전 실패의 잔상을
        # 물려받으면 재시도가 아니다.
        self._started_at = self._clock()
        self._lost = False
        self._frozen_at = None

    def relative_pose(self) -> Optional[DockObservation]:
        if self._started_at is None or self._lost or not self._script:
            return None

        now = self._clock()
        sample_at = self._frozen_at if self._frozen_at is not None else now

        # 표본이 끊긴 뒤 마지막 목격을 계속 돌려주면, 잃어버린 도크가 확신 있는
        # 오답이 된다. 신선도를 넘긴 관측은 없는 것으로 본다.
        if now - sample_at > self._staleness_s:
            return None

        index = int((sample_at - self._started_at) / self._step_s)
        index = max(0, min(index, len(self._script) - 1))
        x, y, yaw = self._script[index]
        return DockObservation(x=x, y=y, yaw=yaw,
                               confidence=self._confidence, at=sample_at)

    def stop(self) -> None:
        self._started_at = None
        self._frozen_at = None

    # --- 테스트 조작 -----------------------------------------------------------

    def lose(self) -> None:
        """도크를 시야에서 놓친다."""
        self._lost = True

    def freeze(self) -> None:
        """새 표본이 끊긴 상황 — 시계는 가지만 관측은 갱신되지 않는다."""
        self._frozen_at = self._clock()
