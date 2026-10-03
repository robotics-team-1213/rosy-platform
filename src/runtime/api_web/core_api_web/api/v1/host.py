"""core_api_web.api.v1.host — Host Agent 릴레이 (네트워크·릴리스·커미셔닝)와 장치 관측(D-247)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core_api_web.api.v1.common import admin, require_calibration_owner, viewer
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.host_agent_client import HostAgentClient, TIMEOUT, UNAVAILABLE
from core_common import face_screen, robot_state
from core_common.protocol.evidence import EvidenceState
from core_common.protocol.schemas import HostStatusEvidence
from . import host_hardware as _host_hardware


# --- Network / Release / Commissioning (WP-5, 설계 §10.2/§10.3) --------------
#
# CORE 는 호스트 권한이 없으므로 이 세 화면의 데이터는 전부 Host Agent 에서 온다.
# 에이전트가 없는 상태(개발 장비, 서비스 미기동)는 예외가 아니라 정상적으로
# 있을 수 있는 상태이며, 그때 **없는 값을 그럴듯하게 채우지 않는다.** 빈 칸은
# 운영자에게 "이상 없음" 으로 읽히고, 지어낸 값은 사실로 읽힌다.

host_router = APIRouter(prefix="/api/v1/host", tags=["host"])
host_router.include_router(_host_hardware.hardware_router)

# Keep the status summary built from the hardware module's validated readback.
_read_small_json = _host_hardware._read_small_json
_evidence_of = _host_hardware._evidence_of
_write_private = _host_hardware._write_private
host_hardware = _host_hardware.host_hardware
MAX_TEXT = _host_hardware.MAX_TEXT


def _agent(svc: CoreServicesLike) -> HostAgentClient:
    host_cfg = (svc.config or {}).get("host_agent", {})
    return HostAgentClient(
        socket_path=host_cfg.get("socket_path", "/run/rosy/host-agent.sock"),
        timeout_s=float(host_cfg.get("timeout_s", 5.0)),
    )


HOST_STATUS_STALE_AFTER_S = 15.0


def _status_evidence(reply) -> HostStatusEvidence:
    base = {"stale_after_s": HOST_STATUS_STALE_AFTER_S}
    if reply.code in {UNAVAILABLE, TIMEOUT}:
        return HostStatusEvidence(evidence=EvidenceState.DISCONNECTED,
                                  reason="Host Agent에 연결되지 않았거나 응답이 시간 안에 오지 않았습니다.", **base)
    if not reply.reachable or not reply.ok:
        return HostStatusEvidence(reason="Host Agent가 완전한 상태 조회 결과를 주지 않았습니다.", **base)
    try:
        observed = datetime.fromisoformat(reply.observed_at) if reply.observed_at else None
    except (TypeError, ValueError):
        observed = None
    if observed is None or observed.tzinfo is None or observed.utcoffset().total_seconds() != 0:
        return HostStatusEvidence(reason="Host Agent 원본 조회 완료 시각이 없습니다.", **base)
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    if age < 0:
        return HostStatusEvidence(reason="Host Agent 원본 시각이 CORE 시각보다 미래입니다.", **base)
    state = EvidenceState.DELAYED if age > HOST_STATUS_STALE_AFTER_S else EvidenceState.FRESH
    return HostStatusEvidence(evidence=state, observed_at=reply.observed_at,
                              age_s=round(age, 1),
                              reason="Host Agent 원본 조회가 지연되었습니다." if state is EvidenceState.DELAYED
                              else "Host Agent 원본 조회 완료 시각을 확인했습니다.", **base)


def _relay(reply, *, absent_detail: str, status_read: bool = False) -> dict:
    """Turn an agent reply into a card payload that cannot mislead.

    ``available`` is the field the dashboard keys on. When it is false the
    card shows why instead of showing empty fields — an unreachable agent and
    a healthy device with nothing to report look identical otherwise.
    """
    evidence = _status_evidence(reply) if status_read else None
    if not reply.reachable:
        payload = {
            "available": False,
            "code": reply.code,
            "detail": reply.detail or absent_detail,
            "recovery": reply.recovery,
            "data": None,
        }
    else:
        payload = {
            "available": True,
            "ok": reply.ok,
            "code": reply.code,
            "detail": reply.detail,
            "recovery": reply.recovery,
            "data": reply.data,
        }
    if evidence is not None:
        payload["evidence"] = evidence.model_dump(mode="json")
        if evidence.evidence in {EvidenceState.DISCONNECTED, EvidenceState.UNAVAILABLE}:
            payload["data"] = None
    return payload


@host_router.get("/network")
def host_network(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """현재 네트워크 모드와 도달성. SSID 는 표시하되 secret 은 절대 싣지 않는다."""
    reply = _agent(svc).request("network.status", role="viewer")
    return _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 네트워크 상태를 알 수 없습니다.",
                  status_read=True)


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
    return _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 릴리스 상태를 알 수 없습니다.",
                  status_read=True)


class HostActionRequest(BaseModel):
    """파괴적 명령의 공통 입력.

    `confirmed` 는 대시보드의 재확인이 실제로 있었음을 뜻한다. 기본값이 False 인
    것이 핵심이다 — 빠뜨리면 실행되지 않고 거부된다.
    """

    confirmed: bool = False
    idempotency_key: str | None = None
    # D-321 addendum: install/rollback/reboot restart CORE and end a running
    # calibration. Another token must say so explicitly to go ahead.
    override_calibration: bool = False


def _calibration_fence(svc: CoreServicesLike, auth: AuthContext, body: HostActionRequest,
                       action: str) -> None:
    if not body.override_calibration:
        require_calibration_owner(svc, auth, f"{action} (set override_calibration to end it)")


class ReleaseInstallRequest(HostActionRequest):
    release_id: str = Field(min_length=1, max_length=64)


@host_router.post("/release/install")
def host_release_install(
    body: ReleaseInstallRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    _calibration_fence(svc, auth, body, "release install")
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
    _calibration_fence(svc, auth, body, "release rollback")
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
    _calibration_fence(svc, auth, body, "reboot")
    reply = _agent(svc).request(
        "system.reboot",
        role="administrator",
        user_id=auth.token_id,
        confirmed=body.confirmed,
        idempotency_key=body.idempotency_key,
    )
    return _relay(reply, absent_detail="Host Agent 에 연결할 수 없어 재부팅하지 못했습니다.")


# D-247 7's sentences live in the D-260 rule table, which the boot display shares.
MOTION_REASON = robot_state.MOTION_REASON


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
        # D-247 7: why the robot cannot move, in words that are not a
        # permission message. Empty when the mode itself does not hold motion.
        "motion_reason": MOTION_REASON.get(mode, ""),
        "motor_hold": mode == "core",
        "lidar_hold": mode != "hardware",
        "battery_hold": True,
        "imu_hold": True,
        "slam_hold": True,
        "fleet_hold": True,
        "detail": detail,
    }


# --- D-260: one robot state for the operate view's summary line ---------------
#
# The same rule table (core_common.robot_state) the root-side boot display
# applies to the same files, so the LCD, the lamp, the buzzer and this line
# never disagree. CORE reads boot-status.json as strictly as hardware.json.

BOOT_STATUS_FILE = "/run/rosy-boot/boot-status.json"


def read_boot_status(path: str) -> Optional[dict[str, Optional[str]]]:
    """rosy-boot-status's stage and failed unit, or None when absent, unreadable or malformed."""
    data = _read_small_json(path)
    if not isinstance(data, dict):
        return None
    stage, failed_unit = data.get("stage"), data.get("failed_unit")
    if not isinstance(stage, str) or not stage or len(stage) > MAX_TEXT:
        return None
    if failed_unit is not None and (not isinstance(failed_unit, str) or len(failed_unit) > MAX_TEXT):
        return None
    return {"stage": stage, "failed_unit": failed_unit}


