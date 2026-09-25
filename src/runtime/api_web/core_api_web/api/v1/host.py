"""core_api_web.api.v1.host — Host Agent 릴레이 (네트워크·릴리스·커미셔닝)와 장치 관측(D-247)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import stat
import threading
import time
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from core_api_web.api.errors import ApiError
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


MOTION_REASON = {
    "core": "모터가 꺼진 CORE 전용 모드입니다. 관리자가 모터 모드로 올려야 움직입니다.",
    "motor": "모터 벤치 모드입니다. 저속 직접 제어만 됩니다. LiDAR와 자율주행(Nav2)은 꺼져 있습니다.",
}


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


# --- D-247: board devices (root probe -> /run/rosy-boot/hardware.json) --------
#
# CORE never opens a device (D-161). rosy-hw-probe (root) writes what it saw;
# CORE reads that file as strictly as it reads the login verifier (D-193) and
# asks for a new run by writing a request file into its own /run/rosy, which
# rosy-hw-probe.path watches. No subprocess, no D-Bus.

HARDWARE_FILE = "/run/rosy-boot/hardware.json"
HW_REQUEST_FILE = "/run/rosy/hw-probe.request"
MAX_HARDWARE_BYTES = 64 * 1024
MAX_DEVICES = 64
MAX_TEXT = 200
HW_SCHEMA = 1
HW_STATES = ("ok", "no_response", "bus_missing", "driver_missing", "needs_human", "not_measured")
#: The probe takes seconds; a second request inside this window starts nothing new.
REFRESH_MIN_INTERVAL_S = 10.0
#: The card is not telemetry (D-247): a result older than this is shown faded.
HW_STALE_AFTER_S = 600.0
#: LiDAR scans and ultrasonic ranges are streams; two seconds without one is a stopped sensor.
TOPIC_FRESH_S = 2.0
MAX_BOOT_ID = 64
_last_refresh: dict[str, float] = {}

# D-247 6: the buzzer and the lamp are judged by a person. CORE asks the root
# rosy-hw-test (through rosy-hw-test.path) to beep or flash once, reads its
# outcome, and records the administrator's answer in its own state directory.
HW_TEST_REQUEST_FILE = "/run/rosy/hw-test.request"
HW_TEST_RESULT_FILE = "/run/rosy-boot/hw-test.json"
HW_CONFIRM_NAME = "hw-confirmations.json"
HW_TEST_DEVICES = ("buzzer", "lamp")
HW_TEST_STATES = ("done", "busy", "unavailable", "failed")
#: One test at a time: a second press inside this window starts nothing.
HW_TEST_COOLDOWN_S = 10.0
MAX_SMALL_FILE_BYTES = 8 * 1024
#: What a person answered, in the words of each device.
NOT_OBSERVED = {"buzzer": "들리지 않음", "lamp": "보이지 않음"}
#: An answer must follow a test of that device that rosy-hw-test finished this recently.
HW_CONFIRM_WINDOW_S = 300.0
#: rosy-hw-test and CORE share a clock; a finish time further ahead than this is not trusted.
HW_CONFIRM_FUTURE_SKEW_S = 5.0
_last_test: dict[str, float] = {}
#: Two presses in the same instant must not both pass the cool-down check.
_test_lock = threading.Lock()
#: Two answers in the same instant must not drop each other's device.
_confirm_lock = threading.Lock()


def _hardware_paths(svc: CoreServicesLike) -> tuple[str, str]:
    cfg = (svc.config or {}).get("hardware_probe", {}) or {}
    return str(cfg.get("result_path", HARDWARE_FILE)), str(cfg.get("request_path", HW_REQUEST_FILE))


def _test_paths(svc: CoreServicesLike) -> tuple[str, str, str]:
    """(request, result, confirmations). The answers live beside CORE's other state (~/.rosy)."""
    cfg = (svc.config or {}).get("hardware_probe", {}) or {}
    confirm = cfg.get("confirm_path") or str(Path.home() / ".rosy" / HW_CONFIRM_NAME)
    return (str(cfg.get("test_request_path", HW_TEST_REQUEST_FILE)),
            str(cfg.get("test_result_path", HW_TEST_RESULT_FILE)), str(confirm))


