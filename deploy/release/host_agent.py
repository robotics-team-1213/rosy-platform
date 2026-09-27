"""The Host Agent: the one ROSY process that holds host privilege (WP-4).

CORE is the robot API and the command boundary, and it must not also be a host
administrator — an internet-facing HTTP surface and root in one process is
what ADR D-22 forbids. So changing a network profile, activating a release and
rebooting live here instead, behind a contract that offers no arbitrary shell.

The contract is docs/reference/rosy-host-agent-contract.md. This module is its
implementation, split in two so that the part that decides *whether* to act is
testable everywhere:

``HostAgent``
    Pure decision and dispatch. Takes a request line, returns a response line.
    Every refusal — unknown command, wrong role, unconfirmed, unlisted value,
    a device under recovery hold — is decided here, with no socket and no
    privilege involved.
``serve_forever`` / ``check_peer_credentials``
    The thin POSIX transport. Owns the socket, its ownership and mode, and the
    kernel-supplied peer identity.

Actions are injected (:class:`HostCommands`), so the tests exercise every
refusal and every audit record without running ``nmcli``, ``systemctl`` or
``reboot`` anywhere.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

SCHEMA_VERSION = 1

#: A request line longer than this is refused unread. The socket is reachable
#: by anything running as ROSY_UID, so an unbounded line is an easy way to
#: make the agent allocate until the device dies.
MAX_REQUEST_BYTES = 64 * 1024

#: How many completed requests to remember for idempotency. Bounded so a long
#: -running agent cannot grow without limit; the dashboard only ever retries a
#: request it has just sent.
IDEMPOTENCY_CAPACITY = 256


class Role(str, Enum):
    VIEWER = "viewer"
    ADMINISTRATOR = "administrator"


@dataclass(frozen=True)
class CommandSpec:
    """One entry in the allowlist.

    ``params`` is exhaustive: a request carrying any other parameter is
    refused rather than having the extra ignored. Ignoring an unexpected
    parameter is how a caller comes to believe it did something.
    """

    name: str
    role: Role
    requires_confirmation: bool
    params: frozenset[str] = frozenset()


ALLOWLIST: dict[str, CommandSpec] = {
    spec.name: spec
    for spec in (
        CommandSpec("network.status", Role.VIEWER, False),
        CommandSpec("network.apply_profile", Role.ADMINISTRATOR, True, frozenset({"profile_id"})),
        CommandSpec("network.set_mode", Role.ADMINISTRATOR, True, frozenset({"mode"})),
        CommandSpec("network.connect", Role.ADMINISTRATOR, True, frozenset({"ssid", "psk"})),
        CommandSpec("release.status", Role.VIEWER, False),
        CommandSpec("release.install", Role.ADMINISTRATOR, True, frozenset({"release_id"})),
        CommandSpec("release.rollback", Role.ADMINISTRATOR, True),
        CommandSpec("release.clear_hold", Role.ADMINISTRATOR, True),
        CommandSpec("service.status", Role.VIEWER, False, frozenset({"unit"})),
        CommandSpec("system.reboot", Role.ADMINISTRATOR, True),
    )
}

#: Identifiers are matched against an enumerated set, but they are shape-checked
#: first so a malformed value is refused before it is compared to anything.
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")

#: Keys whose values never appear in an audit record. apply_profile still takes
#: a profile id; network.connect takes a PSK that must die in this process.
_REDACTED_KEYS = re.compile(
    r"psk|passphrase|passwo?rd|secret|token|private[_-]?key|credential",
    re.IGNORECASE,
)
_REDACTED = "[redacted]"

#: Dashboard operating modes (ADR D-26 / D-124). Not NetworkManager profile ids.
_OPERATING_MODES = frozenset({"SITE_STA", "RELAY_AP_STA"})

#: Printable SSID, same bound as deploy/release/network.py SetupRequest.
_SSID = re.compile(r"^[\x20-\x7e]{1,32}$")


class HostCommands(Protocol):
    """The privileged actions, injected so refusals can be tested in isolation."""

    def network_status(self) -> dict: ...
    def apply_network_profile(self, profile_id: str) -> dict: ...
    def set_network_mode(self, mode: str) -> dict: ...
    def connect_wifi(self, ssid: str, psk: str) -> dict: ...
    def release_status(self) -> dict: ...
    def install_release(self, release_id: str) -> dict: ...
    def rollback_release(self) -> dict: ...
    def clear_recovery_hold(self) -> dict: ...
    def service_status(self, unit: str) -> dict: ...
    def reboot(self) -> dict: ...


@dataclass
class AuditRecord:
    at: str
    request_id: str | None
    idempotency_key: str | None
    command: str | None
    actor: dict
    code: str
    ok: bool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _observed_now() -> str:
    """UTC completion time for a synchronous host status read, not an audit time."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def redact(value: Any) -> Any:
    """Strip anything secret-shaped before it reaches the audit log."""
    if isinstance(value, dict):
        return {
            key: (_REDACTED if _REDACTED_KEYS.search(str(key)) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class _Idempotency:
    """Remembers completed responses, bounded and insertion-ordered."""

    def __init__(self, capacity: int = IDEMPOTENCY_CAPACITY) -> None:
        self._capacity = capacity
        self._entries: dict[str, dict] = {}

    def get(self, key: str) -> dict | None:
        return self._entries.get(key)

    def put(self, key: str, response: dict) -> None:
        self._entries[key] = response
        while len(self._entries) > self._capacity:
            self._entries.pop(next(iter(self._entries)))


class HostAgent:
    """Decides whether to act, then acts. One request line in, one line out."""

    def __init__(
        self,
        commands: HostCommands,
        *,
        allowed_profiles: Sequence[str],
        allowed_units: Sequence[str],
        recovery_hold: Callable[[], dict | None] = lambda: None,
        audit: Callable[[AuditRecord], None] | None = None,
    ) -> None:
        self._commands = commands
        self._allowed_profiles = frozenset(allowed_profiles)
        self._allowed_units = frozenset(allowed_units)
        self._recovery_hold = recovery_hold
        self._audit = audit or (lambda _record: None)
        self._idempotency = _Idempotency()

    # --- the wire ---------------------------------------------------------

    def handle_line(self, line: str | bytes) -> str:
        """Parse, decide, act. Never raises; a fault is a response."""
        if isinstance(line, str):
            raw = line.encode("utf-8")
        else:
            raw = line

        if len(raw) > MAX_REQUEST_BYTES:
            return self._render(
                None, "HOST_AGENT_REQUEST_TOO_LARGE",
                f"request exceeds {MAX_REQUEST_BYTES} bytes",
                "요청을 나누어 보내십시오.", command=None, actor={},
            )

        try:
            request = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return self._render(
                None, "HOST_AGENT_MALFORMED_REQUEST", str(exc),
                "요청이 한 줄의 UTF-8 JSON 인지 확인하십시오.", command=None, actor={},
            )

        if not isinstance(request, dict):
            return self._render(
                None, "HOST_AGENT_MALFORMED_REQUEST", "expected a JSON object",
                "요청이 한 줄의 UTF-8 JSON 객체인지 확인하십시오.", command=None, actor={},
            )

        return json.dumps(self.handle(request), ensure_ascii=False)

    # --- the decision -----------------------------------------------------

    def handle(self, request: dict) -> dict:
        """Decide and act on an already-parsed request."""
        request_id = request.get("request_id")
        command_name = request.get("command")
        actor = request.get("actor") if isinstance(request.get("actor"), dict) else {}

        def refuse(code: str, detail: str, recovery: str) -> dict:
            return json.loads(
                self._render(request_id, code, detail, recovery, command=command_name, actor=actor)
            )

        if request.get("schema_version") != SCHEMA_VERSION:
            return refuse(
                "HOST_AGENT_SCHEMA_UNKNOWN",
                f"request schema {request.get('schema_version')!r} is not implemented",
                "CORE 와 Host Agent 의 버전이 맞는지 확인하십시오.",
            )

        if not isinstance(request_id, str) or not _IDENTIFIER.match(request_id):
            return refuse(
                "HOST_AGENT_MALFORMED_REQUEST",
                f"request_id is missing or malformed: {request_id!r}",
                "요청마다 고유한 request_id 를 붙이십시오.",
            )

        spec = ALLOWLIST.get(command_name) if isinstance(command_name, str) else None
        if spec is None:
            # No fuzzy matching: a command this build does not implement is a
            # command it must not approximate.
            return refuse(
                "HOST_AGENT_COMMAND_UNKNOWN",
                f"{command_name!r} is not in the allowlist",
                f"허용된 명령: {', '.join(sorted(ALLOWLIST))}",
            )

        # Replay before any side effect: a retry must not become a second reboot.
        key = request.get("idempotency_key")
        if key is not None:
            if not isinstance(key, str) or not _IDENTIFIER.match(key):
                return refuse(
                    "HOST_AGENT_MALFORMED_REQUEST",
                    f"idempotency_key is malformed: {key!r}",
                    "idempotency_key 는 식별자 형식이어야 합니다.",
                )
            remembered = self._idempotency.get(key)
            if remembered is not None:
                replay = dict(remembered)
                replay["request_id"] = request_id
                replay["replayed"] = True
                self._record(request_id, key, command_name, actor, replay["code"], replay["ok"])
                return replay

        role_error = self._check_role(spec, actor)
        if role_error is not None:
            return refuse(*role_error)

        if spec.requires_confirmation and request.get("confirmed") is not True:
            return refuse(
                "HOST_AGENT_CONFIRMATION_REQUIRED",
                f"{spec.name} is destructive and was not confirmed",
                "대시보드에서 재확인한 뒤 다시 요청하십시오.",
            )

        params = request.get("params") or {}
        if not isinstance(params, dict):
            return refuse(
                "HOST_AGENT_MALFORMED_REQUEST", "params must be an object",
                "params 를 객체로 보내십시오.",
            )
        param_error = self._check_params(spec, params)
        if param_error is not None:
            return refuse(*param_error)

        if spec.name == "release.install":
            hold = self._recovery_hold()
            if hold is not None:
                return refuse(
                    "RECOVERY_HELD",
                    f"device is held for recovery: {hold.get('detail', 'no detail')}",
                    "release.clear_hold 로 홀드를 해제한 뒤 다시 설치하십시오.",
                )

        response = self._execute(request_id, spec, params, actor)
        if key is not None and response.get("ok"):
            self._idempotency.put(key, response)
        return response

    # --- checks -----------------------------------------------------------

    def _check_role(self, spec: CommandSpec, actor: dict) -> tuple[str, str, str] | None:
        raw = actor.get("role")
        try:
            role = Role(raw)
        except ValueError:
            return (
                "HOST_AGENT_ROLE_UNKNOWN",
                f"actor role {raw!r} is not recognised",
                "CORE 가 viewer 또는 administrator 를 실어 보내야 합니다.",
            )
        if spec.role is Role.ADMINISTRATOR and role is not Role.ADMINISTRATOR:
            return (
                "HOST_AGENT_ROLE_INSUFFICIENT",
                f"{spec.name} requires administrator, actor is {role.value}",
                "관리자 권한으로 로그인한 뒤 다시 시도하십시오.",
            )
        return None

    def _check_params(self, spec: CommandSpec, params: dict) -> tuple[str, str, str] | None:
        unexpected = sorted(set(params) - spec.params)
        if unexpected:
            # Includes any attempt to pass a path: no command takes one, so an
            # unexpected key is refused rather than dropped.
            return (
                "HOST_AGENT_PARAM_UNKNOWN",
                f"{spec.name} does not take {unexpected}",
                f"허용된 파라미터: {sorted(spec.params) or '없음'}",
            )

        missing = sorted(spec.params - set(params))
        if missing:
            return (
                "HOST_AGENT_PARAM_MISSING",
                f"{spec.name} requires {missing}",
                f"필수 파라미터: {sorted(spec.params)}",
            )

        for name, value in params.items():
            if name == "psk":
                if not isinstance(value, str) or not 8 <= len(value) <= 63:
                    return (
                        "HOST_AGENT_PARAM_INVALID",
                        "psk length is invalid",
                        "a WPA2 passphrase is 8 to 63 characters",
                    )
                continue
            if name == "ssid":
                if not isinstance(value, str) or not _SSID.match(value):
                    return (
                        "HOST_AGENT_PARAM_INVALID",
                        f"ssid is not a well-formed SSID: {value!r}",
                        "SSID 는 1–32자의 인쇄 가능 문자입니다.",
                    )
                continue
            if name == "mode":
                if not isinstance(value, str) or value not in _OPERATING_MODES:
                    return (
                        "HOST_AGENT_MODE_UNKNOWN",
                        f"{value!r} is not an operating mode",
                        f"허용된 모드: {sorted(_OPERATING_MODES)}",
                    )
                continue
            if not isinstance(value, str) or not _IDENTIFIER.match(value):
                return (
                    "HOST_AGENT_PARAM_INVALID",
                    f"{name} is not a well-formed identifier: {value!r}",
                    "식별자는 영숫자와 . _ - @ 만 사용합니다.",
                )

        if "profile_id" in params and params["profile_id"] not in self._allowed_profiles:
            return (
                "HOST_AGENT_PROFILE_UNKNOWN",
                f"{params['profile_id']!r} is not a registered network profile",
                f"등록된 프로파일: {sorted(self._allowed_profiles)}",
            )
        if "unit" in params and params["unit"] not in self._allowed_units:
            return (
                "HOST_AGENT_UNIT_UNKNOWN",
                f"{params['unit']!r} is not an inspectable unit",
                f"조회 가능한 unit: {sorted(self._allowed_units)}",
            )
        return None

    # --- action -----------------------------------------------------------

    def _execute(self, request_id: str, spec: CommandSpec, params: dict, actor: dict) -> dict:
        actions: dict[str, Callable[[], dict]] = {
            "network.status": self._commands.network_status,
            "network.apply_profile": lambda: self._commands.apply_network_profile(params["profile_id"]),
            "network.set_mode": lambda: self._commands.set_network_mode(params["mode"]),
            "network.connect": lambda: self._commands.connect_wifi(params["ssid"], params["psk"]),
            "release.status": self._commands.release_status,
            "release.install": lambda: self._commands.install_release(params["release_id"]),
            "release.rollback": self._commands.rollback_release,
            "release.clear_hold": self._commands.clear_recovery_hold,
            "service.status": lambda: self._commands.service_status(params["unit"]),
            "system.reboot": self._commands.reboot,
        }

        try:
            data = actions[spec.name]()
        except Exception as exc:  # noqa: BLE001 - a fault must become a response
            return json.loads(
                self._render(
                    request_id, "HOST_AGENT_COMMAND_FAILED",
                    f"{spec.name} failed: {exc}",
                    "로그를 확인하고 다시 시도하십시오.",
                    command=spec.name, actor=actor,
                )
            )

        observed_at = _observed_now() if spec.name in {"network.status", "release.status"} else None
        self._record(request_id, None, spec.name, actor, "OK", True)
        response = {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "ok": True,
            "code": "OK",
            "detail": "",
            "recovery": "",
            "data": redact(data) if isinstance(data, dict) else data,
        }
        if observed_at is not None:
            response["observed_at"] = observed_at
        return response

    # --- rendering and audit ---------------------------------------------

    def _render(
        self, request_id: str | None, code: str, detail: str, recovery: str,
        *, command: str | None, actor: dict,
    ) -> str:
        self._record(request_id, None, command, actor, code, False)
        return json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "request_id": request_id,
                "ok": False,
                "code": code,
                "detail": detail,
                "recovery": recovery,
            },
            ensure_ascii=False,
        )

    def _record(
        self, request_id: str | None, key: str | None, command: str | None,
        actor: dict, code: str, ok: bool,
    ) -> None:
        self._audit(
            AuditRecord(
                at=_now(),
                request_id=request_id,
                idempotency_key=key,
                command=command,
                actor=redact(actor),
                code=code,
                ok=ok,
            )
        )


# --- audit sink ------------------------------------------------------------


@dataclass
class JsonlAudit:
    """Append every decision, successful or not, one JSON object per line."""

    path: Path
    records: list[dict] = field(default_factory=list)

    def __call__(self, record: AuditRecord) -> None:
        entry = redact(
            {
                "at": record.at,
                "request_id": record.request_id,
                "idempotency_key": record.idempotency_key,
                "command": record.command,
                "actor": record.actor,
                "code": record.code,
                "ok": record.ok,
            }
        )
        self.records.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
