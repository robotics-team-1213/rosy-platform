"""Bounded same-host Fleet client for OMX Device Action UDS operations."""

from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from core_common.protocol.schemas import (
    ArmTransferCheckRequest, ArmTransferCheckResult, ArmTransferCheckRejection,
    DeviceActionReceipt,
    FleetActionGrant,
    FleetArmTransferGrant,
    FleetCellTransferGrant,
)
from core_common.protocol.arm_transfer_preflight import ARM_PREFLIGHT_REJECTION_STATUS

from .action_receipts import receipt_matches_grant

_INSTANCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
# One wire version per admitted kind. Phased kinds report ordered phase summaries
# (v2); a kind missing here has no local executor and is refused before any I/O.
_PROTOCOL_VERSION_BY_KIND = {"PICK_PLACE": 2, "CELL_TRANSFER": 2, "ARM_TRANSFER": 2}
ActionGrant = FleetActionGrant | FleetCellTransferGrant | FleetArmTransferGrant


class LocalActionUnavailable(TimeoutError):
    """The Fleet client cannot establish whether the local Action was accepted."""


class LocalActionRejected(ValueError):
    """The local API explicitly rejected the Action request before acceptance."""


class ArmPreflightRejected(LocalActionRejected):
    """A supported, typed read-only planning refusal from the owner."""

    def __init__(self, rejection: ArmTransferCheckRejection, status: int):
        super().__init__(rejection.code)
        self.code, self.reason, self.status = rejection.code, rejection.reason, status


class DeviceActionTransport(Protocol):
    def submit(self, grant: ActionGrant) -> DeviceActionReceipt: ...

    def get(self, grant: ActionGrant) -> DeviceActionReceipt | None: ...

    def cancel(self, grant: ActionGrant, *, reason: str) -> DeviceActionReceipt: ...


