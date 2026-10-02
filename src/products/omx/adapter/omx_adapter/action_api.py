"""Versioned newline-framed local IPC API for one OMX workcell owner."""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
from pathlib import Path
from typing import Any, Callable, Mapping

from core_common.protocol.schemas import (
    DeviceActionCancelRequest,
    LocalStopQuery,
    LocalStopRearmRequest,
    LocalStopRequest,
    StopRequestSource,
)

from .action_runner import ActionRunner, action_grant_digest, parse_action_grant
from .local_stop import LocalStopBlocked, LocalStopController

# A phase-runner-only kind is never journaled from a v1 frame, whose reply drops the
# ordered phase summaries Fleet needs to reconcile it (D-403 §2).
MIN_SUBMIT_VERSION_BY_KIND = {"CELL_TRANSFER": 2}


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
    def _error(code: str, message: str, *, status: int,
               version: int = 1) -> dict[str, Any]:
        # Errors answer with the version of the request they reject; the
        # default 1 is only for frames rejected before version validation
        # (bad JSON, framing, unsupported version) where no version is known.
        return {"version": version, "status": status,
                "error": {"code": code, "message": message}}

    @staticmethod
    def _success(version: int, receipt: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(receipt)
        if version == 1:
            payload.pop("phase_summaries", None)
        return {"version": version, "status": 200, "receipt": payload}

    def dispatch(self, request: Mapping[str, Any], *, peer_uid: int) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            return self._error("INVALID_REQUEST", "request must be a JSON object", status=400)
        try:
            if len(self._encode(request)) > self.MAX_FRAME_BYTES:
                return self._error("FRAME_TOO_LARGE", "request exceeds 64 KiB", status=413)
        except (TypeError, ValueError):
            return self._error("INVALID_JSON", "request must be finite JSON", status=400)
        version = request.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version not in {1, 2}:
            return self._error("UNSUPPORTED_VERSION", "version must equal 1 or 2", status=400)
        operation = request.get("operation")
        try:
            if operation == "SubmitAction":
                if set(request) != {"version", "operation", "grant"}:
                    raise ValueError("SubmitAction contains unsupported fields")
                grant = parse_action_grant(request["grant"])
                if version < MIN_SUBMIT_VERSION_BY_KIND.get(grant.action_kind, 1):
                    return self._error("UNSUPPORTED_VERSION",
                                       f"{grant.action_kind} requires protocol version 2",
                                       status=400, version=version)
                receipt = self.runner.submit(grant, peer_uid=peer_uid)
                return self._success(version, receipt)
            if operation == "GetAction":
                if set(request) != {"version", "operation", "action_id"}:
                    raise ValueError("GetAction contains unsupported fields")
                receipt = self.runner.get(request["action_id"], peer_uid=peer_uid)
                if receipt is None:
                    return self._error("ACTION_NOT_FOUND", "Action is unavailable",
                                       status=404, version=version)
                return self._success(version, receipt)
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
                return self._success(version, receipt)
            if operation in {"StopLocal", "GetStopState", "RearmLocal"}:
                if version != 1:
                    return self._error("UNSUPPORTED_VERSION",
                                       "stop operations use protocol version 1",
                                       status=400, version=version)
                if self.stop_api is None:
                    return self._error("STOP_API_NOT_CONFIGURED",
                                       "local stop adapter is unavailable", status=503)
                return self.stop_api.dispatch(request, peer_uid=peer_uid)
            return self._error("UNKNOWN_OPERATION", "operation is not supported",
                               status=404, version=version)
        except PermissionError as exc:
            return self._error("PEER_NOT_ALLOWED" if "peer" in str(exc).lower()
                               else "GRANT_REJECTED", str(exc), status=403,
                               version=version)
        except KeyError:
            return self._error("ACTION_NOT_FOUND", "Action is unavailable",
                               status=404, version=version)
        except (TypeError, ValueError) as exc:
            return self._error("INVALID_REQUEST", str(exc), status=400,
                               version=version)
        except Exception:
            return self._error("LOCAL_ACTION_ERROR", "local Action processing failed",
                               status=500, version=version)

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


class LocalStopApi:
    """Stop/read API whose source is derived from an allowlisted peer UID."""

    def __init__(self, controller: LocalStopController, *,
                 source_by_peer_uid: Mapping[int, StopRequestSource],
                 cancel_active: Callable[[int], object] | None = None,
                 fleet_fence_current: Callable[[int, int], bool] | None = None) -> None:
        self.controller = controller
        self.source_by_peer_uid = dict(source_by_peer_uid)
        self.cancel_active = cancel_active
        self.fleet_fence_current = fleet_fence_current or (lambda _epoch, _generation: False)

    @staticmethod
    def _response(status: int, *, snapshot: Mapping[str, Any] | None = None,
                  cancellations: object = None,
                  error: Mapping[str, str] | None = None) -> dict[str, Any]:
        response: dict[str, Any] = {"version": 1, "status": status}
        if snapshot is not None:
            response["snapshot"] = dict(snapshot)
        if cancellations is not None:
            response["cancellations"] = cancellations
        if error is not None:
            response["error"] = dict(error)
        return response

    def dispatch(self, request: Mapping[str, Any], *, peer_uid: int) -> dict[str, Any]:
        source = self.source_by_peer_uid.get(peer_uid)
        if source is None:
            return self._response(403, error={
                "code": "PEER_NOT_ALLOWED", "message": "peer UID cannot use stop API",
            })
        try:
            operation = request.get("operation")
            if operation == "StopLocal":
                expected = {"version", "operation", "workcell_id", "instance_id",
                            "authority_epoch", "dispatch_generation", "requested_at", "reason"}
                if set(request) != expected:
                    raise ValueError("StopLocal contains unsupported fields")
                stop_request = LocalStopRequest.model_validate({
                    key: request[key] for key in expected - {"version", "operation"}
                })
                cancellations = []
                callback = None
                if self.cancel_active is not None:
                    def cancel_active() -> None:
                        cancellations.extend(self.cancel_active(peer_uid) or [])

                    callback = cancel_active
                snapshot = self.controller.trip(
                    stop_request, source=source, cancel_active=callback,
                )
                return self._response(
                    200, snapshot=snapshot.model_dump(mode="json"),
                    cancellations=cancellations,
                )
            if operation == "RearmLocal":
                if source is not StopRequestSource.FLEET:
                    return self._response(403, error={
                        "code": "FLEET_PEER_REQUIRED",
                        "message": "only the authenticated Fleet peer can rearm",
                    })
                expected = {"version", "operation", "workcell_id", "instance_id",
                            "authority_epoch", "dispatch_generation"}
                if set(request) != expected:
                    raise ValueError("RearmLocal contains unsupported fields")
                rearm = LocalStopRearmRequest.model_validate({
                    key: request[key] for key in expected - {"version", "operation"}
                })
                if (rearm.workcell_id, rearm.instance_id) != (
                        self.controller.workcell_id, self.controller.instance_id):
                    raise KeyError("unknown workcell instance")
                snapshot = self.controller.rearm(
                    authority_epoch=rearm.authority_epoch,
                    dispatch_generation=rearm.dispatch_generation,
                    operator_confirmed=True,
                    fleet_fence_current=self.fleet_fence_current,
                )
                return self._response(200, snapshot=snapshot.model_dump(mode="json"))
            if operation == "GetStopState":
                if set(request) != {"version", "operation", "workcell_id", "instance_id"}:
                    raise ValueError("GetStopState contains unsupported fields")
                query = LocalStopQuery.model_validate({
                    "workcell_id": request["workcell_id"],
                    "instance_id": request["instance_id"],
                })
                snapshot = self.controller.snapshot(
                    workcell_id=query.workcell_id, instance_id=query.instance_id,
                )
                return self._response(200, snapshot=snapshot.model_dump(mode="json"))
            return self._response(404, error={
                "code": "UNKNOWN_OPERATION", "message": "stop operation is unsupported",
            })
        except LocalStopBlocked as exc:
            return self._response(409, error={"code": "LOCAL_REARM_REFUSED",
                                              "message": str(exc)})
        except (TypeError, ValueError) as exc:
            return self._response(400, error={"code": "INVALID_REQUEST", "message": str(exc)})
        except KeyError:
            return self._response(404, error={
                "code": "WORKCELL_NOT_FOUND", "message": "workcell instance is unavailable",
            })
        except Exception:
            return self._response(503, error={
                "code": "STOP_STATE_UNAVAILABLE",
                "message": "local stop persistence is unavailable",
            })


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
                except OSError:
                    if self._stop.is_set():
                        break
                    raise
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


__all__ = ["ActionApi", "LocalStopApi", "UnixActionServer", "action_grant_digest"]
