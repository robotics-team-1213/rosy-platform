"""core_api_web.api.v1.safety — SAF-001 E-Stop, SAF-003 Fleet 상실, SAF-004 속도 한계, SAF-005 배터리 정책."""

from __future__ import annotations

import logging
import math

import hmac

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from core_api_web.api.v1 import auth as login
from core_api_web.api.v1.common import admin, battery_health, operator, require_calibration_owner, viewer
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_api_web.api.deps import Mode
from core_common.config import ConfigError, patch_local_config


logger = logging.getLogger(__name__)

safety_router = APIRouter(prefix="/api/v1/safety", tags=["safety"])


@safety_router.post("/stop")
def safety_stop(auth: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    captured = []
    for owner_name in ("nav", "docking", "swarm", "command"):
        try:
            owner = getattr(svc, owner_name)
            operation = owner.capture_native_operation()
            if operation is not None:
                captured.append((owner, operation))
        except Exception:
            # Optional evidence must never prevent the existing safety path.
            captured.clear()
            break
    # Latch first: the mode change runs listeners (docking abort, ...), and
    # nothing they do may leave EMERGENCY without the latch behind it.
    svc.safety.trigger_estop(f"api:{auth.role}")
    svc.modes.transition(Mode.EMERGENCY)
    svc.state.set_estop(True)
    operations = []
    for owner, operation in captured:
        try:
            current = owner.capture_native_operation(operation.run_id)
            if current is not None and (current.run_id, current.boot_id, current.kind) == (
                    operation.run_id, operation.boot_id, operation.kind):
                operation = current
        except Exception:
            pass  # Keep the exact pending receipt when its later evidence is unavailable.
        operations.append(operation.model_dump(mode="json"))
    return {"estop": True, "operations": operations}


@safety_router.post("/release")
def safety_release(auth: AuthContext = Depends(admin), svc: CoreServicesLike = Depends(get_services)):
    return _release(svc, f"api:{auth.role}")


def _release(svc: CoreServicesLike, by: str) -> dict:
    ok_mode, reason = svc.modes.release_emergency()
    # Desync recovery: a latch left in IDLE (before v1.196, POST /mode IDLE left
    # EMERGENCY with the latch set) is still the administrator's to release.
    if not ok_mode:
        if not (svc.safety.estop and svc.modes.mode is Mode.IDLE):
            raise ApiError("MODE_CONFLICT", 409, reason)
        svc.docking.on_estop()  # D-502, as the EMERGENCY exit listener does
    svc.safety.release(by=by)
    svc.state.set_estop(False)
    return {"estop": False}


class ReleaseCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


def _match_release(state: "login.PairingState", code: str) -> tuple[bool, bool]:
    """(matched, burned) against root's live release code; a miss counts toward burning it."""
    physical = state.physical_code(roles={login.RELEASE_ROLE})
    if physical is None:
        return False, False
    with login.SCRYPT_SLOTS:
        presented = login.scrypt_digest(code, physical["salt"])
    code_id = physical["code_id"]
    with state.lock:
        if code_id in state.spent:
            return False, False
        if hmac.compare_digest(presented, physical["digest"]):
            state.spent.add(code_id)
            matched, burned, attempts = True, False, None
        else:
            attempts = state.failures[code_id] = state.failures.get(code_id, 0) + 1
            matched, burned = False, attempts >= login.MAX_WRONG_ATTEMPTS
            if burned:
                state.spent.add(code_id)
    state.signal_root(code_id, "used" if matched else "burned" if burned else "failing",
                      None if matched or burned else attempts)
    return matched, burned


@safety_router.post("/release-code")
async def safety_release_code(body: ReleaseCodeRequest, request: Request,
                              auth: AuthContext = Depends(operator),
                              svc: CoreServicesLike = Depends(get_services)):
    """v1.337: release with the one-time code the robot's own screen shows while latched.

    The code proves a person read this robot's LCD; it releases once and logs nobody in.
    The administrator release above is unchanged.
    """
    host = request.client.host if request.client else ""
    if not login.client_allowed(host):
        raise ApiError("FORBIDDEN", 403, "release codes are accepted only from the robot LAN")
    if not svc.safety.estop:
        raise ApiError("NOT_LATCHED", 409, "the robot is not in emergency stop; the code was not used")
    if login._pairing(request).admit(host) is not None:
        raise ApiError("RATE_LIMITED", 429, "too many release attempts")
    code = login.normalize_code(body.code)
    if not login.CODE_RE.fullmatch(code):
        raise ApiError("VALIDATION_ERROR", 400, "a release code is 8 characters like ABCD-EFGH")
    matched, burned = await run_in_threadpool(_match_release, login._pairing(request), code)
    if not matched:
        raise ApiError("UNAUTHORIZED", 401, "invalid or expired release code",
                       detail={"burned": True} if burned else None)
    return _release(svc, f"screen_code:{auth.role}")


_FLEET_LOSS_POLICIES = {"STOP", "HOLD", "RETURN_HOME", "CONTINUE"}
RETURN_HOME_WARNING = (
    "RETURN_HOME on Fleet loss: every robot with this policy drives to __home__ at the same "
    "time when the site Fleet goes down, without Fleet traffic control (D-419). STOP is the "
    "safe default.")
_CRITICAL_POLICIES = {"RETURN_HOME", "STOP"}


def _safety_payload(svc: CoreServicesLike) -> dict:
    battery = svc.safety.battery_policy
    deep = getattr(getattr(svc.battery, "_cfg", None), "deep_percent", 5.0)
    fleet_loss = svc.fleet_loss
    health = battery_health(svc)
    return {
        "estop": svc.safety.estop,
        "source": svc.safety.estop_source,
        "fleet_loss_policy": svc.safety.fleet_loss_policy,
        # SAF-003 (D-419, v1.86): FleetAgent link and the policy applied in this outage.
        "fleet_link": fleet_loss.status() if fleet_loss is not None else None,
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
            # v1.120: what the policy is judging now. A latched battery stop with
            # evidence "fresh" and level "ok" is the operator's cue to release.
            **{key: health[key] for key in ("evidence", "sample_age_s", "level", "percent")},
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
    # D-321 addendum: the owner calibrates against these limits; nobody else moves them.
    require_calibration_owner(svc, auth, "safety limits change")
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
    svc.events.publish("config.changed", severity="warning", source="api",
                       data={"key": "safety.limits"})
    payload = _safety_payload(svc)
    if patch_safety.get("fleet_loss_policy") == "RETURN_HOME":
        # D-419: accepted, but every paired robot on this policy drives home at once when
        # the site Fleet goes down, with no Fleet traffic control. Say so; do not refuse.
        logger.warning("fleet_loss_policy set to RETURN_HOME by %s: %s", auth.role,
                       RETURN_HOME_WARNING)
        payload["warning"] = RETURN_HOME_WARNING
    return payload
