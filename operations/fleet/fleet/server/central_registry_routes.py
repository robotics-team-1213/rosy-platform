"""중앙 Fleet 경로 — `/api/v1/fleet/*` (D-454 1단계, API Ref §10.1 읽기 2경로).

사이트 프로파일(`/api/fleet/*`)과 같은 앱에 마운트된다. 인증은 시드의 역할 가드를
그대로 쓴다(읽기=Viewer 이상). 나머지 §10.1 경로(변경·페어링 토큰·승인 대기·폐기)는
뒤 작업이 같은 모듈에 더한다.
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException

from fleet.hub.hub import HubError
from fleet.server.central_registry import CentralRegistry
from fleet.server.roster import RosterConflict


def install_registry_routes(app: FastAPI, *, registry, enrollment, pairing, sync_token,
                            require_viewer: Callable, require_operator: Callable,
                            named_identity: bool) -> None:
    """Compose existing registry/pairing owners without changing their guards or writes."""
    if enrollment is not None:
        from fleet.server.enrollment_routes import install_enrollment_routes
        install_enrollment_routes(app, enrollment, require_viewer=require_viewer,
                                  require_operator=require_operator, named_identity=named_identity)
    if pairing is not None:
        from fleet.server.pairing_routes import install_pairing_routes
        install_pairing_routes(app, pairing, sync_token=sync_token,
                               require_viewer=require_viewer, require_operator=require_operator,
                               named_identity=named_identity)
    if registry is not None:
        install_central_registry_routes(app, registry, require_viewer=require_viewer)


def install_central_registry_routes(app: FastAPI, registry: CentralRegistry, *,
                                    require_viewer: Callable,
                                    require_operator: Callable) -> None:
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

    @router.delete("/api/v1/fleet/robots/{robot_id}",
                   dependencies=[Depends(require_operator)], tags=["central-fleet"])
    async def fleet_robot_delete(robot_id: str) -> dict:
        """등록 해제(REG-001a). 로스터의 차단(진행 작업 등)은 409 로 내려온다."""
        try:
            await registry.roster.remove(robot_id)
        except RosterConflict as conflict:
            detail = {"code": conflict.code, "message": str(conflict)}
            if conflict.task_ids:
                detail["task_ids"] = conflict.task_ids
            raise HTTPException(status_code=409, detail=detail) from None
        except HubError as error:
            status = 404 if error.code == "UNKNOWN_ROBOT" else 409
            raise HTTPException(status_code=status,
                                detail={"code": error.code, "message": str(error)}) from None
        return {"robot_id": robot_id, "removed": True}

    app.include_router(router)
