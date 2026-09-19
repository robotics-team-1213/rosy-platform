"""core_api_web.api.v1.safety — SAF-001 E-Stop, SAF-004 속도 한계, SAF-005 배터리 정책."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from core_api_web.api.v1.common import admin, viewer
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_features.command.arbitration import Mode
from core_common.config import ConfigError, patch_local_config


safety_router = APIRouter(prefix="/api/v1/safety", tags=["safety"])


@safety_router.post("/stop")
def safety_stop(auth: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    svc.modes.transition(Mode.EMERGENCY)
    svc.safety.trigger_estop(f"api:{auth.role}")
    svc.state.set_estop(True)
    return {"estop": True}


@safety_router.post("/release")
def safety_release(auth: AuthContext = Depends(admin), svc: CoreServicesLike = Depends(get_services)):
    ok_mode, reason = svc.modes.release_emergency()
    if not ok_mode:
        raise ApiError("MODE_CONFLICT", 409, reason)
    svc.safety.release(by=f"api:{auth.role}")
    svc.state.set_estop(False)
    return {"estop": False}


_FLEET_LOSS_POLICIES = {"STOP", "HOLD", "RETURN_HOME", "CONTINUE"}
_CRITICAL_POLICIES = {"RETURN_HOME", "STOP"}


def _safety_payload(svc: CoreServicesLike) -> dict:
    battery = svc.safety.battery_policy
    deep = getattr(getattr(svc.battery, "_cfg", None), "deep_percent", 5.0)
    return {
        "estop": svc.safety.estop,
        "source": svc.safety.estop_source,
        "fleet_loss_policy": svc.safety.fleet_loss_policy,
        "limits": {
            # 활동 상한이 걸려 있으면 지금 실제로 적용되는 값이 이것이다.
            "session_linear": svc.safety.session_linear,
            "max_linear": svc.safety.limits.max_linear,
            "max_angular": svc.safety.limits.max_angular,
            "manual_linear": svc.safety.limits.manual_linear,
            "manual_angular": svc.safety.limits.manual_angular,
        },
        "battery": {
            "warning_percent": battery.warning_percent,
            "critical_percent": battery.critical_percent,
            "deep_percent": deep,
            "critical_policy": battery.critical_action,
        },
    }


@safety_router.get("/state")
def safety_state(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return _safety_payload(svc)


class LimitsRequest(BaseModel):
    manual_linear: float | None = Field(default=None, ge=0)
    manual_angular: float | None = Field(default=None, ge=0)
    fleet_loss_policy: str | None = None
    battery_warning_percent: float | None = Field(default=None, gt=0, le=100)
    battery_critical_percent: float | None = Field(default=None, gt=0, le=100)
    battery_deep_percent: float | None = Field(default=None, gt=0, le=100)
    battery_critical_policy: str | None = None

    @field_validator(
        "manual_linear", "manual_angular",
        "battery_warning_percent", "battery_critical_percent", "battery_deep_percent",
    )
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("must be a finite number")
        return value


def _apply_safety_patch(svc: CoreServicesLike, patch: dict) -> None:
    if "manual_linear" in patch:
        svc.safety.limits.manual_linear = patch["manual_linear"]
    if "manual_angular" in patch:
        svc.safety.limits.manual_angular = patch["manual_angular"]
    if "fleet_loss_policy" in patch:
        svc.safety.fleet_loss_policy = patch["fleet_loss_policy"]
    if "battery_warning_percent" in patch:
        svc.safety.battery_policy.warning_percent = patch["battery_warning_percent"]
    if "battery_critical_percent" in patch:
        svc.safety.battery_policy.critical_percent = patch["battery_critical_percent"]
    if "battery_critical_policy" in patch:
        svc.safety.battery_policy.critical_action = patch["battery_critical_policy"]
    if any(key.startswith("battery_") and key.endswith("_percent") for key in patch):
        svc.battery.apply_thresholds(
            warning_percent=patch.get("battery_warning_percent"),
            critical_percent=patch.get("battery_critical_percent"),
            deep_percent=patch.get("battery_deep_percent"),
        )


@safety_router.put("/limits")
def safety_limits(body: LimitsRequest, auth: AuthContext = Depends(admin),
                  svc: CoreServicesLike = Depends(get_services)):
    patch_safety: dict = {}
    if body.manual_linear is not None:
        patch_safety["manual_linear"] = min(body.manual_linear, svc.safety.limits.max_linear)
    if body.manual_angular is not None:
        patch_safety["manual_angular"] = min(body.manual_angular, svc.safety.limits.max_angular)
    if body.fleet_loss_policy is not None:
        policy = body.fleet_loss_policy
        if policy == "CONTINUE_CURRENT_NAVIGATION":
            policy = "CONTINUE"
        if policy not in _FLEET_LOSS_POLICIES:
            raise ApiError("VALIDATION_ERROR", 400, "unknown fleet_loss_policy")
        patch_safety["fleet_loss_policy"] = policy
    if body.battery_critical_policy is not None:
        if body.battery_critical_policy not in _CRITICAL_POLICIES:
            raise ApiError("VALIDATION_ERROR", 400, "unknown battery_critical_policy")
        patch_safety["battery_critical_policy"] = body.battery_critical_policy
    if body.battery_warning_percent is not None:
        patch_safety["battery_warning_percent"] = body.battery_warning_percent
    if body.battery_critical_percent is not None:
        patch_safety["battery_critical_percent"] = body.battery_critical_percent
    if body.battery_deep_percent is not None:
        patch_safety["battery_deep_percent"] = body.battery_deep_percent
    warning = patch_safety.get(
        "battery_warning_percent", svc.safety.battery_policy.warning_percent)
    critical = patch_safety.get(
        "battery_critical_percent", svc.safety.battery_policy.critical_percent)
    deep = patch_safety.get(
        "battery_deep_percent", getattr(getattr(svc.battery, "_cfg", None), "deep_percent", 5.0))
    if not (0 < float(deep) < float(critical) < float(warning) <= 100):
        raise ApiError(
            "VALIDATION_ERROR", 400,
            "battery thresholds must satisfy 0 < deep < critical < warning <= 100",
        )
    if not patch_safety:
        return _safety_payload(svc)
    try:
        patch_local_config({"safety": patch_safety})
    except (ConfigError, OSError) as exc:
        raise ApiError("INTERNAL_ERROR", 500, f"failed to persist safety.limits: {exc}")
    _apply_safety_patch(svc, patch_safety)
    svc.config.setdefault("safety", {}).update(patch_safety)
    svc.events.publish("config.changed", source="api", data={"key": "safety.limits"})
    return _safety_payload(svc)
