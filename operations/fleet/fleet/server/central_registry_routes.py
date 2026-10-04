"""중앙 Fleet 경로 — `/api/v1/fleet/*` (D-454 1단계, API Ref §10.1 읽기 2경로).

사이트 프로파일(`/api/fleet/*`)과 같은 앱에 마운트된다. 인증은 시드의 역할 가드를
그대로 쓴다(읽기=Viewer 이상). 나머지 §10.1 경로(변경·페어링 토큰·승인 대기·폐기)는
뒤 작업이 같은 모듈에 더한다.
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException

from fleet.server.central_registry import CentralRegistry


def install_central_registry_routes(app: FastAPI, registry: CentralRegistry, *,
                                    require_viewer: Callable) -> None:
    router = APIRouter()

    @router.get("/api/v1/fleet/robots", dependencies=[Depends(require_viewer)],
                tags=["central-fleet"])
    def fleet_robots() -> dict:
        return {"robots": registry.rows()}

    @router.get("/api/v1/fleet/robots/{robot_id}", dependencies=[Depends(require_viewer)],
                tags=["central-fleet"])
    def fleet_robot(robot_id: str) -> dict:
        row = registry.row(robot_id)
        if row is None:
            raise HTTPException(status_code=404,
                                detail={"code": "UNKNOWN_ROBOT", "message": robot_id})
        return row

    app.include_router(router)
