"""260919 트랙을 장면 데이터로만 적는다.

숫자 근거는 차선 그래프와 점유 격자다. 서쪽 문은 왼쪽 선의 주차 입구
(s = 1.437 m), 정차는 (-1.000, 0.000) 이라 통과 선에서 0.27 m 다.
동쪽 문은 (0.327, 0.301) 의 s = 0.860 m 이고, 정차 (0.650, 0.300) 은
통과 선과 벽에서 모두 0.32 m 다. 로터리 한가운데는 대기 자리가 아니라
구간에 문이 없다.
"""

from __future__ import annotations

from fleet.meet.scene import Door, Edge, Pin, Robot, Room, Scene

BODY_M = 0.17


def track_v2(robots: tuple[Robot, ...] = (), body_m: float = BODY_M,
             pins: tuple[Pin, ...] = ()) -> Scene:
    return Scene(
        edges=(
            Edge("west", 2.865, oneway=False),
            Edge("east", 3.992, oneway=False),
            Edge("ring_e", 0.460, oneway=True),
            Edge("ring_n", 0.372, oneway=True),
            Edge("ring_w", 0.374, oneway=True),
            Edge("ring_s", 0.374, oneway=True),
        ),
        rooms=(
            Room("west_spot", (-1.0, 0.0), 0.27),
            Room("east_room", (0.65, 0.30), 0.32),
        ),
        doors=(
            Door("west", 1.437, "west_spot"),
            Door("east", 0.860, "east_room"),
        ),
        robots=robots,
        body_m=body_m,
        pins=pins,
    )
