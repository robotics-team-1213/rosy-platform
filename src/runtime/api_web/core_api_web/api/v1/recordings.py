"""core_api_web.api.v1.recordings — D-411 A Pilot robot recording control and download.

CORE only asks the camera unit's recorder (PilotRecordingGuard) and reads its folder
read-only (pilot_recording_store). A download is camera footage leaving the robot, so it
needs an operator and an idle robot: not recording, no live manual input, not NAVIGATION or
DOCKING, line-follow off, and fresh zero velocity (or E-Stop). MANUAL mode itself does not
block: a Pilot that let go of the stick downloads where it stands.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from core_api_web.api.deps import AuthContext, CoreServicesLike, Mode, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator, viewer
from core_common.domain.pilot_recording import RecordingRefused
from core_common.domain.pilot_recording_store import archive_plan, iter_archive, list_recordings
from core_common.protocol.recording import PILOT_RECORDING_ROOT

recordings_router = APIRouter(prefix="/api/v1/recordings", tags=["recordings"])


def _root(svc: CoreServicesLike) -> Path:
    return Path((svc.config.get("recording") or {}).get("pilot_root") or PILOT_RECORDING_ROOT)


def _download_blocker(svc: CoreServicesLike) -> str | None:
    if svc.pilot_recording.active():
        return "RECORDING_BUSY"
    if (svc.command.manual_active or svc.modes.mode in (Mode.NAVIGATION, Mode.DOCKING)
            or svc.line_follow.active):
        return "ROBOT_MOVING"
    # The same stop evidence as traffic.py _robot_stopped, without its IDLE-only rule.
    snapshot = svc.state.snapshot()
    evidence = snapshot.evidence.get("velocity")
    fresh = bool(evidence and evidence.evidence.value == "fresh")
    still = abs(float(snapshot.velocity.linear)) <= 0.005 and abs(float(snapshot.velocity.angular)) <= 0.01
    return None if svc.safety.estop or (fresh and still) else "ROBOT_MOVING"


def _refused(exc: RecordingRefused) -> ApiError:
    return ApiError(exc.code, exc.status, exc.message)


@recordings_router.get("")
def recordings(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    status = svc.pilot_recording.status()
    active_id = status["id"] if status and status["state"] in ("recording", "stopping") else None
    blocker = _download_blocker(svc)
    return {"active": status, "items": list_recordings(_root(svc), active_id=active_id),
            "download_allowed": blocker is None, "download_blocker": blocker}


@recordings_router.get("/active")
def active(auth: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return {"active": svc.pilot_recording.status(),
            "owned": svc.pilot_recording.owner() == auth.token_id}


@recordings_router.post("", status_code=201)
def start(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    try:
        return svc.pilot_recording.start(auth.token_id)
    except RecordingRefused as exc:
        raise _refused(exc) from exc


@recordings_router.post("/active/stop")
def stop(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    try:
        return svc.pilot_recording.stop(auth.token_id, is_admin=auth.role == "administrator")
    except RecordingRefused as exc:
        raise _refused(exc) from exc


# `:path` so an encoded "../" reaches the id check and is refused as not found.
@recordings_router.get("/{recording_id:path}/archive")
def archive(recording_id: str, _: AuthContext = Depends(operator),
            svc: CoreServicesLike = Depends(get_services)):
    blocker = _download_blocker(svc)
    if blocker is not None:
        raise ApiError(blocker, 409, "recordings can only be downloaded while the robot is stopped")
    try:
        members, length = archive_plan(_root(svc), recording_id)
    except LookupError as exc:
        raise ApiError("RECORDING_NOT_FOUND", 404, str(exc)) from exc

    def stream():
        yield from iter_archive(members)
        svc.pilot_recording.fetched(recording_id)   # only after the last byte left

    return StreamingResponse(stream(), media_type="application/x-tar", headers={
        "Content-Length": str(length), "Cache-Control": "no-store", "Content-Encoding": "identity",
        "Content-Disposition": f'attachment; filename="{recording_id}.tar"'})
