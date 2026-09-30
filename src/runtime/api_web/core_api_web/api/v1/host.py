"""core_api_web.api.v1.host ??Host Agent 由대젅??(?ㅽ듃?뚰겕쨌由대━?ㅒ룹빱誘몄뀛??? ?μ튂 愿痢?D-247)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core_api_web.api.v1.common import admin, viewer
from core_api_web.api.deps import AuthContext, get_services, CoreServicesLike
from core_api_web.api.host_agent_client import HostAgentClient, TIMEOUT, UNAVAILABLE
from core_common import robot_state
from core_common.protocol.evidence import EvidenceState
from core_common.protocol.schemas import HostStatusEvidence
from . import host_hardware as _host_hardware


# --- Network / Release / Commissioning (WP-5, ?ㅺ퀎 짠10.2/짠10.3) --------------
#
# CORE ???몄뒪??沅뚰븳???놁쑝誘濡??????붾㈃???곗씠?곕뒗 ?꾨? Host Agent ?먯꽌 ?⑤떎.
# ?먯씠?꾪듃媛 ?녿뒗 ?곹깭(媛쒕컻 ?λ퉬, ?쒕퉬??誘멸린?????덉쇅媛 ?꾨땲???뺤긽?곸쑝濡?
# ?덉쓣 ???덈뒗 ?곹깭?대ŉ, 洹몃븣 **?녿뒗 媛믪쓣 洹몃윺??븯寃?梨꾩슦吏 ?딅뒗??** 鍮?移몄?
# ?댁쁺?먯뿉寃?"?댁긽 ?놁쓬" ?쇰줈 ?쏀엳怨? 吏?대궦 媛믪? ?ъ떎濡??쏀엺??

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
                                  reason="Host Agent???곌껐?섏? ?딆븯嫄곕굹 ?묐떟???쒓컙 ?덉뿉 ?ㅼ? ?딆븯?듬땲??", **base)
    if not reply.reachable or not reply.ok:
        return HostStatusEvidence(reason="Host Agent媛 ?꾩쟾???곹깭 議고쉶 寃곌낵瑜?二쇱? ?딆븯?듬땲??", **base)
    try:
        observed = datetime.fromisoformat(reply.observed_at) if reply.observed_at else None
    except (TypeError, ValueError):
        observed = None
    if observed is None or observed.tzinfo is None or observed.utcoffset().total_seconds() != 0:
        return HostStatusEvidence(reason="Host Agent ?먮낯 議고쉶 ?꾨즺 ?쒓컖???놁뒿?덈떎.", **base)
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    if age < 0:
        return HostStatusEvidence(reason="Host Agent ?먮낯 ?쒓컖??CORE ?쒓컖蹂대떎 誘몃옒?낅땲??", **base)
    state = EvidenceState.DELAYED if age > HOST_STATUS_STALE_AFTER_S else EvidenceState.FRESH
    return HostStatusEvidence(evidence=state, observed_at=reply.observed_at,
                              age_s=round(age, 1),
                              reason="Host Agent ?먮낯 議고쉶媛 吏?곕릺?덉뒿?덈떎." if state is EvidenceState.DELAYED
                              else "Host Agent ?먮낯 議고쉶 ?꾨즺 ?쒓컖???뺤씤?덉뒿?덈떎.", **base)


def _relay(reply, *, absent_detail: str, status_read: bool = False) -> dict:
    """Turn an agent reply into a card payload that cannot mislead.

    ``available`` is the field the dashboard keys on. When it is false the
    card shows why instead of showing empty fields ??an unreachable agent and
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
    """?꾩옱 ?ㅽ듃?뚰겕 紐⑤뱶? ?꾨떖?? SSID ???쒖떆?섎릺 secret ? ?덈? ?ｌ? ?딅뒗??"""
    reply = _agent(svc).request("network.status", role="viewer")
    return _relay(reply, absent_detail="Host Agent ???곌껐?????놁뼱 ?ㅽ듃?뚰겕 ?곹깭瑜??????놁뒿?덈떎.",
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
    return _relay(reply, absent_detail="Host Agent ???곌껐?????놁뼱 ?ㅽ듃?뚰겕 ?꾨줈?뚯씪??諛붽씀吏 紐삵뻽?듬땲??")


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
    return _relay(reply, absent_detail="Host Agent ???곌껐?????놁뼱 ?ㅽ듃?뚰겕 紐⑤뱶瑜?諛붽씀吏 紐삵뻽?듬땲??")


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
        _relay(reply, absent_detail="Host Agent ???곌껐?????놁뼱 Wi-Fi???곌껐?섏? 紐삵뻽?듬땲??")
    )


