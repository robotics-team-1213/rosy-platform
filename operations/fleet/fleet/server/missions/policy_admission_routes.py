"""D-865 P2b 정책 승인 HTTP 표면 — 범위 readback·운영자 전환·감사 조회.

`create_app`이 검증만 하고 경로는 이 모듈이 단다(mission_routes 패턴). 승인 권한은
Fleet이 소유하고 범위 내용(로봇·종류·상한)은 사이트 설정만 정의한다. 전환은 스위치만
바꾼다. 자동 admit 루프는 이 표면과 별도 조립이 기존 mission 경로와 같은 소유에서
연결한다(P2c). 규칙집 law(FL-*)는 이 경로로 해제하지 않는다.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException

from core_common.protocol.policy_admission import (
    PolicyAdmissionReadResponse,
    PolicyAdmissionToggleRequest,
)


def install_policy_admission_routes(app, *, core, read_guard, operator_guard,
                                    require_viewer,
                                    require_named_operator) -> None:
    @app.get("/api/fleet/policy-admission", dependencies=[read_guard],
             tags=["fleet-policy-admission"])
    def policy_admission_status(
            principal: object = Depends(require_viewer)) -> dict:
        return PolicyAdmissionReadResponse(status=core.status()).model_dump(
            mode="json")

    @app.post("/api/fleet/policy-admission", dependencies=[operator_guard],
              tags=["fleet-policy-admission"])
    def policy_admission_toggle(body: PolicyAdmissionToggleRequest,
                                principal: object = Depends(
                                    require_named_operator)) -> dict:
        try:
            status = core.toggle(enabled=body.enabled)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={
                "code": "POLICY_ADMISSION_SCOPE_NOT_CONFIGURED",
                "message": str(exc)}) from exc
        return PolicyAdmissionReadResponse(status=status).model_dump(
            mode="json")

    @app.get("/api/fleet/policy-admission/audit", dependencies=[read_guard],
             tags=["fleet-policy-admission"])
    def policy_admission_audit(
            principal: object = Depends(require_viewer)) -> dict:
        return core.audit().model_dump(mode="json")
