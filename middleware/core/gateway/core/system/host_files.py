"""CORE's unprivileged host-file exchange; host units retain device authority."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Optional

from core_common import face_screen
from .host_hardware import (
    MAX_TEXT, _read_small_json, read_hardware, read_test_result, read_confirmations,
    _confirmation_overlay, _topic_overlay, _warning_percent, _robot_mode,
    _nav_state, _swarm_role, _idleness_inputs,
)

# Request-path maps and both locks are process-wide across owner instances.
HARDWARE_FILE = "/run/rosy-boot/hardware.json"
HW_REQUEST_FILE = "/run/rosy/hw-probe.request"
REFRESH_MIN_INTERVAL_S = 10.0
_last_refresh: dict[str, float] = {}
HW_TEST_REQUEST_FILE = "/run/rosy/hw-test.request"
HW_TEST_RESULT_FILE = "/run/rosy-boot/hw-test.json"
HW_CONFIRM_NAME = "hw-confirmations.json"
HW_TEST_COOLDOWN_S = 10.0
HW_CONFIRM_WINDOW_S = 300.0
HW_CONFIRM_FUTURE_SKEW_S = 5.0
_last_test: dict[str, float] = {}
_last_identify: dict[str, tuple[str, float]] = {}
IDENTIFY_RESULT_WAIT_S = 20.0
_test_lock = threading.Lock()
_confirm_lock = threading.Lock()
STATUS_INPUTS_FILE = "/run/rosy/status-inputs.json"
STATUS_INPUTS_PERIOD_S = 1.0
_UNSET = object()


def _hardware_paths(svc: Any) -> tuple[str, str]:
    cfg = (svc.config or {}).get("hardware_probe", {}) or {}
    return str(cfg.get("result_path", HARDWARE_FILE)), str(cfg.get("request_path", HW_REQUEST_FILE))


def _test_paths(svc: Any) -> tuple[str, str, str]:
    """(request, result, confirmations). The answers live beside CORE's other state (~/.rosy)."""
    cfg = (svc.config or {}).get("hardware_probe", {}) or {}
    confirm = cfg.get("confirm_path") or str(Path.home() / ".rosy" / HW_CONFIRM_NAME)
    return (str(cfg.get("test_request_path", HW_TEST_REQUEST_FILE)),
            str(cfg.get("test_result_path", HW_TEST_RESULT_FILE)), str(confirm))


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


def _snapshot(svc: Any) -> Any:
    """One StateSnapshot (what GET /robot/state serves), or None without a state manager."""
    snapshot = getattr(getattr(svc, "state", None), "snapshot", None)
    return snapshot() if callable(snapshot) else None


def _hardware(svc: Any, snapshot: Any = _UNSET) -> Optional[dict[str, Any]]:
    result_path, _request_path = _hardware_paths(svc)
    result = read_hardware(result_path)
    if result is None:
        return None
    age = max(0.0, (datetime.now(timezone.utc) - result["measured_at"]).total_seconds())
    state = getattr(svc, "state", None)
    needs = state is not None and any(row["state"] == "not_measured" and row.get("held_by")
                                       for row in result["devices"])
    if snapshot is _UNSET:
        snapshot = state.snapshot() if needs else None
    _request, test_result, confirm_path = _test_paths(svc)
    confirmations = read_confirmations(confirm_path)
    return {**result, "age_s": age,
            "devices": [_confirmation_overlay(_topic_overlay(row, state, snapshot), confirmations)
                        for row in result["devices"]],
            "test": read_test_result(test_result)}