@host_router.get("/release")
def host_release(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """current / previous / staged ? 留덉?留??ㅽ뙣 ?ъ쑀."""
    reply = _agent(svc).request("release.status", role="viewer")
    return _relay(reply, absent_detail="Host Agent ???곌껐?????놁뼱 由대━???곹깭瑜??????놁뒿?덈떎.",
                  status_read=True)


class HostActionRequest(BaseModel):
    """?뚭눼??紐낅졊??怨듯넻 ?낅젰.

    `confirmed` ????쒕낫?쒖쓽 ?ы솗?몄씠 ?ㅼ젣濡??덉뿀?뚯쓣 ?삵븳?? 湲곕낯媛믪씠 False ??
    寃껋씠 ?듭떖?대떎 ??鍮좊쑉由щ㈃ ?ㅽ뻾?섏? ?딄퀬 嫄곕??쒕떎.
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
    return _relay(reply, absent_detail="Host Agent ???곌껐?????놁뼱 ?ㅼ튂瑜??쒖옉?섏? 紐삵뻽?듬땲??")


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
    return _relay(reply, absent_detail="Host Agent ???곌껐?????놁뼱 濡ㅻ갚???쒖옉?섏? 紐삵뻽?듬땲??")


@host_router.post("/release/clear-hold")
def host_release_clear_hold(
    body: HostActionRequest,
    auth: AuthContext = Depends(admin),
    svc: CoreServicesLike = Depends(get_services),
):
    """RECOVERY HOLD ?댁젣. ???以묒뿉??install ??嫄곕??섎?濡?蹂꾨룄???섎룄???됱쐞??"""
    reply = _agent(svc).request(
        "release.clear_hold",
        role="administrator",
        user_id=auth.token_id,
        confirmed=body.confirmed,
        idempotency_key=body.idempotency_key,
    )
    return _relay(reply, absent_detail="Host Agent ???곌껐?????놁뼱 ??쒕? ?댁젣?섏? 紐삵뻽?듬땲??")


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
    return _relay(reply, absent_detail="Host Agent ???곌껐?????놁뼱 ?щ??낇븯吏 紐삵뻽?듬땲??")


# D-247 7's sentences live in the D-260 rule table, which the boot display shares.
MOTION_REASON = robot_state.MOTION_REASON


@host_router.get("/commissioning")
def host_commissioning(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    """runtime mode ? hardware ?ъ듅???ъ쑀.

    runtime mode ??CORE 媛 ?ㅼ뒪濡??덈떎 ???먭린媛 臾댁뾿?쇰줈 湲곕룞?덈뒗吏???몄뒪?몄뿉
    臾살? ?딆븘???쒕떎. 洹몃옒????移대뱶???먯씠?꾪듃媛 ?놁뼱???덈컲? ?뺤쭅?섍쾶 梨꾩슫??
    """
    mode = (svc.config or {}).get("runtime", {}).get("mode", "core")
    if mode == "core":
        detail = (
            "UART쨌紐⑦꽣 誘몄듅???곹깭?낅땲?? ?닿쾬? ?뺤긽?대ŉ, ?밴꺽? 蹂꾨룄 ?꾩옣 ?덉쟾 "
            "?덉감瑜??곕쫭?덈떎."
        )
    elif mode == "motor":
        detail = (
            "紐⑦꽣 踰ㅼ튂 紐⑤뱶?낅땲?? LiDAR???꾩쭅 爰쇱졇 ?덉쑝硫?hardware 紐⑤뱶??"
            "蹂꾨룄 ?섎씫???꾩슂?⑸땲?? 諛고꽣由?ADC, IMU, SLAM, Fleet???놁뒿?덈떎."
        )
    else:
        detail = (
            f"?꾩옱 {mode} 紐⑤뱶濡?湲곕룞?섏뼱 ?덉뒿?덈떎. 紐⑦꽣? LiDAR? Nav2????"
            "?щ씪?댁뒪???덉뒿?덈떎. 諛고꽣由??꾩븬(ADC), IMU, SLAM, Fleet??"
            "?꾩슦吏 ?딆뒿?덈떎."
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
    """?댁슜 ?붾㈃ ?붿빟以?D-260 5): 濡쒕큸 ?곹깭 ?섎굹, ?댁쑀, ?μ튂 ?붿빟, 諛고꽣由?룹삩?? ????"""
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


def _robot_mode(svc: CoreServicesLike) -> Optional[str]:
    """D-380: CORE's live RobotMode for the boot display; absent rather than wrong.

    Duck-typed like ``_warning_percent``: a test double (or a CORE without a state
    manager) reports no mode, and the lamp falls back to the health patterns.
    """
    snapshot = getattr(getattr(svc, "state", None), "snapshot", None)
    mode = getattr(snapshot() if callable(snapshot) else None, "mode", None)
    return robot_state.valid_robot_mode(getattr(mode, "value", mode))


def status_inputs(svc: CoreServicesLike) -> dict[str, Any]:
    """What the root side cannot know: the live warning threshold, the overlaid device states and the live robot mode."""
    hardware = host_hardware(None, svc)
    devices = [{"id": row["id"], "state": row["state"], "product": row["product"]}
               for row in (hardware["devices"] if hardware.get("available") else [])]
    return {"schema": 1, "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "battery_warning_percent": _warning_percent(svc), "devices": devices,
            "robot_mode": _robot_mode(svc)}


def write_status_inputs(svc: CoreServicesLike) -> None:
    """Replace the hand-over atomically (0644: rosy-boot-status is root, nothing in it is secret)."""
    cfg = (svc.config or {}).get("hardware_probe", {}) or {}
    path = str(cfg.get("status_inputs_path", STATUS_INPUTS_FILE))
    _write_private(path, json.dumps(status_inputs(svc), sort_keys=True) + "\n", 0o644, "status-inputs")