def _read_small_json(path: str) -> Any:
    """A small JSON document, never through a symlink or a FIFO; None when absent or unreadable."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
        | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SMALL_FILE_BYTES:
            return None
        raw = os.read(descriptor, MAX_SMALL_FILE_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    if len(raw) > MAX_SMALL_FILE_BYTES:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _aware_time(value: Any) -> Optional[datetime]:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def read_test_result(path: str) -> Optional[dict[str, Any]]:
    """rosy-hw-test's last outcome, validated like hardware.json, or None."""
    data = _read_small_json(path)
    if not isinstance(data, dict) or data.get("schema") != 1:
        return None
    row = {key: data.get(key) for key in ("request_id", "action", "state", "detail")}
    if not all(isinstance(value, str) and len(value) <= MAX_TEXT for value in row.values()):
        return None
    if row["action"] not in HW_TEST_DEVICES or row["state"] not in HW_TEST_STATES:
        return None
    finished = _aware_time(data.get("finished_at"))
    if finished is None:
        return None
    row["finished_at"] = finished.astimezone(timezone.utc).isoformat(timespec="seconds")
    return row


def read_confirmations(path: str) -> dict[str, dict[str, Any]]:
    """The recorded answers per device; an entry that does not validate is dropped."""
    data = _read_small_json(path)
    devices = data.get("devices") if isinstance(data, dict) and data.get("schema") == 1 else None
    if not isinstance(devices, dict):
        return {}
    clean = {}
    for device, entry in devices.items():
        if device not in HW_TEST_DEVICES or not isinstance(entry, dict):
            continue
        if type(entry.get("observed")) is not bool or _aware_time(entry.get("at")) is None:
            continue
        if not all(isinstance(entry.get(key), str) and len(entry[key]) <= MAX_TEXT for key in ("by", "label")):
            continue
        clean[device] = {key: entry[key] for key in ("observed", "by", "label", "at")}
        request_id = entry.get("request_id")
        if isinstance(request_id, str) and len(request_id) <= MAX_TEXT:
            clean[device]["request_id"] = request_id
    return clean


