"""core_api_web.api.v1.robot — 상태·포즈·센서 조회와 PWR-001 절전 모드."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core_api_web.api.v1.common import operator, viewer
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_common.protocol.schemas import PowerMode


robot_router = APIRouter(prefix="/api/v1/robot", tags=["robot"])


@robot_router.get("/state")
def robot_state(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return svc.state.snapshot().model_dump()


@robot_router.get("/pose")
def robot_pose(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    snap = svc.state.snapshot()
    return snap.pose.model_dump()


@robot_router.get("/battery")
def robot_battery(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    snap = svc.state.snapshot()
    return snap.battery.model_dump()


@robot_router.get("/velocity")
def robot_velocity(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    snap = svc.state.snapshot()
    return snap.velocity.model_dump()

sensors_router = APIRouter(prefix="/api/v1/sensors", tags=["sensors"])


@sensors_router.get("")
def list_sensors(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return {"sensors": svc.state.get_sensors()}


@sensors_router.get("/{sensor_type}")
def sensor_detail(sensor_type: str, _: AuthContext = Depends(viewer),
                  svc: CoreServicesLike = Depends(get_services)):
    data = svc.state.get_sensor(sensor_type)
    if data is None:
        raise ApiError("NOT_FOUND", 404, f"sensor '{sensor_type}' has no data yet")
    return data

power_router = APIRouter(prefix="/api/v1/power", tags=["power"])


class PowerModeRequest(BaseModel):
    mode: PowerMode


@power_router.get("")
def power_status(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """PWR-001: 현재 절전 모드·프레즌스·샘플링 주기."""
    return svc.power.status().model_dump()


@power_router.post("/wake")
def power_wake(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    """PWR-004: 원격 웨이크 — 로봇 앞에 서지 않고 정보 화면을 띄운다."""
    svc.power.wake("api")
    svc.state.set_power(svc.power.status())
    return svc.power.status().model_dump()


@power_router.post("/mode")
def power_set_mode(body: PowerModeRequest, auth: AuthContext = Depends(operator),
                   svc: CoreServicesLike = Depends(get_services)):
    """운영자 강제 전환. 활동이 감지되면 정책이 다시 ACTIVE로 되돌린다."""
    svc.power.request_mode(body.mode, source=f"api:{auth.role}")
    svc.state.set_power(svc.power.status())
    return svc.power.status().model_dump()
