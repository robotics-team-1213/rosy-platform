"""D-865 P2b/P2c 정책 승인 HTTP 표면 — 범위 readback·운영자 전환·감사 조회·자동 승인 루프.

`create_app`이 검증만 하고 경로는 이 모듈이 단다(mission_routes 패턴). 승인 권한은
Fleet이 소유하고 범위 내용(로봇·종류·상한)은 사이트 설정만 정의한다. 전환은 스위치만
바꾼다. app.py 는 크기 레칫(D-766)에 있어 줄을 못 더하므로 루프 기동·정리는 이
인스톨러의 startup/shutdown 이벤트로 한다(lifespan 패턴과 동등한 시점, 등가 확인).
규칙집 law(FL-*)는 이 경로로 해제하지 않는다.
"""

from __future__ import annotations

import asyncio

from fastapi import Depends, HTTPException

from core_common.protocol.policy_admission import (
    PolicyAdmissionAuditEntry,
    PolicyAdmissionAuditResponse,
    PolicyAdmissionReadResponse,
    PolicyAdmissionToggleRequest,
)
from fleet.server.missions.policy_admission import (
    POLICY_ADMISSION_PRINCIPAL,
)


def install_policy_admission_routes(app, *, core, read_guard, operator_guard,
                                    require_viewer,
                                    require_named_operator,
                                    proposal_store=None, mission_service=None,
                                    audit_log=None) -> None:
    @app.get("/api/fleet/policy-admission", dependencies=read_guard,
             tags=["fleet-policy-admission"])
    def policy_admission_status(
            principal: object = Depends(require_viewer)) -> dict:
        return PolicyAdmissionReadResponse(status=core.status()).model_dump(
            mode="json")

    @app.post("/api/fleet/policy-admission", dependencies=operator_guard,
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

    @app.get("/api/fleet/policy-admission/audit", dependencies=read_guard,
             tags=["fleet-policy-admission"])
    def policy_admission_audit(
            principal: object = Depends(require_viewer)) -> dict:
        if audit_log is not None:  # P2c: durable rows win over the core ring
            entries = [PolicyAdmissionAuditEntry(
                mission_id=row["mission_id"], decided_at=row["at"],
                principal=POLICY_ADMISSION_PRINCIPAL,
                scope_revision=row["scope_revision"],
                outcome=row["outcome"], generation=row["generation"],
                reason=row["reason"]).model_dump(mode="json")
                for row in audit_log.latest()]
            return PolicyAdmissionAuditResponse(entries=entries).model_dump(
                mode="json")
        return core.audit().model_dump(mode="json")

    if proposal_store is None or mission_service is None or audit_log is None:
        return  # P2c loop parts not wired: the surface stays read/toggle only

    from fleet.server.missions.policy_admission_worker import (
        PolicyAdmissionWorker, policy_admission_loop)

    worker = PolicyAdmissionWorker(core=core, proposal_store=proposal_store,
                                   mission_service=mission_service,
                                   audit_log=audit_log, log=app.state.log
                                   if hasattr(app.state, "log") else _no_log())

    @app.on_event("startup")
    async def policy_admission_start() -> None:
        app.state.policy_admission_task = asyncio.create_task(
            policy_admission_loop(worker, _no_log()))

    @app.on_event("shutdown")
    async def policy_admission_stop() -> None:
        task = getattr(app.state, "policy_admission_task", None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class _no_log:
    """stdlib-logger-shaped sink: the loop must never die on a missing logger."""

    def warning(self, *_args, **_kwargs) -> None:
        pass

    def exception(self, *_args, **_kwargs) -> None:
        pass
