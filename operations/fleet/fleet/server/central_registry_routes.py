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


def install_central_registry_routes(app: FastAPI, registry: CentralRegistry, *,
                                    require_viewer: Callable,
                                    require_operator: Callable,
                                    enrollment=None) -> None:
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

    # -- §10.1 나머지 — 등록 저장소가 정본인 경로 (D-454 1c) -----------------

    @app.patch("/api/v1/fleet/robots/{robot_id}",
               dependencies=[Depends(require_operator)], tags=["central-fleet"])
    async def fleet_robot_patch(robot_id: str, body: dict) -> dict:
        """이름·그룹 변경(REG-003). 이 단계는 등록 저장소의 discovery_name만 건넨다."""
        from fleet.server.enrollment import EnrollmentError
        if enrollment is None:
            raise HTTPException(status_code=501,
                                detail={"code": "NOT_IMPLEMENTED",
                                        "message": "no enrollment store; PATCH needs --central with --enrollment-db"})
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=422,
                                detail={"code": "INVALID_NAME",
                                        "message": "body.name must be a non-empty string"})
        try:
            enrollment._store.update(robot_id, discovery_name=name.strip())
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404,
                                detail={"code": "UNKNOWN_ROBOT", "message": robot_id}) from exc
        except EnrollmentError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.body()) from exc
        return {"robot_id": robot_id, "name": name.strip()}

    @app.post("/api/v1/fleet/robots/{robot_id}/token/revoke",
              dependencies=[Depends(require_operator)], tags=["central-fleet"])
    async def fleet_robot_token_revoke(robot_id: str) -> dict:
        """토큰 폐기(SEC-203). 등록 상태를 needs_new_code로 전환해 재발급을 강제한다."""
        if enrollment is None:
            raise HTTPException(status_code=501,
                                detail={"code": "NOT_IMPLEMENTED",
                                        "message": "no enrollment store"})
        try:
            enrollment._store.update(robot_id, state="needs_new_code")
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404,
                                detail={"code": "UNKNOWN_ROBOT", "message": robot_id}) from exc
        return {"robot_id": robot_id, "token_state": "revoked"}

    @app.get("/api/v1/fleet/pending-robots",
             dependencies=[Depends(require_operator)], tags=["central-fleet"])
    def fleet_pending_robots() -> dict:
        """승인 대기 목록(SEC-202). 이 단계는 비-active 상태 등록 로봇을 돌려준다."""
        if enrollment is None:
            raise HTTPException(status_code=501,
                                detail={"code": "NOT_IMPLEMENTED",
                                        "message": "no enrollment store"})
        listing = enrollment.listing()
        pending = [row for row in listing.get("robots", [])
                   if row.get("state") not in (None, "active")]
        return {"pending": pending}

    @app.post("/api/v1/fleet/pairing-tokens",
              dependencies=[Depends(require_operator)], tags=["central-fleet"])
    def fleet_pairing_token_issue() -> dict:
        """1회용 페어링 토큰 발급(SEC-201). D-341 승인 흐름과의 통합은 뒤 작업 설계가 소유한다."""
        raise HTTPException(status_code=501,
                            detail={"code": "NOT_IMPLEMENTED",
                                    "message": "pairing-token issuance requires the D-341 pairing service integration"})
