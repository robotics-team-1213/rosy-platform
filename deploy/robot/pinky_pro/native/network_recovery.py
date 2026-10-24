"""Boot/AP-scoped network recovery authority, independent of CORE login tokens."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time

ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
LIFETIME = 600


class RecoveryError(Exception):
    """A fixed public error code; never include backend exceptions or inputs."""


@dataclass(frozen=True)
class RecoveryState:
    boot_id: str
    ap_epoch: str
    ap_address: str
    device_uid: str
    identity_serial: str
    hardware_serial: str
    firstboot_state: str
    core_healthy: bool
    handoff_supported: bool

    def eligible(self) -> bool:
        try:
            address = ipaddress.IPv4Address(self.ap_address)
        except (ValueError, TypeError):
            return False
        return bool(self.boot_id and self.ap_epoch and self.device_uid and self.identity_serial
                    and self.identity_serial == self.hardware_serial
                    and not (address.is_unspecified or address.is_loopback or address.is_multicast)
                    and not self.core_healthy
                    and self.firstboot_state in {"site_wifi_unreachable", "FAILED", "held"})

    def scope(self) -> list[str]:
        return [self.boot_id, self.ap_epoch, self.ap_address, self.device_uid, self.identity_serial]


def _digest(code: str, salt: bytes) -> str:
    return hashlib.scrypt(code.encode("ascii"), salt=salt, n=2**14, r=8, p=1,
                          dklen=32, maxmem=64 * 1024 * 1024).hex()


def issue_code(state: RecoveryState, *, now: float | None = None,
               uid: int | None = None) -> tuple[dict, str]:
    """Root orchestration persists verifier separately from physical display text."""
    if (os.geteuid() if uid is None else uid) != 0:
        raise PermissionError("root_required")
    if not state.eligible():
        raise RecoveryError("recovery_unavailable")
    code = "".join(secrets.choice(ALPHABET) for _ in range(8))
    salt = secrets.token_bytes(16)
    return {"id": secrets.token_hex(16), "scope": "network-recovery", "context": state.scope(),
            "deadline": (time.monotonic() if now is None else now) + LIFETIME,
            "salt": salt.hex(), "digest": _digest(code, salt)}, code


class RecoveryCoordinator:
    def __init__(self, state_supplier, network_call, record: dict, *, auth_state_path: Path,
                 clock=time.monotonic):
        self.state_supplier = state_supplier
        self.network_call = network_call
        self.record = dict(record)
        self.auth_state_path = Path(auth_state_path)
        self.clock = clock
        self._closed = False
        self._session = ""
        self._csrf = ""
        self._deadline = 0.0

    def close(self) -> None:
        self._closed = True
        self._session = self._csrf = ""

    def active_state(self) -> RecoveryState | None:
        try:
            state = self.state_supplier()
            if (self._closed or not state.eligible()
                    or self.record.get("scope") != "network-recovery"
                    or state.scope() != self.record.get("context")):
                self.close()
                return None
            return state
        except Exception:
            self.close()
            return None

    @contextmanager
    def _attempt(self):
        """Lock and fsync before responding; partial writes fail closed on restart."""
        import fcntl
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        descriptor = os.open(self.auth_state_path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise RecoveryError("authentication_unavailable")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            raw = os.read(descriptor, 4097)
            stored = json.loads(raw) if raw else {}
            if not isinstance(stored, dict) or len(raw) > 4096:
                raise RecoveryError("authentication_unavailable")
            if stored.get("id") != self.record["id"]:
                stored = {"id": self.record["id"], "attempts": 0, "used": False}
            if (type(stored.get("attempts")) is not int or not 0 <= stored["attempts"] <= 5
                    or type(stored.get("used")) is not bool):
                raise RecoveryError("authentication_unavailable")
            yield stored
            data = json.dumps(stored, separators=(",", ":")).encode("ascii")
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.write(descriptor, data)
            os.ftruncate(descriptor, len(data))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def exchange(self, code: str) -> tuple[str, str]:
        if self.active_state() is None:
            raise RecoveryError("recovery_unavailable")
        try:
            if self.clock() >= self.record["deadline"]:
                raise RecoveryError("code_expired")
            with self._attempt() as state:
                if state["used"] or state["attempts"] >= 5:
                    raise RecoveryError("code_unavailable")
                normalized = code.replace("-", "").strip().upper() if isinstance(code, str) else ""
                matched = (len(normalized) == 8 and set(normalized) <= set(ALPHABET)
                           and hmac.compare_digest(_digest(normalized, bytes.fromhex(self.record["salt"])),
                                                   self.record["digest"]))
                state["attempts"] += not matched
                state["used"] = bool(matched)
            if not matched:
                raise RecoveryError("code_invalid")
        except RecoveryError:
            raise
        except Exception:
            raise RecoveryError("authentication_unavailable") from None
        self._session, self._csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self._deadline = self.clock() + LIFETIME
        return self._session, self._csrf

    def authenticate(self, session: str, csrf: str | None = None) -> RecoveryState:
        state = self.active_state()
        if state is None:
            raise RecoveryError("recovery_unavailable")
        if (not self._session or not isinstance(session, str)
                or not hmac.compare_digest(session, self._session) or self.clock() >= self._deadline):
            raise RecoveryError("session_expired")
        if csrf is not None and (not isinstance(csrf, str) or not hmac.compare_digest(csrf, self._csrf)):
            raise RecoveryError("csrf_invalid")
        return state

    def session_info(self, session: str) -> dict:
        state = self.authenticate(session)
        return {"csrf": self._csrf, "write_available": state.handoff_supported}

    def _network(self, command: str, payload: dict) -> dict:
        try:
            result = self.network_call(command, payload)
            if not isinstance(result, dict):
                raise ValueError()
            # Explicit public fields only; raw stderr/credentials cannot cross this boundary.
            return {key: value for key, value in result.items()
                    if key in {"job_id", "request_id", "state", "code", "ssid", "ipv4", "profile_uuid"}
                    and isinstance(value, str) and len(value) <= 128}
        except Exception:
            raise RecoveryError("network_unavailable") from None

    @staticmethod
    def _request_id(request_id: str) -> None:
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", request_id):
            raise RecoveryError("request_invalid")

    def status(self, session: str, request_id: str | None = None) -> dict:
        self.authenticate(session)
        if request_id is not None:
            self._request_id(request_id)
        return self._network("network.status", {"request_id": request_id} if request_id else {})

    def connect(self, session: str, csrf: str, ssid: str, psk: str, request_id: str) -> dict:
        state = self.authenticate(session, csrf)
        if not state.handoff_supported:
            raise RecoveryError("image_required")
        from network_transaction import validate_request
        try:
            validate_request(ssid, psk, request_id)
        except (ValueError, TypeError, AttributeError):
            raise RecoveryError("network_input_invalid") from None
        return self._network("network.connect", {"ssid": ssid, "psk": psk, "request_id": request_id})

    def start(self, session: str, csrf: str, request_id: str) -> dict:
        state = self.authenticate(session, csrf)
        if not state.handoff_supported:
            raise RecoveryError("image_required")
        self._request_id(request_id)
        return self._network("network.start", {"request_id": request_id})
