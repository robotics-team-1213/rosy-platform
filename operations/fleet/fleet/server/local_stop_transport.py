"""Bounded Fleet client for same-host OMX StopLocal UDS fanout."""

from __future__ import annotations

import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core_common.protocol.schemas import LocalStopRearmRequest, LocalStopRequest


_INSTANCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")


class UnixLocalStopTransport:
    """Send one bounded stop frame; a local latch reply is not physical stop proof."""

    MAX_FRAME_BYTES = 64 * 1024

    def __init__(self, socket_root: Path | str = "/run/rosy/omx", *,
                 timeout_s: float = 0.25) -> None:
        self.socket_root = Path(socket_root).resolve()
        if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
                or not 0.01 <= float(timeout_s) <= 2.0):
            raise ValueError("UDS stop timeout must be between 10 ms and 2 s")
        self.timeout_s = float(timeout_s)

    def stop(self, *, workcell_id: str, instance_id: str, authority_epoch: int,
             dispatch_generation: int, reason: str = "FLEET_ESTOP") -> dict[str, Any]:
        if (not isinstance(instance_id, str) or not _INSTANCE_ID.fullmatch(instance_id)
                or instance_id in {".", ".."}):
            raise ValueError("invalid OMX instance id")
        request = LocalStopRequest(
            workcell_id=workcell_id, instance_id=instance_id,
            authority_epoch=authority_epoch, dispatch_generation=dispatch_generation,
            requested_at=datetime.now(timezone.utc), reason=reason,
        )
        document = {"version": 1, "operation": "StopLocal",
                    **request.model_dump(mode="json")}
        payload = self._exchange(instance_id, document)
        if payload is None or payload.get("status") != 200:
            error = payload.get("error") if isinstance(payload, Mapping) else None
            code = error.get("code") if isinstance(error, Mapping) else None
            return {"state": "UNKNOWN", "reason": code or "STOP_REQUEST_FAILED"}
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, Mapping):
            return {"state": "UNKNOWN", "reason": "STOP_SNAPSHOT_MISSING"}
        if (snapshot.get("workcell_id") != workcell_id
                or snapshot.get("instance_id") != instance_id
                or snapshot.get("authority_epoch") != authority_epoch
                or type(snapshot.get("dispatch_generation")) is not int
                or snapshot["dispatch_generation"] < dispatch_generation):
            return {"state": "UNKNOWN", "reason": "STOP_SNAPSHOT_IDENTITY_MISMATCH"}
        state = snapshot.get("state")
        return {
            "state": state if state in {"LOCAL_LATCHED", "REQUESTED", "UNKNOWN"}
            else "UNKNOWN",
            "reason": snapshot.get("reason", "STOP_STATE_UNAVAILABLE"),
            "source": snapshot.get("source"),
        }

    def rearm(self, *, workcell_id: str, instance_id: str, authority_epoch: int,
              dispatch_generation: int) -> dict[str, Any]:
        request = LocalStopRearmRequest(
            workcell_id=workcell_id, instance_id=instance_id,
            authority_epoch=authority_epoch, dispatch_generation=dispatch_generation,
        )
        payload = self._exchange(instance_id, {
            "version": 1, "operation": "RearmLocal",
            **request.model_dump(mode="json"),
        })
        if payload is None or payload.get("status") != 200:
            error = payload.get("error") if isinstance(payload, Mapping) else None
            code = error.get("code") if isinstance(error, Mapping) else None
            return {"state": "UNKNOWN", "reason": code or "REARM_REQUEST_FAILED"}
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, Mapping):
            return {"state": "UNKNOWN", "reason": "REARM_SNAPSHOT_MISSING"}
        if (snapshot.get("workcell_id") != workcell_id
                or snapshot.get("instance_id") != instance_id
                or type(snapshot.get("authority_epoch")) is not int
                or snapshot.get("authority_epoch") != authority_epoch
                or type(snapshot.get("dispatch_generation")) is not int
                or snapshot.get("dispatch_generation") != dispatch_generation):
            return {"state": "UNKNOWN", "reason": "REARM_SNAPSHOT_IDENTITY_MISMATCH"}
        return {"state": snapshot.get("state") if snapshot.get("state") == "OPEN"
                else "UNKNOWN", "reason": snapshot.get("reason", "REARM_UNCONFIRMED")}

    def _exchange(self, instance_id: str, document: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if (not isinstance(instance_id, str) or not _INSTANCE_ID.fullmatch(instance_id)
                or instance_id in {".", ".."}):
            raise ValueError("invalid OMX instance id")
        socket_path = (self.socket_root / instance_id / "control.sock").resolve()
        try:
            socket_path.relative_to(self.socket_root)
        except ValueError:
            raise ValueError("OMX socket path escapes the configured socket root") from None
        frame = json.dumps(document, sort_keys=True, separators=(",", ":"),
                           allow_nan=False).encode("utf-8") + b"\n"
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
        except (OSError, TimeoutError):
            return None
        finally:
            client.close()
        if len(response) > self.MAX_FRAME_BYTES or b"\n" not in response:
            return None
        line, trailing = bytes(response).split(b"\n", 1)
        if trailing:
            return None
        try:
            payload = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, Mapping) else None