def _confirmation_overlay(row: dict[str, Any], confirmations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A person's answer turns a `needs_human` buzzer or lamp row into ok / no_response.

    Only `needs_human`: a missing driver or a wrong lamp channel stays what the
    probe measured, whatever someone once heard or saw.
    """
    answer = confirmations.get(row["id"])
    if answer is None or row["state"] != "needs_human":
        return row
    at = _aware_time(answer["at"]).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    who = answer["label"] or answer["by"]
    if answer["observed"]:
        return {**row, "state": "ok", "evidence": f"사람 확인: {who} {at}", "source": "human"}
    heard = NOT_OBSERVED[row["id"]]
    return {**row, "state": "no_response", "evidence": f"사람 확인: {heard} · {who} {at}", "source": "human"}


def _write_private(path: str, payload: str, mode: int, prefix: str) -> None:
    """Write beside the target with O_EXCL | O_NOFOLLOW, then rename over it (atomic)."""
    directory = os.path.dirname(path) or "."
    temporary = os.path.join(directory, f".{prefix}.{secrets.token_hex(6)}")
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def read_hardware(path: str) -> Optional[dict[str, Any]]:
    """The probe's result, validated, or None. Root wrote it; CORE still reads it strictly.

    No symlink (O_NOFOLLOW), regular files only (a FIFO would block), at most
    MAX_HARDWARE_BYTES, schema 1, known states and bounded strings. A missing
    file raises FileNotFoundError: "not measured yet" is not "unreadable".
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
        | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_HARDWARE_BYTES:
            return None
        raw = os.read(descriptor, MAX_HARDWARE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_HARDWARE_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != HW_SCHEMA:
        return None
    try:
        measured = datetime.fromisoformat(str(data["measured_at"]))
    except (KeyError, ValueError):
        return None
    devices = data.get("devices")
    if measured.tzinfo is None or not isinstance(devices, list) or not 0 < len(devices) <= MAX_DEVICES:
        return None
    clean = []
    seen: set[str] = set()
    for device in devices:
        if not isinstance(device, dict):
            return None
        row = {key: device.get(key) for key in ("id", "label", "bus", "state", "evidence")}
        if not all(isinstance(value, str) and len(value) <= MAX_TEXT for value in row.values()):
            return None
        if row["state"] not in HW_STATES or type(device.get("product")) is not bool or row["id"] in seen:
            return None
        seen.add(row["id"])
        row["product"] = device["product"]
        held_by = device.get("held_by")
        if held_by is not None:
            if not isinstance(held_by, str) or len(held_by) > MAX_TEXT:
                return None
            row["held_by"] = held_by
        clean.append(row)
    boot_id = data.get("boot_id")
    if boot_id is not None and (not isinstance(boot_id, str) or len(boot_id) > MAX_BOOT_ID):
        return None
    return {"measured_at": measured, "boot_id": boot_id,
            "devices": clean}


def _evidence_of(snapshot: Any, channel: str) -> Optional[str]:
    value = (getattr(snapshot, "evidence", None) or {}).get(channel)
    judged = getattr(value, "evidence", None)
    return None if judged is None else str(getattr(judged, "value", judged))


#: Rows judged from a sensor sample CORE keeps (state.get_sensor): device id -> (sensor, topic).
SAMPLE_TOPICS = {"lidar": ("lidar", "scan"), "adc.ultrasonic": ("ultrasonic", "us_range")}
#: Rows judged from CORE's own evidence channels: device id -> (channel, topic).
EVIDENCE_TOPICS = {"adc.battery": ("battery", "battery"), "motor.1": ("velocity", "odom"),
                   "motor.2": ("velocity", "odom")}


def _topic_overlay(row: dict[str, Any], state: Any, snapshot: Any) -> dict[str, Any]:
    """Judge a device rosy-io holds from topics CORE already receives (D-247 4).

    Only rows the probe left `not_measured` because a runtime held the bus. A
    row with no topic in CORE (the IR channels) says so instead of waiting
    for a judgment that will not come.
    """
    if state is None or row["state"] != "not_measured" or not row.get("held_by"):
        return row
    device = row["id"]
    if device in SAMPLE_TOPICS:
        sensor, topic = SAMPLE_TOPICS[device]
        sample = state.get_sensor(sensor) if hasattr(state, "get_sensor") else None
        received = (sample or {}).get("received_at")
        if not isinstance(received, (int, float)):
            return {**row, "evidence": f"측정 안 함 — {row['held_by'].removesuffix('.service')} 사용 중"}
        age = max(0.0, time.time() - received)
        if age <= TOPIC_FRESH_S:
            return {**row, "state": "ok", "evidence": f"{topic} {age:.1f} s 전 (토픽 판정)", "source": "topic"}
        return {**row, "state": "no_response", "evidence": f"{topic} {age:.0f} s 전에 끊김 (토픽 판정)",
                "source": "topic"}
    if device not in EVIDENCE_TOPICS or snapshot is None:
        return {**row, "evidence": f"측정 안 함 — {row['held_by'].removesuffix('.service')} 사용 중"}
    channel, topic = EVIDENCE_TOPICS[device]
    judged = _evidence_of(snapshot, channel)
    if judged == "fresh":
        volts = getattr(getattr(snapshot, "battery", None), "voltage", None)
        text = (f"{volts:.2f} V (토픽 판정)" if channel == "battery" and isinstance(volts, (int, float))
                else f"{topic} 수신 중 (토픽 판정)")
        return {**row, "state": "ok", "evidence": text, "source": "topic"}
    if judged in {"delayed", "disconnected"}:
        return {**row, "state": "no_response", "evidence": f"{topic} {judged} (토픽 판정)", "source": "topic"}
    return {**row, "evidence": f"측정 안 함 — {row['held_by'].removesuffix('.service')} 사용 중"}


@host_router.get("/hardware")
def host_hardware(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """보드의 모든 장치가 붙어 있고 응답하는지 (D-247). capability와는 다른 질문이다."""
    result_path, _request_path = _hardware_paths(svc)
    try:
        result = read_hardware(result_path)
    except FileNotFoundError:
        return {"available": False, "detail": "장치 점검 결과가 아직 없습니다", "devices": []}
    except OSError:
        result = None
    if result is None:
        return {"available": False, "detail": "장치 점검 결과를 읽을 수 없습니다", "devices": []}
    measured = result["measured_at"]
    age = max(0.0, (datetime.now(timezone.utc) - measured).total_seconds())
    # One snapshot per request, and only when a row needs a topic judgment.
    state = getattr(svc, "state", None)
    needs = state is not None and any(row["state"] == "not_measured" and row.get("held_by")
                                       for row in result["devices"])
    snapshot = state.snapshot() if needs else None
    _request, test_result, confirm_path = _test_paths(svc)
    confirmations = read_confirmations(confirm_path)
    return {
        "available": True,
        "schema": HW_SCHEMA,
        "measured_at": measured.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "age_s": round(age, 1),
        "stale": age > HW_STALE_AFTER_S,
        "boot_id": result["boot_id"],
        "devices": [_confirmation_overlay(_topic_overlay(row, state, snapshot), confirmations)
                    for row in result["devices"]],
        # D-247 6: the last buzzer/lamp test rosy-hw-test ran, for the card to show.
        "test": read_test_result(test_result),
        "detail": "",
    }


@host_router.post("/hardware/refresh")
def host_hardware_refresh(auth: AuthContext = Depends(admin), svc: CoreServicesLike = Depends(get_services)):
    """rosy-hw-probe 재실행 요청. CORE는 요청 파일만 쓰고 측정은 root가 한다(D-161)."""
    _result_path, request_path = _hardware_paths(svc)
    now = time.monotonic()
    last = _last_refresh.get(request_path)
    if last is not None and now - last < REFRESH_MIN_INTERVAL_S:
        return {"accepted": False, "detail": "방금 점검을 요청했습니다. 잠시 뒤 결과를 확인하세요."}
    directory = os.path.dirname(request_path) or "."
    temporary = os.path.join(directory, f".hw-probe.request.{secrets.token_hex(6)}")
    payload = json.dumps({"requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "by": auth.token_id}, sort_keys=True) + "\n"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o640)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temporary, request_path)
    except OSError as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise ApiError("HW_PROBE_UNAVAILABLE", 503, "장치 점검을 요청하지 못했습니다") from exc
    _last_refresh[request_path] = now
    return {"accepted": True, "detail": "장치 점검을 요청했습니다. 잠시 뒤 결과가 바뀝니다."}


class HardwareTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: Literal["buzzer", "lamp"]


class HardwareConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: Literal["buzzer", "lamp"]
    observed: StrictBool


@host_router.post("/hardware/test")
def host_hardware_test(
    body: HardwareTestRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    """부저를 한 번 울리거나 램프를 한 번 켠다(D-247 6). CORE는 요청 파일만 쓰고 장치는 root가 다룬다."""
    request_path, _result, _confirm = _test_paths(svc)
    request_id = secrets.token_hex(8)
    payload = json.dumps({"action": body.device, "request_id": request_id, "by": auth.token_id,
                          "requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                         sort_keys=True) + "\n"
    # Check, write and start the cool-down as one step: of two presses at once, one is accepted.
    with _test_lock:
        now = time.monotonic()
        last = _last_test.get(request_path)
        if last is not None and now - last < HW_TEST_COOLDOWN_S:
            raise ApiError("HW_TEST_COOLDOWN", 429, "방금 시험했습니다. 10초 뒤에 다시 누르세요.")
        try:
            _write_private(request_path, payload, 0o640, "hw-test.request")
        except OSError as exc:
            raise ApiError("HW_TEST_UNAVAILABLE", 503, "장치 시험을 요청하지 못했습니다") from exc
        _last_test[request_path] = now
    what = "부저를 울립니다" if body.device == "buzzer" else "램프를 켭니다"
    return {"accepted": True, "request_id": request_id, "device": body.device,
            "detail": f"{what}. 들렸는지·보였는지 확인해 주세요."}


@host_router.post("/hardware/confirm")
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
    _request, result_path, confirm_path = _test_paths(svc)
    test = read_test_result(result_path)
    if test is None or test["action"] != body.device:
        raise ApiError("HW_CONFIRM_NO_TEST", 409, "이 장치를 먼저 시험한 뒤에 답해 주세요.")
    if test["state"] != "done":
        raise ApiError("HW_CONFIRM_NO_TEST", 409, "마지막 시험이 끝나지 않았습니다. 다시 시험한 뒤에 답해 주세요.")
    now = datetime.now(timezone.utc)
    age = (now - datetime.fromisoformat(test["finished_at"])).total_seconds()
    if not -HW_CONFIRM_FUTURE_SKEW_S <= age <= HW_CONFIRM_WINDOW_S:
        raise ApiError("HW_CONFIRM_NO_TEST", 409, "마지막 시험이 5분보다 오래되었습니다. 다시 시험한 뒤에 답해 주세요.")
    entry = {"observed": body.observed, "by": auth.token_id, "label": (auth.label or "")[:MAX_TEXT],
             "at": now.isoformat(timespec="seconds")}
    # The test's request_id ties the answer to the run it judged. It stays in the 0600 file
    # (audit); the response and the card do not carry it.
    stored = {**entry, "request_id": test["request_id"]}
    with _confirm_lock:
        confirmations = read_confirmations(confirm_path)
        confirmations[body.device] = stored
        payload = json.dumps({"schema": 1, "devices": confirmations}, ensure_ascii=False, sort_keys=True) + "\n"
        try:
            os.makedirs(os.path.dirname(confirm_path) or ".", mode=0o700, exist_ok=True)
            _write_private(confirm_path, payload, 0o600, HW_CONFIRM_NAME)
        except OSError as exc:
            raise ApiError("HW_CONFIRM_UNAVAILABLE", 503, "확인 결과를 기록하지 못했습니다") from exc
    return {"recorded": True, "device": body.device, **entry}
