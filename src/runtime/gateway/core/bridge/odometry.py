"""Odometry-derived geometry the bridge used to compute inline. ROS-free.

Undocking measures how far it has come with this and nothing else — no sensor
confirms it — so a wrong answer drives the robot into the dock or leaves it
short of clearance, and neither shows up in a boot smoke test.
"""

from __future__ import annotations

import math
from typing import Optional

Point = Optional[tuple[float, float]]


def travelled_m(mark: Point, current: Point) -> float:
    """Straight-line distance from the mark, or 0.0 when there is no baseline.

    Zero is the safe answer for a missing mark: the caller reads this as "not
    far enough yet" and keeps waiting, where a large number would read as
    "clear" and stop a reverse early. Straight-line is deliberate — undocking
    reverses along one axis, so path length would only add drift.
    """
    if mark is None or current is None:
        return 0.0
    return math.hypot(current[0] - mark[0], current[1] - mark[1])


#: map→base TF 를 이 시간 안에 읽었으면 map 프레임 pose 가 살아 있다고 본다. state 틱은
#: 기본 10 Hz 라 여유 있게 잡는다 - 한두 틱 놓쳤다고 화면이 odom 으로 튀면 안 된다.
MAP_POSE_TTL_S = 2.0


def odom_owns_pose(map_pose_ts: float, now: float,
                   ttl_s: float = MAP_POSE_TTL_S) -> bool:
    """odom 이 보고 pose 를 써도 되는가.

    브리지에는 pose 를 쓰는 곳이 둘이다 - odom 콜백(약 30 Hz)과 map→base TF 를 읽는 state
    틱(10 Hz). 둘 다 같은 필드에 쓰면 주기가 높은 odom 이 대부분 이겨서, 보고 위치가
    조용히 odom 프레임으로 바뀐다. 미로 주행 뒤 AMCL 은 정답과 4 cm 안에 있었는데 API 는
    3.3 m 떨어진 odom 값을 돌려줬다 - 관제 화면도 미션 판정도 그 값을 읽는다.

    그래서 map 프레임이 권위다. odom 은 그것이 없을 때만 - 맵도 SLAM 도 없는 teleop
    구성에서는 화면에 무엇이라도 띄워야 하므로 - 폴백으로 쓴다.
    """
    return (now - map_pose_ts) >= ttl_s
