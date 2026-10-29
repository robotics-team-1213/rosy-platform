"""Board hardware readback and safe test request API (D-247)."""

from __future__ import annotations

from datetime import timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, StrictBool

from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import admin, operator, viewer
from core_common.protocol.schemas import LampIdentifyRequest
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike


hardware_router = APIRouter(tags=["host"])

HW_STALE_AFTER_S = 600.0
HW_SCHEMA = 1


@hardware_router.get("/hardware")
def host_hardware(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """보드의 모든 장치가 붙어 있고 응답하는지 (D-247). capability와는 다른 질문이다."""
    try:
        result = svc.host_files.hardware(svc)
    except FileNotFoundError:
        return {"available": False, "detail": "장치 점검 결과가 아직 없습니다", "devices": []}
    except OSError:
        result = None
    if result is None:
        return {"available": False, "detail": "장치 점검 결과를 읽을 수 없습니다", "devices": []}
    measured = result["measured_at"]
    age = result["age_s"]
    return {
        "available": True,
        "schema": HW_SCHEMA,
        "measured_at": measured.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "age_s": round(age, 1),
        "stale": age > HW_STALE_AFTER_S,
        "boot_id": result["boot_id"],
        "devices": result["devices"],
        # D-247 6: the last buzzer/lamp test rosy-hw-test ran, for the card to show.
        "test": result["test"],
        "detail": "",
    }


@hardware_router.post("/hardware/refresh")
def host_hardware_refresh(auth: AuthContext = Depends(admin), svc: CoreServicesLike = Depends(get_services)):
    """rosy-hw-probe 재실행 요청. CORE는 요청 파일만 쓰고 측정은 root가 한다(D-161)."""
    try:
        accepted = svc.host_files.refresh_hardware(svc, by=auth.token_id)
    except svc.host_files.Error as exc:
        raise ApiError(exc.code, 503, str(exc)) from exc
    return {"accepted": accepted, "detail": "장치 점검을 요청했습니다. 잠시 뒤 결과가 바뀝니다." if accepted
            else "방금 점검을 요청했습니다. 잠시 뒤 결과를 확인하세요."}


class HardwareTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: Literal["buzzer", "lamp"]


@hardware_router.post("/lamp/identify")
def host_lamp_identify(
    body: LampIdentifyRequest,
    auth: AuthContext = Depends(operator),
    svc: CoreServicesLike = Depends(get_services),
    quiet: Annotated[bool, Query()] = False,
):
    """Ask the sole face owner for a short visual challenge; no motion or identity claim.
    D-596: ``?quiet=true`` (Fleet's automatic requests) blinks without the call chirp."""
    color = body.color or _identify_color(svc)
    if color is None:
        raise ApiError("IDENTIFY_COLOR_UNSET", 409, "이 로봇의 식별 색이 설정되지 않았습니다")
    try:
        request_id = svc.host_files.identify(svc, color=color, quiet=quiet, by=auth.token_id)
    except svc.host_files.Error as exc:
        raise ApiError(exc.code, 429 if exc.code == "HW_TEST_COOLDOWN" else 503, str(exc)) from exc
    return {"accepted": True, "request_id": request_id, "color": color,
            "state": "pending_visual_confirmation"}


@hardware_router.get("/lamp/identify/{request_id}")
def host_lamp_identify_result(
    request_id: str,
    _auth: AuthContext = Depends(operator),
    svc: CoreServicesLike = Depends(get_services),
):
    """D-596 rev 2026-10-10: did rosy-face show the blink or refuse it (and why)?

    ``shown`` means the lamp blinked, not that a camera saw it. ``refused`` carries rosy-face's
    reason (CAUTION_ACTIVE, ESTOP, ...), or the bare hw-test state from a payload before it."""
    try:
        result, expired = svc.host_files.identify_result(svc, request_id)
    except svc.host_files.Error as exc:
        raise ApiError(exc.code, 404, str(exc)) from exc
    if result is not None and result["request_id"] == request_id:
        if result["state"] == "done":
            return {"request_id": request_id, "state": "shown", "reason": None, "detail": result["detail"]}
        return {"request_id": request_id, "state": "refused",
                "reason": result["reason"] or result["state"].upper(), "detail": result["detail"]}
    return {"request_id": request_id, "state": "expired" if expired else "pending", "reason": None, "detail": None}


#: D-472 4: colours lamp_pattern can show for an identity blink (amber = the ADR's orange).
LAMP_IDENTIFY_COLORS = ("blue", "amber")
#: D-472 4 default per robot (config, not wire schema); CORE config ``lamp_identify.color`` overrides it.
#: D-562 renumbers 9dfk rosy_26 -> rosy_41 and 8kcn rosy_60 -> rosy_40; the old ids stay until both are renumbered.
LAMP_IDENTIFY_DEFAULT_COLORS = {"rosy_41": "blue", "rosy_40": "amber", "rosy_26": "blue", "rosy_60": "amber"}


def _identify_color(svc: CoreServicesLike):
    """CORE config ``lamp_identify.color``, else the D-472 4 default for this robot id; None when neither."""
    configured = ((getattr(svc, "config", None) or {}).get("lamp_identify") or {}).get("color")
    if configured is not None:
        return configured if configured in LAMP_IDENTIFY_COLORS else None
    identity = getattr(svc, "identity", None)
    return LAMP_IDENTIFY_DEFAULT_COLORS.get(getattr(identity, "robot_id", None))


class HardwareConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: Literal["buzzer", "lamp"]
    observed: StrictBool


@hardware_router.post("/hardware/test")
def host_hardware_test(
    body: HardwareTestRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    """부저를 한 번 울리거나 램프를 한 번 켠다(D-247 6). CORE는 요청 파일만 쓰고 장치는 root가 다룬다."""
    try:
        request_id = svc.host_files.test_hardware(svc, device=body.device, by=auth.token_id)
    except svc.host_files.Error as exc:
        raise ApiError(exc.code, 429 if exc.code == "HW_TEST_COOLDOWN" else 503, str(exc)) from exc
    what = "부저를 울립니다" if body.device == "buzzer" else "램프를 켭니다"
    return {"accepted": True, "request_id": request_id, "device": body.device,
            "detail": f"{what}. 들렸는지·보였는지 확인해 주세요."}


@hardware_router.post("/hardware/confirm")
def host_hardware_confirm(
    body: HardwareConfirmRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    """관리자가 들림·보임을 기록한다(D-247 6). 누가 언제 확인했는지 CORE 상태 디렉터리에 남는다.

    답은 방금 끝난 그 장치의 시험에 대한 것이어야 한다: rosy-hw-test 가 같은 장치를
    `done` 으로 5분 안에 끝낸 결과가 없으면 409 ``HW_CONFIRM_NO_TEST``. 울리지 않은
    부저를 "들림" 으로 기록하지 않기 위해서다.
    """
    try:
        entry = svc.host_files.confirm_hardware(svc, device=body.device, observed=body.observed,
                                               by=auth.token_id, label=auth.label)
    except svc.host_files.Error as exc:
        raise ApiError(exc.code, 409 if exc.code == "HW_CONFIRM_NO_TEST" else 503, str(exc)) from exc
    return {"recorded": True, "device": body.device, **entry}
