"""D-963: an operator's role decision for a USB camera the control PC reports; Fleet only stores the decision."""
import re
import sqlite3
import threading
import time

from fastapi import Depends, Header, HTTPException, Request, Response
from pydantic import ValidationError

from core_common.protocol.workcell_observations import UsbCameraDecision, UsbCameraDecisions, UsbCameraReport
from fleet.server.camera_peer_routes import body as bounded_json
from fleet.server.sqlite_policy import configure_connection, enable_wal

FRESH_S = 60.  # an older report is a host that stopped reporting; its cameras are not offered


class UsbCameraStore:
    def __init__(self, path=None, *, clock=time.monotonic, wall=time.time):
        self._clock, self._wall, self._lock, self._reports = clock, wall, threading.Lock(), {}
        self._db = configure_connection(sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False))
        if path:
            enable_wal(self._db)
        with self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS usb_camera_decisions (workcell_id TEXT NOT NULL, "
                             "key TEXT NOT NULL, role TEXT NOT NULL, principal_id TEXT NOT NULL, "
                             "decided_at REAL NOT NULL, PRIMARY KEY (workcell_id, key))")

    def _decisions(self, workcell_id):
        rows = self._db.execute("SELECT key, role, principal_id FROM usb_camera_decisions WHERE workcell_id=?",
                                (workcell_id,))
        return {key: (role, principal) for key, role, principal in rows}

    def report(self, report: UsbCameraReport) -> UsbCameraDecisions:
        """Keep the latest report, forget decisions for cameras no longer in it, return the rest."""
        keys = {c.key for c in report.candidates}
        with self._lock, self._db:
            self._reports[report.workcell_id] = (report, self._clock())
            for key in set(self._decisions(report.workcell_id)) - keys:
                self._db.execute("DELETE FROM usb_camera_decisions WHERE workcell_id=? AND key=?",
                                 (report.workcell_id, key))
            return UsbCameraDecisions(decisions=[UsbCameraDecision(key=k, role=role) for k, (role, _)
                                                 in self._decisions(report.workcell_id).items()])

    def decide(self, workcell_id, decision: UsbCameraDecision, principal_id):
        with self._lock, self._db:
            report = self._reports.get(workcell_id)
            if report is None or decision.key not in {c.key for c in report[0].candidates}:
                raise KeyError(decision.key)
            self._db.execute("INSERT OR REPLACE INTO usb_camera_decisions VALUES (?,?,?,?,?)",
                             (workcell_id, decision.key, decision.role, principal_id, self._wall()))

    def snapshot(self) -> dict:
        with self._lock:
            out = []
            for workcell_id, (report, at) in sorted(self._reports.items()):
                if self._clock() - at > FRESH_S:
                    continue
                decided = self._decisions(workcell_id)
                out.append({"workcell_id": workcell_id, "roles": report.roles, "candidates": [
                    {**c.model_dump(), "decision": ({"role": decided[c.key][0], "principal_id": decided[c.key][1]}
                                                    if c.key in decided else None)} for c in report.candidates]})
            return {"workcells": out}


def install_usb_camera_routes(app, *, service, store, require_viewer, require_named_operator):
    base = "/api/fleet/workcell-observations"

    @app.get(base + "/usb-devices", tags=["workcell-observations"])
    def listing(response: Response, _principal=Depends(require_viewer)):
        response.headers["Cache-Control"] = "no-store"
        return store.snapshot()

    @app.post(base + "/{workcell_id}/usb-devices", tags=["workcell-observations"])
    async def report(workcell_id: str, request: Request, response: Response,
                     token: str | None = Header(None, alias="X-Workcell-Observation-Token")):
        response.headers["Cache-Control"] = "no-store"
        try:
            service.authorize_workcell(workcell_id, token or "")
        except KeyError:
            raise HTTPException(404, detail={"code": "WORKCELL_UNKNOWN"}) from None
        except PermissionError:
            raise HTTPException(401, detail={"code": "WORKCELL_OBSERVATION_UNAUTHORIZED"}) from None
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 16384:
                raise HTTPException(413, detail={"code": "WORKCELL_OBSERVATION_TOO_LARGE"})
            data.extend(chunk)
        try:
            parsed = UsbCameraReport.model_validate_json(data)
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_USB_CAMERA_REPORT"}) from None
        if parsed.workcell_id != workcell_id:
            raise HTTPException(422, detail={"code": "INVALID_USB_CAMERA_REPORT"})
        return store.report(parsed).model_dump()

    @app.post(base + "/{workcell_id}/usb-devices/{key}/decision", tags=["workcell-observations"])
    async def decide(workcell_id: str, key: str, request: Request, response: Response,
                     principal=Depends(require_named_operator)):
        response.headers["Cache-Control"] = "no-store"
        data = await bounded_json(request)
        try:
            if not re.fullmatch(r"[0-9a-f]{16,64}", key) or not isinstance(data, dict) or set(data) != {"role"}:
                raise ValueError
            decision = UsbCameraDecision.model_validate({"key": key, "role": data["role"]})
        except (ValueError, ValidationError):
            raise HTTPException(422, detail={"code": "INVALID_USB_CAMERA_DECISION"}) from None
        try:
            store.decide(workcell_id, decision, principal.principal_id)
        except KeyError:
            raise HTTPException(404, detail={"code": "USB_CAMERA_NOT_REPORTED"}) from None
        return {"key": key, "role": decision.role}
