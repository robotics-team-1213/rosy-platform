"""Read-only per-motor observations from the existing native bus owner."""
from fastapi import APIRouter, Depends

from core_api_web.api.deps import AuthContext
from core_api_web.api.v1.common import viewer
from core_api_web.api.motor_health import read_motor_health
from core_common.protocol.motor_health import MotorHealthResponse

motors_router = APIRouter(prefix='/api/v1/motors', tags=['motors'])


@motors_router.get('/health', response_model=MotorHealthResponse)
def motor_health(_: AuthContext = Depends(viewer)):
    return read_motor_health()
