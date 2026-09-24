"""core_api_web.api.v1.routes — 라우터 집합.

API Ref §5 구현은 도메인별 모듈에 있다. 이 파일은 그것들을 모아 `app.py` 가
하나의 이름으로 가져가게 할 뿐이며, 여기에 엔드포인트를 추가하지 않는다.
새 엔드포인트는 해당 도메인 모듈에 넣고, 새 도메인이면 모듈을 만들어 여기에
등록한다.
"""

from __future__ import annotations

from core_api_web.api.v1.auth import auth_router
from core_api_web.api.v1.common import admin, enter_navigation_mode, operator, viewer
from core_api_web.api.v1.control import control_router
from core_api_web.api.v1.docking import docking_router
from core_api_web.api.v1.host import host_router
from core_api_web.api.v1.map import map_router
from core_api_web.api.v1.line_follow import line_follow_router
from core_api_web.api.v1.navigation import navigation_router, slam_router
from core_api_web.api.v1.observability import (
    diagnostics_router,
    events_router,
    logs_router,
    metrics_router,
)
from core_api_web.api.v1.robot import power_router, robot_router, sensors_router
from core_api_web.api.v1.safety import safety_router
from core_api_web.api.v1.swarm import swarm_router
from core_api_web.api.v1.system import system_router
from core_api_web.api.v1.traffic import traffic_router
from core_api_web.api.v1.vision import vision_router
from core_api_web.api.v1.waypoints import waypoints_router

__all__ = [
    "admin",
    "auth_router",
    "control_router",
    "diagnostics_router",
    "docking_router",
    "enter_navigation_mode",
    "events_router",
    "host_router",
    "logs_router",
    "line_follow_router",
    "map_router",
    "metrics_router",
    "navigation_router",
    "operator",
    "power_router",
    "robot_router",
    "safety_router",
    "sensors_router",
    "slam_router",
    "swarm_router",
    "system_router",
    "traffic_router",
    "vision_router",
    "viewer",
    "waypoints_router",
]
