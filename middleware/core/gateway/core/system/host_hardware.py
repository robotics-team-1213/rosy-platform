"""Bounded host-file validation and hardware/status overlays (D-247, D-260)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
import re
import stat
import time
from typing import Any, Optional

from core_common import robot_state

MAX_HARDWARE_BYTES = 64 * 1024
MAX_DEVICES = 64
MAX_TEXT = 200
HW_SCHEMA = 1
HW_STATES = ("ok", "no_response", "bus_missing", "driver_missing", "needs_human", "not_measured")
TOPIC_FRESH_S = 2.0
MAX_BOOT_ID = 64
HW_TEST_DEVICES = ("buzzer", "lamp")
HW_TEST_ACTIONS = (*HW_TEST_DEVICES, "identify_blue", "identify_amber",
                   "identify_blue_quiet", "identify_amber_quiet")
HW_TEST_STATES = ("done", "busy", "unavailable", "failed")
MAX_SMALL_FILE_BYTES = 8 * 1024
NOT_OBSERVED = {"buzzer": "들리지 않음", "lamp": "보이지 않음"}
IDENTIFY_REASON = re.compile(r"[A-Z][A-Z_]{0,39}")
SAMPLE_TOPICS = {"lidar": ("lidar", "scan"), "adc.ultrasonic": ("ultrasonic", "us_range")}
EVIDENCE_TOPICS = {"adc.battery": ("battery", "battery"), "motor.1": ("velocity", "odom"),
                   "motor.2": ("velocity", "odom")}
MAX_STATUS_NAME = 64


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


def read_test_result(path: str, *, with_reason: bool = False) -> Optional[dict[str, Any]]:
    """rosy-hw-test's last outcome, validated like hardware.json, or None.

    ``with_reason`` adds rosy-face's identify refusal code (D-596 rev 2026-10-10), or None."""
    data = _read_small_json(path)
    if not isinstance(data, dict) or data.get("schema") != 1:
        return None
    row = {key: data.get(key) for key in ("request_id", "action", "state", "detail")}
    if not all(isinstance(value, str) and len(value) <= MAX_TEXT for value in row.values()):
        return None
    if row["action"] not in HW_TEST_ACTIONS or row["state"] not in HW_TEST_STATES:
        return None
    finished = _aware_time(data.get("finished_at"))
    if finished is None:
        return None
    row["finished_at"] = finished.astimezone(timezone.utc).isoformat(timespec="seconds")
    if with_reason:
        reason = data.get("reason")
        row["reason"] = reason if isinstance(reason, str) and IDENTIFY_REASON.fullmatch(reason) else None
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
        sample = state.get_sensor(sensor)
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


def _warning_percent(svc: Any) -> float:
    policy = getattr(getattr(svc, "safety", None), "battery_policy", None)
    value = robot_state.BATTERY_WARNING_PERCENT if policy is None else policy.warning_percent
    try:
        return float(value)
    except (TypeError, ValueError):
        return robot_state.BATTERY_WARNING_PERCENT


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
