"""core_api_web.api.v1.system — IDN-003 신원, CAP-001 capability, SEC-101 토큰, 호스트 런타임, inventory."""

from __future__ import annotations

import hmac
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core_api_web.api.v1.common import admin, viewer
from core_api_web.api.deps import (
    AuthContext,
    CoreServicesLike,
    MAX_TOKEN_LENGTH,
    MIN_TOKEN_LENGTH,
    ROLE_RANK,
    auth_entries,
    generate_token,
    get_services,
    is_durable_admin,
    is_expired,
    new_token_record,
    persist_token_records,
    public_token_records,
    token_digest,
)
from core_api_web.api.errors import ApiError
from core_common.config import ConfigError, patch_local_config
from core_common.domain.capabilities import hardware_runtime_reason, withhold_hardware_flags
from core_common.identity import validate_robot_id, validate_robot_name


system_router = APIRouter(prefix="/api/v1/system", tags=["system"])


@system_router.get("/info")
def system_info(auth: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    # `caller_role` lets the dashboard gate admin panels without probing an
    # admin-only route and eating a 403 for every viewer (v1.18 additive).
    return {**svc.identity.info(), "caller_role": auth.role}


class IdentityRequest(BaseModel):
    robot_id: str | None = None
    robot_name: str | None = None


@system_router.put("/info")
def update_system_info(body: IdentityRequest, _: AuthContext = Depends(admin),
                       svc: CoreServicesLike = Depends(get_services)):
    patch_robot: dict[str, str] = {}
    try:
        if body.robot_id is not None:
            requested_id = validate_robot_id(body.robot_id)
            if requested_id != svc.identity.robot_id:
                raise ApiError(
                    "IDENTITY_LOCKED", 409,
                    "robot_id is derived from the robot number",
                )
        if body.robot_name is not None:
            patch_robot["name"] = validate_robot_name(body.robot_name)
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", 400, str(exc))
    if not patch_robot:
        return svc.identity.info()
    try:
        patch_local_config({"robot": patch_robot})
    except (ConfigError, OSError) as exc:
        raise ApiError("INTERNAL_ERROR", 500, f"failed to persist robot identity: {exc}")
    if "name" in patch_robot:
        svc.identity.robot_name = patch_robot["name"]
        svc.config.setdefault("robot", {})["name"] = patch_robot["name"]
    svc.events.publish("config.changed", severity="warning", source="api",
                       data={"key": "robot.identity"})
    return svc.identity.info()


@system_router.get("/tokens")
def list_tokens(auth: AuthContext = Depends(admin), svc: CoreServicesLike = Depends(get_services)):
    return {"tokens": public_token_records(svc.config, current_id=auth.token_id)}


class TokenRequest(BaseModel):
    """`token` 을 비우면 서버가 만들어 응답에 한 번만 싣는다."""

    token: str | None = Field(default=None, min_length=MIN_TOKEN_LENGTH,
                              max_length=MAX_TOKEN_LENGTH)
    role: str
    label: str = Field(default="", max_length=64)


@system_router.post("/tokens", status_code=201)
def add_token(body: TokenRequest, _: AuthContext = Depends(admin),
              svc: CoreServicesLike = Depends(get_services)):
    role = body.role.strip()
    if role not in ROLE_RANK:
        raise ApiError("VALIDATION_ERROR", 400, "role must be viewer, operator or administrator")
    generated = body.token is None
    token = generate_token() if generated else body.token.strip()
    if len(token) < MIN_TOKEN_LENGTH:
        raise ApiError("VALIDATION_ERROR", 400,
                       f"token must be at least {MIN_TOKEN_LENGTH} characters")

    records = auth_entries(svc.config)
    digest = token_digest(token)
    if any(hmac.compare_digest(digest, item["digest"]) for item in records):
        raise ApiError("VALIDATION_ERROR", 409, "token already exists")

    record = new_token_record(token, role, body.label.strip())
    records.append(record)
    persist_token_records(svc, records)
    svc.events.publish(
        "config.changed", severity="warning", source="api",
        data={"key": "auth.tokens", "id": record["id"], "role": role},
    )
    created = {"id": record["id"], "role": role, "label": record["label"],
               "created_at": record["created_at"], "expires_at": None, "source": record["source"]}
    if generated:
        # 원문이 나가는 유일한 지점이다. 저장도 재조회도 되지 않는다.
        created["token"] = token
    return created


@system_router.delete("/tokens/{token_id}", status_code=204)
def delete_token(token_id: str, auth: AuthContext = Depends(admin),
                 svc: CoreServicesLike = Depends(get_services)):
    if auth.token_id == token_id:
        raise ApiError("VALIDATION_ERROR", 400, "cannot delete the token in use")
    records = auth_entries(svc.config)
    target = next((item for item in records if item["id"] == token_id), None)
    if target is None:
        raise ApiError("NOT_FOUND", 404, "token id not found")
    remaining = [item for item in records if item["id"] != token_id]
    # D-193 5: an expiring administrator (a paired browser) cannot hold the
    # robot's administration on its own; only non-expiring ones count.
    if is_durable_admin(target) and not any(is_durable_admin(item) for item in remaining):
        raise ApiError("VALIDATION_ERROR", 409, "cannot delete the last non-expiring administrator token")
    persist_token_records(svc, remaining)
    svc.events.publish(
        "config.changed", severity="warning", source="api",
        data={"key": "auth.tokens", "id": token_id, "deleted": True},
    )


class TokenLabelRequest(BaseModel):
    label: str = Field(max_length=64)


@system_router.patch("/tokens/{token_id}")
def relabel_token(token_id: str, body: TokenLabelRequest, auth: AuthContext = Depends(admin),
                  svc: CoreServicesLike = Depends(get_services)):
    records = auth_entries(svc.config)
    target = next((item for item in records if item["id"] == token_id), None)
    if target is None or is_expired(target):
        raise ApiError("NOT_FOUND", 404, "token id not found")
    target["label"] = body.label.strip()
    persist_token_records(svc, records)
    svc.events.publish(
        "config.changed", severity="warning", source="api",
        data={"key": "auth.tokens", "id": token_id},
    )
    return next(item for item in public_token_records(svc.config, current_id=auth.token_id)
                if item["id"] == token_id)


@system_router.get("/capabilities")
def capabilities(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    data = svc.capability.to_dict()
    reason = hardware_runtime_reason(svc.config, svc.state)
    return withhold_hardware_flags(data, reason) if reason else data


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@system_router.get("/inventory")
def system_inventory(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return _jsonable(svc.inventory())


@system_router.get("/runtime")
def system_runtime(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return svc.runtime_probe.snapshot()


class CycloneApplyRequest(BaseModel):
    confirmed: bool = False
    idempotency_key: str | None = None


@system_router.post("/dds/cyclone")
def apply_cyclone_and_reboot(
    body: CycloneApplyRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    """Persist Cyclone intent then ask Host Agent to reboot (D-123)."""
    if not body.confirmed:
        raise ApiError("CONFIRMATION_REQUIRED", 400, "재부팅 확인이 필요합니다")
    from core_common.rmw import REQUIRED_RMW, cyclone_overlay_patch

    try:
        patch_local_config(cyclone_overlay_patch())
    except (ConfigError, OSError) as exc:
        raise ApiError("INTERNAL_ERROR", 500, f"failed to persist Cyclone intent: {exc}")
    from core_api_web.api.v1.host import _agent, _relay

    reply = _agent(svc).request(
        "system.reboot",
        role="administrator",
        user_id=auth.token_id,
        confirmed=True,
        idempotency_key=body.idempotency_key,
    )
    reboot = _relay(
        reply,
        absent_detail=(
            "오버레이에 Cyclone을 저장했습니다. Host Agent가 없어 재부팅하지 못했습니다. "
            "systemctl restart rosy-runtime.service 로 런타임을 다시 띄우세요."
        ),
    )
    svc.events.publish("config.changed", severity="warning", source="api",
                       data={"key": "dds.rmw"})
    return {"persisted": True, "rmw": REQUIRED_RMW, "reboot": reboot}