class UnixLocalActionTransport:
    """One request per bounded UDS connection; no retries are performed."""

    MAX_FRAME_BYTES = 64 * 1024

    def __init__(self, socket_root: Path | str = "/run/rosy/omx", *,
                 timeout_s: float = 0.25) -> None:
        self.socket_root = Path(socket_root).resolve()
        if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
                or not 0.01 <= float(timeout_s) <= 2.0):
            raise ValueError("UDS Action timeout must be between 10 ms and 2 s")
        self.timeout_s = float(timeout_s)

    def check_transfer(self, request: ArmTransferCheckRequest) -> ArmTransferCheckResult:
        request = ArmTransferCheckRequest.model_validate(request)
        response = self._exchange(request.instance_id, {
            "version": 2, "operation": "CheckTransfer", "transfer": request.model_dump(mode="json")})
        if (type(response.get("version")) is not int or response["version"] != 2
                or type(response.get("status")) is not int):
            raise LocalActionUnavailable("invalid owner preflight protocol")
        if response["status"] != 200:
            try:
                rejection = ArmTransferCheckRejection.model_validate(response.get("error"))
                if ARM_PREFLIGHT_REJECTION_STATUS[rejection.code] != response["status"]:
                    raise ValueError("planning rejection status mismatch")
            except (TypeError, ValueError, KeyError) as exc:
                raise LocalActionUnavailable("unsupported owner preflight response") from exc
            raise ArmPreflightRejected(rejection, response["status"])
        try:
            result = ArmTransferCheckResult.model_validate(response.get("check"))
            if result.request != request:
                raise ValueError("owner preflight response refers to another request")
        except (TypeError, ValueError) as exc:
            raise LocalActionUnavailable("invalid owner preflight facts") from exc
        return result

    def submit(self, grant: ActionGrant) -> DeviceActionReceipt:
        version = self._version(grant)
        return self._receipt(grant, {
            "version": version, "operation": "SubmitAction",
            "grant": grant.model_dump(mode="json"),
        })

    def get(self, grant: ActionGrant) -> DeviceActionReceipt | None:
        version = self._version(grant)
        response = self._exchange(grant.instance_id, {
            "version": version, "operation": "GetAction", "action_id": grant.action_id,
        })
        if response.get("version") != version:
            raise LocalActionUnavailable("local Action protocol version is unsupported")
        error = response.get("error")
        if (response.get("status") == 404 and isinstance(error, Mapping)
                and error.get("code") == "ACTION_NOT_FOUND"):
            return None  # only the owner's explicit "no such Action"; other 404s are errors
        return self._parse_receipt(grant, response)

    def cancel(self, grant: ActionGrant, *, reason: str) -> DeviceActionReceipt:
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 256:
            raise ValueError("cancel reason must be non-empty and at most 256 characters")
        version = self._version(grant)
        return self._receipt(grant, {
            "version": version, "operation": "CancelAction",
            "action_id": grant.action_id, "attempt_id": grant.attempt_id,
            "reason": reason,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        })

    def owner_identity(self, instance_id: str) -> Mapping[str, Any]:
        """The owner's self-reported identity (simulation flag, D-390 §5), read over the same UDS."""
        response = self._exchange(instance_id, {"version": 2, "operation": "GetOwnerIdentity"})
        if response.get("status") != 200 or not isinstance(response.get("identity"), Mapping):
            error = response.get("error") if isinstance(response.get("error"), Mapping) else {}
            raise LocalActionRejected(f"{error.get('code', 'OWNER_IDENTITY_UNAVAILABLE')}: "
                                      f"{error.get('message', 'owner identity is unavailable')}")
        return dict(response["identity"])

    def _receipt(self, grant: ActionGrant,
                 document: Mapping[str, Any]) -> DeviceActionReceipt:
        return self._parse_receipt(grant, self._exchange(grant.instance_id, document))

    @staticmethod
    def _version(grant: ActionGrant) -> int:
        version = _PROTOCOL_VERSION_BY_KIND.get(grant.action_kind)
        if version is None:
            raise ValueError(f"action kind {grant.action_kind!r} has no local Action protocol")
        return version

    @staticmethod
    def _parse_receipt(grant: ActionGrant,
                       response: Mapping[str, Any]) -> DeviceActionReceipt:
        version = UnixLocalActionTransport._version(grant)
        if response.get("version") != version:
            raise LocalActionUnavailable("local Action protocol version is unsupported")
        status = response.get("status")
        if status != 200:
            error = response.get("error")
            code = error.get("code") if isinstance(error, Mapping) else "LOCAL_ACTION_REJECTED"
            message = error.get("message") if isinstance(error, Mapping) else "local Action request failed"
            if type(status) is int and 400 <= status < 500:
                raise LocalActionRejected(f"{code}: {message}")
            raise LocalActionUnavailable(f"{code}: {message}")
        raw = response.get("receipt")
        try:
            receipt = DeviceActionReceipt.model_validate(raw)
        except (TypeError, ValueError) as exc:
            raise LocalActionUnavailable("local Action receipt is invalid") from exc
        if version == 2 and receipt.phase_summaries is None:
            raise LocalActionUnavailable("v2 local Action receipt is missing phase summaries")
        if version == 1 and receipt.phase_summaries is not None:
            raise LocalActionUnavailable("v1 local Action receipt contains v2 phase summaries")
        if not receipt_matches_grant(grant, receipt):
            raise LocalActionUnavailable("local Action receipt does not match the Fleet grant")
        return receipt

    def _exchange(self, instance_id: str,
                  document: Mapping[str, Any]) -> Mapping[str, Any]:
        if (not isinstance(instance_id, str) or not _INSTANCE_ID.fullmatch(instance_id)
                or instance_id in {".", ".."}):
            raise ValueError("invalid OMX instance id")
        socket_path = (self.socket_root / instance_id / "control.sock").resolve()
        try:
            socket_path.relative_to(self.socket_root)
        except ValueError:
            raise ValueError("OMX socket path escapes the configured socket root") from None
        frame = json.dumps(document, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
        if len(frame) > self.MAX_FRAME_BYTES:
            raise ValueError("local Action request exceeds 64 KiB")
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(self.timeout_s)
        try:
            client.connect(str(socket_path))
            client.sendall(frame)
            response = bytearray()
            while len(response) <= self.MAX_FRAME_BYTES:
                chunk = client.recv(min(4096, self.MAX_FRAME_BYTES + 1 - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
                if b"\n" in chunk:
                    break
        except (OSError, TimeoutError) as exc:
            raise LocalActionUnavailable("local Action transport outcome is unknown") from exc
        finally:
            client.close()
        if len(response) > self.MAX_FRAME_BYTES or b"\n" not in response:
            raise LocalActionUnavailable("local Action response frame is incomplete")
        line, trailing = bytes(response).split(b"\n", 1)
        if trailing:
            raise LocalActionUnavailable("local Action response contains trailing frames")
        try:
            payload = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalActionUnavailable("local Action response is invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise LocalActionUnavailable("local Action response is not an object")
        return payload


__all__ = [
    "ActionGrant", "DeviceActionTransport", "LocalActionRejected", "LocalActionUnavailable", "ArmPreflightRejected",
    "UnixLocalActionTransport",
]
