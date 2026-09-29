"""Versioned newline-framed local IPC API for one OMX workcell owner."""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
from pathlib import Path
from typing import Any, Mapping

from core_common.protocol.schemas import DeviceActionCancelRequest, FleetActionGrant

from .action_runner import ActionRunner, action_grant_digest


class ActionApi:
    """Dispatch requests after deriving the caller identity from Unix peer UID."""

    VERSION = 1
    MAX_FRAME_BYTES = 64 * 1024

    def __init__(self, runner: ActionRunner, *, stop_api: Any | None = None) -> None:
        self.runner = runner
        self.stop_api = stop_api

    @staticmethod
    def _encode(document: Mapping[str, Any]) -> bytes:
        return json.dumps(document, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")

    @staticmethod
    def _error(code: str, message: str, *, status: int) -> dict[str, Any]:
        return {"version": 1, "status": status,
                "error": {"code": code, "message": message}}

    def dispatch(self, request: Mapping[str, Any], *, peer_uid: int) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            return self._error("INVALID_REQUEST", "request must be a JSON object", status=400)
        try:
            if len(self._encode(request)) > self.MAX_FRAME_BYTES:
                return self._error("FRAME_TOO_LARGE", "request exceeds 64 KiB", status=413)
        except (TypeError, ValueError):
            return self._error("INVALID_JSON", "request must be finite JSON", status=400)
        if not isinstance(request, Mapping) or request.get("version") != self.VERSION:
            return self._error("UNSUPPORTED_VERSION", "version must equal 1", status=400)
        operation = request.get("operation")
        try:
            if operation == "SubmitAction":
                if set(request) != {"version", "operation", "grant"}:
                    raise ValueError("SubmitAction contains unsupported fields")
                grant = FleetActionGrant.model_validate(request["grant"])
                receipt = self.runner.submit(grant, peer_uid=peer_uid)
                return {"version": 1, "status": 200, "receipt": receipt}
            if operation == "GetAction":
                if set(request) != {"version", "operation", "action_id"}:
                    raise ValueError("GetAction contains unsupported fields")
                receipt = self.runner.get(request["action_id"], peer_uid=peer_uid)
                if receipt is None:
                    return self._error("ACTION_NOT_FOUND", "Action is unavailable", status=404)
                return {"version": 1, "status": 200, "receipt": receipt}
            if operation == "CancelAction":
                expected = {"version", "operation", "action_id", "attempt_id",
                            "reason", "requested_at"}
                if set(request) != expected:
                    raise ValueError("CancelAction contains unsupported fields")
                cancel = DeviceActionCancelRequest.model_validate({
                    key: request[key] for key in expected - {"version", "operation"}
                })
                receipt = self.runner.cancel(
                    cancel.action_id, cancel.attempt_id, peer_uid=peer_uid,
                )
                return {"version": 1, "status": 200, "receipt": receipt}
            if operation in {"StopLocal", "GetStopState"}:
                if self.stop_api is None:
                    return self._error("STOP_API_NOT_CONFIGURED",
                                       "local stop adapter is unavailable", status=503)
                return self.stop_api.dispatch(request, peer_uid=peer_uid)
            return self._error("UNKNOWN_OPERATION", "operation is not supported", status=404)
        except PermissionError as exc:
            return self._error("PEER_NOT_ALLOWED" if "peer" in str(exc).lower()
                               else "GRANT_REJECTED", str(exc), status=403)
        except KeyError:
            return self._error("ACTION_NOT_FOUND", "Action is unavailable", status=404)
        except (TypeError, ValueError) as exc:
            return self._error("INVALID_REQUEST", str(exc), status=400)
        except Exception:
            return self._error("LOCAL_ACTION_ERROR", "local Action processing failed", status=500)

    def handle_connection(self, connection: socket.socket) -> None:
        """Serve one request frame and derive its UID from SO_PEERCRED (Linux)."""
        peer = connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"),
        )
        _, peer_uid, _ = struct.unpack("3i", peer)
        frame = bytearray()
        while len(frame) <= self.MAX_FRAME_BYTES:
            chunk = connection.recv(min(4096, self.MAX_FRAME_BYTES + 1 - len(frame)))
            if not chunk:
                break
            frame.extend(chunk)
            if b"\n" in chunk:
                break
        if len(frame) > self.MAX_FRAME_BYTES or b"\n" not in frame:
            response = self._error("FRAME_TOO_LARGE", "one newline frame up to 64 KiB is required",
                                   status=413)
        else:
            line, trailing = bytes(frame).split(b"\n", 1)
            if trailing:
                response = self._error("INVALID_FRAMING", "one request per connection", status=400)
            else:
                try:
                    request = json.loads(line.decode("utf-8"))
                    if not isinstance(request, Mapping):
                        raise ValueError("request must be a JSON object")
                    response = self.dispatch(request, peer_uid=peer_uid)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    response = self._error("INVALID_JSON", "request frame is not valid JSON",
                                           status=400)
        connection.sendall(self._encode(response) + b"\n")


class UnixActionServer:
    """Bind one pre-provisioned per-instance socket; never create its directory."""

    def __init__(self, api: ActionApi, socket_path: Path | str, *,
                 socket_mode: int = 0o660) -> None:
        self.api = api
        self.socket_path = Path(socket_path)
        if not self.socket_path.is_absolute():
            raise ValueError("UDS socket path must be absolute")
        if socket_mode != 0o660:
            raise ValueError("UDS socket mode is fixed at 0660")
        self.socket_mode = socket_mode
        self._stop = threading.Event()
        self._socket: socket.socket | None = None

    def serve_forever(self) -> None:
        if not hasattr(socket, "SO_PEERCRED"):
            raise RuntimeError("SO_PEERCRED is required for local Action IPC")
        if not self.socket_path.parent.is_dir():
            raise RuntimeError("UDS parent directory must be provisioned by the service manager")
        if self.socket_path.exists():
            raise FileExistsError(
                "UDS socket path already exists; stale paths require operator review"
            )
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket = listener
        try:
            listener.bind(str(self.socket_path))
            os.chmod(self.socket_path, self.socket_mode)
            listener.listen(8)
            listener.settimeout(0.5)
            while not self._stop.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    connection.settimeout(2.0)
                    try:
                        self.api.handle_connection(connection)
                    except TimeoutError:
                        continue
        finally:
            listener.close()
            self._socket = None
            if self.socket_path.exists() and self.socket_path.is_socket():
                self.socket_path.unlink()

    def stop(self) -> None:
        self._stop.set()
        listener = self._socket
        if listener is not None:
            listener.close()


__all__ = ["ActionApi", "UnixActionServer", "action_grant_digest"]