def _battery_reading(snapshot: Any) -> tuple[Optional[float], Optional[float]]:
    """(percent, voltage) from the state snapshot; a reading whose channel is not fresh is none."""
    battery = getattr(snapshot, "battery", None)
    percent, voltage = getattr(battery, "percent", None), getattr(battery, "voltage", None)
    judged = _evidence_of(snapshot, "battery")
    if judged is not None and judged != "fresh":
        return None, None
    number = (int, float)
    return (float(percent) if isinstance(percent, number) and not isinstance(percent, bool) else None,
            float(voltage) if isinstance(voltage, number) and not isinstance(voltage, bool) else None)


@host_router.get("/status-summary")
def host_status_summary(auth: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """운용 화면 요약줄(D-260 5): 로봇 상태 하나, 이유, 장치 요약, 배터리·온도, 할 일."""
    cfg = (svc.config or {}).get("hardware_probe", {}) or {}
    boot = read_boot_status(str(cfg.get("boot_status_path", BOOT_STATUS_FILE)))
    # CORE is answering, so a missing indicator file is not "booting": the stage
    # is taken as CORE_READY and the response says the file was not there.
    stage = boot["stage"] if boot else "CORE_READY"
    hardware = host_hardware(auth, svc)
    devices = hardware["devices"] if hardware.get("available") else []
    state = getattr(svc, "state", None)
    snapshot = state.snapshot() if state is not None and hasattr(state, "snapshot") else None
    percent, voltage = _battery_reading(snapshot)
    warning = _warning_percent(svc)
    mode = (svc.config or {}).get("runtime", {}).get("mode", robot_state.DEFAULT_RUNTIME_MODE)
    result = robot_state.evaluate(stage, devices, battery_percent=percent, battery_warning_percent=warning,
                                  runtime_mode=mode, failed_unit=boot["failed_unit"] if boot else None)
    probe = getattr(svc, "runtime_probe", None)
    temperature = probe.temperature() if probe is not None and hasattr(probe, "temperature") else None
    counts = robot_state.device_counts(devices)
    return {
        "state": result["state"],
        "label": result["label"],
        "reason": result["reason"],
        "state_line": robot_state.state_line(result),
        "motion_reason": result["motion_reason"],
        "runtime_mode": mode,
        "boot": {"available": boot is not None, "stage": boot["stage"] if boot else None},
        "devices": {"available": bool(hardware.get("available")), "stale": bool(hardware.get("stale")),
                    **counts},
        "battery": {"percent": percent, "voltage": voltage, "warning_percent": warning,
                    "low": robot_state.battery_low(percent, warning)},
        "temperature_c": temperature,
        "todos": [{key: item[key] for key in ("id", "text", "device") if key in item}
                  for item in result["todos"]],
    }


# D-260 M1: the boot display must evaluate the same inputs CORE does. It cannot
# read CORE's SAF-005 policy or the overlays (topic judgment, human answers), so
# CORE hands them over in its own runtime directory; root rosy-boot-status reads
# the file strictly and copies the values into boot-status.json.
STATUS_INPUTS_FILE = "/run/rosy/status-inputs.json"
STATUS_INPUTS_PERIOD_S = 10.0


def _warning_percent(svc: CoreServicesLike) -> float:
    policy = getattr(getattr(svc, "safety", None), "battery_policy", None)
    value = getattr(policy, "warning_percent", robot_state.BATTERY_WARNING_PERCENT)
    try:
        return float(value)
    except (TypeError, ValueError):
        return robot_state.BATTERY_WARNING_PERCENT


def _snapshot(svc: CoreServicesLike) -> Any:
    """One StateSnapshot (what GET /robot/state serves), or None without a state manager."""
    snapshot = getattr(getattr(svc, "state", None), "snapshot", None)
    return snapshot() if callable(snapshot) else None


def _robot_mode(snapshot: Any) -> Optional[str]:
    """D-380: CORE's live RobotMode for the boot display; absent rather than wrong.

    Duck-typed like ``_warning_percent``: a test double (or a CORE without a state
    manager) reports no mode, and the lamp falls back to the health patterns.
    """
    mode = getattr(snapshot, "mode", None)
    return robot_state.valid_robot_mode(getattr(mode, "value", mode))


def _nav_state(snapshot: Any) -> Optional[str]:
    """D-381: CORE's live NavigationState, same duck-typing and same absence rule."""
    nav = getattr(snapshot, "navigation", None)
    return robot_state.valid_nav_state(getattr(nav, "value", nav))


def _swarm_role(snapshot: Any) -> Optional[str]:
    """D-383: the live swarm role (leader/follower), same rules as the mode."""
    swarm = getattr(snapshot, "swarm", None)
    return robot_state.valid_swarm_role(getattr(swarm, "role", None))


def _number(value: Any) -> Optional[float]:
    """A finite float; NaN/Inf would be written as non-JSON and pass no bound."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return None
    return float(value)


def _flag(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


#: A free state string longer than this is not a state name; the file stays small.
MAX_STATUS_NAME = 64


def _name(value: Any) -> Optional[str]:
    value = getattr(value, "value", value)
    return value if isinstance(value, str) and len(value) <= MAX_STATUS_NAME else None


def _idleness_inputs(snapshot: Any) -> dict[str, Any]:
    """D-412: what the device updater judges idleness from.

    Every value is typed or null: an unknown is never written as a resting default,
    because the updater reads null as "not eligible". Sensor-derived values are
    freshness-gated: velocity only while its evidence is fresh (a silent odometry
    keeps its last 0.0, a false idle), the battery by the status summary's rule,
    and the charging flag (a dock latch) only beside a battery reading. Docking,
    line follow, swarm, E-stop and activity are CORE's own state, marked on change.
    """
    velocity_fresh = _evidence_of(snapshot, "velocity") == "fresh"
    velocity = getattr(snapshot, "velocity", None) if velocity_fresh else None
    line_follow = getattr(snapshot, "line_follow", None)
    percent = _number(_battery_reading(snapshot)[0])
    charging = getattr(getattr(snapshot, "battery_status", None), "charging", None)
    return {
        "velocity_linear": _number(getattr(velocity, "linear", None)),
        "velocity_angular": _number(getattr(velocity, "angular", None)),
        "battery_percent": percent,
        "battery_charging": _flag(charging) if percent is not None else None,
        "docking_state": _name(getattr(getattr(snapshot, "docking", None), "state", None)),
        "line_follow_mode": _name(getattr(line_follow, "mode", None)),
        "line_follow_state": _name(getattr(line_follow, "state", None)),
        "swarm_active": _flag(getattr(getattr(snapshot, "swarm", None), "active", None)),
        "estop": _flag(getattr(getattr(snapshot, "safety", None), "estop", None)),
        "activity_kind": _name(getattr(getattr(snapshot, "activity", None), "kind", None)),
    }


def status_inputs(svc: CoreServicesLike) -> dict[str, Any]:
    """What the root side cannot know: the live warning threshold, the overlaid device states and the live robot mode.

    Schema 2 (D-412) keeps every schema-1 key and adds the updater's idleness
    inputs. All state keys come from one snapshot, so they describe one instant.
    """
    hardware = host_hardware(None, svc)
    devices = [{"id": row["id"], "state": row["state"], "product": row["product"]}
               for row in (hardware["devices"] if hardware.get("available") else [])]
    snapshot = _snapshot(svc)
    return {"schema": 2, "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "battery_warning_percent": _warning_percent(svc), "devices": devices,
            "robot_mode": _robot_mode(snapshot), "nav_state": _nav_state(snapshot),
            "swarm_role": _swarm_role(snapshot), **_idleness_inputs(snapshot)}


def write_face_inputs(svc: CoreServicesLike, content: dict[str, Any]) -> None:
    """D-433: replace rosy-face's hand-over atomically (0644: nothing in it is secret).

    ``content`` is ``core.bridge.display.face_inputs_payload``; rosy-face reads it
    with ``core_common.face_screen.read_face_inputs`` (owner, size, freshness).
    """
    cfg = (svc.config or {}).get("hardware_probe", {}) or {}
    path = str(cfg.get("face_inputs_path", face_screen.FACE_INPUTS_FILE))
    payload = (json.dumps(content, sort_keys=True) + "\n").encode("utf-8")
    temporary = os.path.join(os.path.dirname(path) or ".", f".face-inputs.{secrets.token_hex(6)}")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            # rosy-core's UMask=0027 would leave 0640; rosy-face (rosy-display) must read it.
            # Set the mode on the temporary file so the name never points at an unreadable one.
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o644)
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if not hasattr(os, "fchmod"):
            os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_status_inputs(svc: CoreServicesLike) -> None:
    """Replace the hand-over atomically (0644: rosy-boot-status is root, nothing in it is secret)."""
    cfg = (svc.config or {}).get("hardware_probe", {}) or {}
    path = str(cfg.get("status_inputs_path", STATUS_INPUTS_FILE))
    _write_private(path, json.dumps(status_inputs(svc), sort_keys=True) + "\n", 0o644, "status-inputs")
