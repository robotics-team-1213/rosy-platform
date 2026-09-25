"""core_api_web.api.v1.host — Host Agent 릴레이 (네트워크·릴리스·커미셔닝)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core_api_web.api.v1.common import admin, viewer
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.host_agent_client import HostAgentClient


# --- Network / Release / Commissioning (WP-5, 설계 §10.2/§10.3) --------------
#
# CORE 는 호스트 권한이 없으므로 이 세 화면의 데이터는 전부 Host Agent 에서 온다.
# 에이전트가 없는 상태(개발 장비, 서비스 미기동)는 예외가 아니라 정상적으로
# 있을 수 있는 상태이며, 그때 **없는 값을 그럴듯하게 채우지 않는다.** 빈 칸은
# 운영자에게 "이상 없음" 으로 읽히고, 지어낸 값은 사실로 읽힌다.

host_router = APIRouter(prefix="/api/v1/host", tags=["host"])


def _agent(svc: CoreServicesLike) -> HostAgentClient:
    host_cfg = (svc.config or {}).get("host_agent", {})
    return HostAgentClient(
        socket_path=host_cfg.get("socket_path", "/run/rosy/host-agent.sock"),
        timeout_s=float(host_cfg.get("timeout_s", 5.0)),
    )


def _relay(reply, *, absent_detail: str) -> dict:
    """Turn an agent reply into a card payload that cannot mislead.

    ``available`` is the field the dashboard keys on. When it is false the
    card shows why instead of showing empty fields — an unreachable agent and
    a healthy device with nothing to report look identical otherwise.
    """
    if not reply.reachable:
        return {
            "available": False,
            "code": reply.code,
            "detail": reply.detail or absent_detail,
            "recovery": reply.recovery,
            "data": None,
        }
    return {
        "available": True,
        "ok": reply.ok,
        "code": reply.code,
        "detail": reply.detail,
        "recovery": reply.recovery,
        "data": reply.data,
    }


@host_router.get("/network")
def host_network(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """현재 네트워크 모드와 도달성. SSID 는 표시하되 secret 은 절대 싣지 않는다."""
    reply = _agent(svc).request("network.status", role="viewer")
    return _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 네트워크 상태를 알 수 없습니다.")


class NetworkApplyRequest(BaseModel):
    profile_id: str = Field(min_length=1, max_length=64)
    confirmed: bool = False
    idempotency_key: str | None = None


class NetworkModeRequest(BaseModel):
    mode: str = Field(min_length=1, max_length=32)
    confirmed: bool = False
    idempotency_key: str | None = None


class NetworkConnectRequest(BaseModel):
    ssid: str = Field(min_length=1, max_length=32)
    psk: str = Field(min_length=8, max_length=63, repr=False)
    confirmed: bool = False
    idempotency_key: str | None = None


@host_router.post("/network/apply")
def host_network_apply(
    body: NetworkApplyRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    """Switch to a registered NetworkManager profile. PSK never enters CORE."""
    reply = _agent(svc).request(
        "network.apply_profile",
        role="administrator",
        user_id=auth.token_id,
        confirmed=body.confirmed,
        params={"profile_id": body.profile_id},
        idempotency_key=body.idempotency_key,
    )
    return _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 네트워크 프로파일을 바꾸지 못했습니다.")


@host_router.post("/network/mode")
def host_network_mode(
    body: NetworkModeRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    """SITE_STA (AP off) or RELAY_AP_STA (AP on). CORE never calls nmcli (D-22)."""
    reply = _agent(svc).request(
        "network.set_mode",
        role="administrator",
        user_id=auth.token_id,
        confirmed=body.confirmed,
        params={"mode": body.mode},
        idempotency_key=body.idempotency_key,
    )
    return _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 네트워크 모드를 바꾸지 못했습니다.")


def _without_secrets(payload: dict) -> dict:
    data = payload.get("data")
    if not isinstance(data, dict):
        return payload
    payload["data"] = {
        key: value
        for key, value in data.items()
        if not str(key).lower() in {"psk", "passphrase", "password"}
    }
    return payload


@host_router.post("/network/connect")
def host_network_connect(
    body: NetworkConnectRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    """Join a site SSID. PSK transits once and is never returned or stored."""
    reply = _agent(svc).request(
        "network.connect",
        role="administrator",
        user_id=auth.token_id,
        confirmed=body.confirmed,
        params={"ssid": body.ssid, "psk": body.psk},
        idempotency_key=body.idempotency_key,
    )
    return _without_secrets(
        _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 Wi-Fi에 연결하지 못했습니다.")
    )


@host_router.get("/release")
def host_release(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """current / previous / staged 와 마지막 실패 사유."""
    reply = _agent(svc).request("release.status", role="viewer")
    return _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 릴리스 상태를 알 수 없습니다.")


class HostActionRequest(BaseModel):
    """파괴적 명령의 공통 입력.

    `confirmed` 는 대시보드의 재확인이 실제로 있었음을 뜻한다. 기본값이 False 인
    것이 핵심이다 — 빠뜨리면 실행되지 않고 거부된다.
    """

    confirmed: bool = False
    idempotency_key: str | None = None


class ReleaseInstallRequest(HostActionRequest):
    release_id: str = Field(min_length=1, max_length=64)


@host_router.post("/release/install")
def host_release_install(
    body: ReleaseInstallRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    reply = _agent(svc).request(
        "release.install",
        role="administrator",
        user_id=auth.token_id,
        confirmed=body.confirmed,
        params={"release_id": body.release_id},
        idempotency_key=body.idempotency_key,
    )
    return _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 설치를 시작하지 못했습니다.")


@host_router.post("/release/rollback")
def host_release_rollback(
    body: HostActionRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    reply = _agent(svc).request(
        "release.rollback",
        role="administrator",
        user_id=auth.token_id,
        confirmed=body.confirmed,
        idempotency_key=body.idempotency_key,
    )
    return _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 롤백을 시작하지 못했습니다.")


@host_router.post("/release/clear-hold")
def host_release_clear_hold(
    body: HostActionRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    """RECOVERY HOLD 해제. 홀드 중에는 install 이 거부되므로 별도의 의도적 행위다."""
    reply = _agent(svc).request(
        "release.clear_hold",
        role="administrator",
        user_id=auth.token_id,
        confirmed=body.confirmed,
        idempotency_key=body.idempotency_key,
    )
    return _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 홀드를 해제하지 못했습니다.")


@host_router.post("/reboot")
def host_reboot(
    body: HostActionRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    """Relay Host Agent system.reboot. CORE does not call reboot itself (D-22)."""
    reply = _agent(svc).request(
        "system.reboot",
        role="administrator",
        user_id=auth.token_id,
        confirmed=body.confirmed,
        idempotency_key=body.idempotency_key,
    )
    return _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 재부팅하지 못했습니다.")


@host_router.get("/commissioning")
def host_commissioning(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """runtime mode 와 hardware 재승인 사유.

    runtime mode 는 CORE 가 스스로 안다 — 자기가 무엇으로 기동했는지는 호스트에
    묻지 않아도 된다. 그래서 이 카드는 에이전트가 없어도 절반은 정직하게 채운다.
    """
    mode = (svc.config or {}).get("runtime", {}).get("mode", "core")
    if mode == "core":
        detail = (
            "UART·모터 미승인 상태입니다. 이것은 정상이며, 승격은 별도 현장 안전 "
            "절차를 따릅니다."
        )
    elif mode == "motor":
        detail = (
            "모터 벤치 모드입니다. LiDAR는 아직 꺼져 있으며 hardware 모드는 "
            "별도 수락이 필요합니다. 배터리 ADC, IMU, SLAM, Fleet는 없습니다."
        )
    else:
        detail = (
            f"현재 {mode} 모드로 기동되어 있습니다. 모터와 LiDAR와 Nav2는 이 "
            "슬라이스에 있습니다. 배터리 전압(ADC), IMU, SLAM, Fleet는 "
            "띄우지 않습니다."
        )
    return {
        "runtime_mode": mode,
        "motor_hold": mode == "core",
        "lidar_hold": mode != "hardware",
        "battery_hold": True,
        "imu_hold": True,
        "slam_hold": True,
        "fleet_hold": True,
        "detail": detail,
    }