class HostFileError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class HostFileExchange:
    Error = HostFileError

    def hardware(self, svc: Any) -> Optional[dict[str, Any]]:
        """Validated readback with overlays and age; absent files still raise FileNotFoundError."""
        return _hardware(svc)

    def refresh_hardware(self, svc: Any, *, by: str) -> bool:
        """Whether a new request was written, or False inside the refresh interval."""
        _result_path, request_path = _hardware_paths(svc)
        now = time.monotonic()
        last = _last_refresh.get(request_path)
        if last is not None and now - last < REFRESH_MIN_INTERVAL_S:
            return False
        directory = os.path.dirname(request_path) or "."
        temporary = os.path.join(directory, f".hw-probe.request.{secrets.token_hex(6)}")
        payload = json.dumps({"requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "by": by}, sort_keys=True) + "\n"
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
            raise HostFileError("HW_PROBE_UNAVAILABLE", "장치 점검을 요청하지 못했습니다") from exc
        _last_refresh[request_path] = now
        return True

    def identify(self, svc: Any, *, color: str, quiet: bool, by: str) -> str:
        """Write the visual challenge and return its request ID."""
        request_path, _result, _confirm = _test_paths(svc)
        request_id = secrets.token_hex(8)
        # Milliseconds: rosy-hw-test refuses an identify older than 1.5 s (D-472 4, total <= 6 s).
        action = f"identify_{color}" + ("_quiet" if quiet else "")
        payload = json.dumps({"action": action, "request_id": request_id,
                              "by": by,
                              "requested_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds")},
                             sort_keys=True) + "\n"
        with _test_lock:
            now = time.monotonic()
            last = _last_test.get(request_path)
            if last is not None and now - last < HW_TEST_COOLDOWN_S:
                raise HostFileError("HW_TEST_COOLDOWN", "방금 램프를 사용했습니다. 잠시 뒤에 다시 시도하세요.")
            try:
                _write_private(request_path, payload, 0o640, "hw-test.request")
            except OSError as exc:
                raise HostFileError("HW_TEST_UNAVAILABLE", "램프 식별 요청을 전달하지 못했습니다") from exc
            _last_test[request_path] = now
            _last_identify[request_path] = (request_id, now)
        return request_id

    def identify_result(self, svc: Any, request_id: str) -> tuple[Optional[dict[str, Any]], bool]:
        """The matching validated result and expiry flag; API chooses the display state."""
        request_path, result_path, _confirm = _test_paths(svc)
        last = _last_identify.get(request_path)
        if last is None or last[0] != request_id:
            raise HostFileError("IDENTIFY_REQUEST_UNKNOWN", "이 식별 요청을 모릅니다(마지막 요청만 답합니다)")
        result = read_test_result(result_path, with_reason=True)
        if result is not None and result["request_id"] == request_id:
            return result, False
        return None, time.monotonic() - last[1] > IDENTIFY_RESULT_WAIT_S

    def test_hardware(self, svc: Any, *, device: str, by: str) -> str:
        """Write the device test and return its request ID."""
        request_path, _result, _confirm = _test_paths(svc)
        request_id = secrets.token_hex(8)
        payload = json.dumps({"action": device, "request_id": request_id, "by": by,
                              "requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                             sort_keys=True) + "\n"
        # Check, write and start the cool-down as one step: of two presses at once, one is accepted.
        with _test_lock:
            now = time.monotonic()
            last = _last_test.get(request_path)
            if last is not None and now - last < HW_TEST_COOLDOWN_S:
                raise HostFileError("HW_TEST_COOLDOWN", "방금 시험했습니다. 10초 뒤에 다시 누르세요.")
            try:
                _write_private(request_path, payload, 0o640, "hw-test.request")
            except OSError as exc:
                raise HostFileError("HW_TEST_UNAVAILABLE", "장치 시험을 요청하지 못했습니다") from exc
            _last_test[request_path] = now
        return request_id

    def confirm_hardware(self, svc: Any, *, device: str, observed: bool, by: str, label: str) -> dict[str, Any]:
        """Persist the answer with its test ID; return the answer without the audit-only ID."""
        _request, result_path, confirm_path = _test_paths(svc)
        test = read_test_result(result_path)
        if test is None or test["action"] != device:
            raise HostFileError("HW_CONFIRM_NO_TEST", "이 장치를 먼저 시험한 뒤에 답해 주세요.")
        if test["state"] != "done":
            raise HostFileError("HW_CONFIRM_NO_TEST", "마지막 시험이 끝나지 않았습니다. 다시 시험한 뒤에 답해 주세요.")
        now = datetime.now(timezone.utc)
        age = (now - datetime.fromisoformat(test["finished_at"])).total_seconds()
        if not -HW_CONFIRM_FUTURE_SKEW_S <= age <= HW_CONFIRM_WINDOW_S:
            raise HostFileError("HW_CONFIRM_NO_TEST", "마지막 시험이 5분보다 오래되었습니다. 다시 시험한 뒤에 답해 주세요.")
        entry = {"observed": observed, "by": by, "label": (label or "")[:MAX_TEXT],
                 "at": now.isoformat(timespec="seconds")}
        # The test's request_id ties the answer to the run it judged. It stays in the 0600 file
        # (audit); the response and the card do not carry it.
        stored = {**entry, "request_id": test["request_id"]}
        with _confirm_lock:
            confirmations = read_confirmations(confirm_path)
            confirmations[device] = stored
            payload = json.dumps({"schema": 1, "devices": confirmations}, ensure_ascii=False, sort_keys=True) + "\n"
            try:
                os.makedirs(os.path.dirname(confirm_path) or ".", mode=0o700, exist_ok=True)
                _write_private(confirm_path, payload, 0o600, HW_CONFIRM_NAME)
            except OSError as exc:
                raise HostFileError("HW_CONFIRM_UNAVAILABLE", "확인 결과를 기록하지 못했습니다") from exc
        return entry

    def read_boot_status(self, path: str) -> Optional[dict[str, Optional[str]]]:
        """rosy-boot-status's stage and failed unit, or None when absent, unreadable or malformed."""
        data = _read_small_json(path)
        if not isinstance(data, dict):
            return None
        stage, failed_unit = data.get("stage"), data.get("failed_unit")
        if not isinstance(stage, str) or not stage or len(stage) > MAX_TEXT:
            return None
        if failed_unit is not None and (not isinstance(failed_unit, str) or len(failed_unit) > MAX_TEXT):
            return None
        release = data.get("release_id")  # D-535: the release the mDNS TXT already shows
        release = release if isinstance(release, str) and 0 < len(release) <= 64 else None
        return {"stage": stage, "failed_unit": failed_unit, "release_id": release}

    def status_inputs(self, svc: Any) -> dict[str, Any]:
        """What the root side cannot know: the live warning threshold, the overlaid device states and the live robot mode.

        Schema 2 (D-412) keeps every schema-1 key and adds the updater's idleness
        inputs. It also carries robot_id, core_process_id, and line_follow_steering_law
        so a device camera can invert the law this process loaded. All state keys
        come from one snapshot, so they describe one instant.
        """
        snapshot = _snapshot(svc)
        try:
            hardware = _hardware(svc, snapshot)
        except OSError:
            hardware = None
        devices = [{"id": row["id"], "state": row["state"], "product": row["product"]}
                   for row in (hardware["devices"] if hardware is not None else [])]
        line_config = getattr(getattr(svc, 'line_follow', None), 'config', None)
        law = (None if line_config is None else
               {key: getattr(line_config, key) for key in
                ('cruise_speed', 'max_linear', 'steering_gain', 'min_confidence')})
        return {"schema": 2, "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "robot_id": getattr(snapshot, 'robot_id', None), "core_process_id": os.getpid(),
                "line_follow_steering_law": law,
                "battery_warning_percent": _warning_percent(svc), "devices": devices,
                "robot_mode": _robot_mode(snapshot), "nav_state": _nav_state(snapshot),
                "swarm_role": _swarm_role(snapshot), **_idleness_inputs(snapshot),
                "calibration_active": (svc.calibration.current() is not None
                                       if getattr(svc, "calibration", None) is not None else None)}

    def write_face_inputs(self, svc: Any, content: dict[str, Any]) -> None:
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

    def write_status_inputs(self, svc: Any) -> None:
        """Replace the hand-over atomically (0644: rosy-boot-status is root, nothing in it is secret)."""
        cfg = (svc.config or {}).get("hardware_probe", {}) or {}
        path = str(cfg.get("status_inputs_path", STATUS_INPUTS_FILE))
        _write_private(path, json.dumps(self.status_inputs(svc), sort_keys=True) + "\n", 0o644, "status-inputs")
