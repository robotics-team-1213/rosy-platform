"""D-494 6: record one robot's map pose while a driver moves it with Pilot, then turn the
recording into a draft edge.

Teach never sends anything to a robot. One recording per site; a stopped recording waits in
memory for ``confirm`` and is dropped ``PENDING_S`` after stop (nothing survives a restart).
Start, stop, confirm and place are site map events; confirm and place save the draft through
``SiteMapStore.save_draft`` (same ``expected_revision`` rule as the draft PUT), never the
active map.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Optional

from pydantic import ValidationError

from fleet.routing import teach
from rosy.world.state.projections.map_pose import compose, relative
from fleet.routing.graph import polyline_length
from fleet.server.site_map_routes import MAX_DRAFT_BYTES, invalid_errors
from fleet.site_map import IMPORT_WIDTH_M, MAX_POINTS, MIN_EDGE_M, SiteMap

#: The trip loop's odom cadence (D-494 3 부록 8): one REST read per sample.
SAMPLE_S = 0.5
#: A recording that kept no point this long is stopped (``IDLE_PRINCIPAL``); a stopped one that
#: is not confirmed this long after its stop is discarded.
PENDING_S = 600.0
IDLE_PRINCIPAL = "system:teach_idle"

_LOG = logging.getLogger(__name__)


class TeachError(Exception):
    def __init__(self, status: int, code: str, detail: Optional[dict] = None) -> None:
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail or {}


@dataclass
class Session:
    teach_id: str
    robot_id: str
    started_by: str
    started_at: float
    points: list = field(default_factory=list)
    stopped_at: Optional[float] = None
    result: Optional[dict] = None
    last_kept_at: float = 0.0
    mode: str = "map"
    map_id: Optional[str] = None
    draft_revision: Optional[str] = None
    reference: Optional[dict] = None
    odom_anchor: Optional[tuple] = None
    odom_epoch: int = 0
    map_frame: Optional[tuple] = None


def survey_reference(body: dict) -> Optional[dict]:
    reference = body.get("survey")
    return {k: v for k, v in reference.items() if k not in {"reviewed", "review_note"}} if reference else None


class TeachService:
    def __init__(self, *, poses, site_maps, roster: Callable[[], Iterable[str]],
                 clock: Callable[[], float] = time.time,
                 place_markers: Optional[Callable[[int], Optional[dict]]] = None) -> None:
        self._poses, self._store, self._roster, self._clock = poses, site_maps, roster, clock
        #: D-564: marker id -> the newest fresh place marker row (``SightingService.fresh_place_marker``).
        self._place_markers = place_markers
        self._recording: Optional[Session] = None
        self._task: Optional[asyncio.Task] = None
        self._pending: dict[str, Session] = {}

    async def _pose(self, robot_id: str):
        refresh = getattr(self._poses, "refresh", None)
        try:
            if refresh is not None:
                await refresh(robot_id, force_rest=True)
        except Exception:  # an unread state ages the pose into DEGRADED/UNKNOWN
            _LOG.debug("teach: state read for %s failed", robot_id, exc_info=True)
        pose = self._poses.arbitrated_pose(robot_id)
        return await pose if inspect.isawaitable(pose) else pose

    async def _localized(self, robot_id: str):
        if robot_id not in set(self._roster()):
            raise TeachError(404, "UNKNOWN_ROBOT")
        map_frame = self._map_frame()
        pose = await self._pose(robot_id)
        if pose is None or pose.state != "LOCALIZED" or pose.x is None:
            raise TeachError(422, "TEACH_POSE_UNTRUSTED",
                             {"state": getattr(pose, "state", None)})
        if self._map_frame(pose) != map_frame:
            raise TeachError(409, "TEACH_MAP_CHANGED")
        return pose

    async def _survey_odom(self, robot_id: str):
        reader = getattr(self._poses, "survey_odom", None)
        if reader is None:
            return None
        try:
            await self._poses.refresh(robot_id, force_rest=True)
            sample = reader(robot_id)
            return await sample if inspect.isawaitable(sample) else sample
        except Exception:
            _LOG.debug("teach: survey odom read for %s failed", robot_id, exc_info=True)
            return None

    async def _end_record(self, reason: str) -> None:
        try:
            await self.stop(IDLE_PRINCIPAL, reason=reason)
        except TeachError as exc:
            if exc.code != "TEACH_TOO_SHORT":
                raise

    async def sample(self) -> None:
        """One recording step: read the pose and keep it when the D-494 6 rules allow."""
        session = self._recording
        if session is None or len(session.points) >= MAX_POINTS:
            return
        if session.mode == "survey":
            sample = await self._survey_odom(session.robot_id)
            if session is not self._recording:
                return
            draft = self._store.draft_view()
            body = draft["map"] or {}
            if (draft["revision"] != session.draft_revision or body.get("map_id") != session.map_id
                    or survey_reference(body) != session.reference):
                await self._end_record("survey_changed")
                return
            if sample is None:
                await self._end_record("odom_lost")
                return
            odom, _stamp, epoch = sample
            if epoch != session.odom_epoch:
                await self._end_record("odom_reset")
                return
            x, y, _yaw = compose((*session.reference["origin"], session.reference["heading_rad"]),
                                relative(session.odom_anchor, odom))
            point = (round(x, 3), round(y, 3))
            if not session.points or math.dist(session.points[-1], point) >= teach.SPACING_M:
                session.points.append(point)
                session.last_kept_at = self._clock()
            return
        pose = await self._pose(session.robot_id)
        if session is not self._recording:
            return
        if teach.keep([], pose) is None:  # a later valid pose must not bridge an unobserved road
            await self._end_record("pose_lost")
            return
        try:
            if self._map_frame(pose) != session.map_frame:
                raise TeachError(409, "TEACH_MAP_CHANGED")
        except TeachError:
            await self._end_record("map_changed")
            return
        point = teach.keep(session.points, pose)
        if point is not None and session is self._recording:
            session.points.append(point)
            session.last_kept_at = self._clock()

    async def idle_check(self) -> bool:
        """Stop a recording that kept no point for ``PENDING_S`` or is full; True when stopped."""
        session = self._recording
        if session is None:
            return False
        full = len(session.points) >= MAX_POINTS
        if not full and self._clock() - session.last_kept_at <= PENDING_S:
            return False
        try:
            await self.stop(IDLE_PRINCIPAL, reason="full" if full else "idle")
        except TeachError:  # too short: dropped, as an operator stop would
            pass
        return True

    async def _run(self) -> None:
        while self._recording is not None:
            try:
                await self.sample()
                if await self.idle_check():
                    return
            except Exception:
                _LOG.exception("teach: sample failed")
            await asyncio.sleep(SAMPLE_S)

    async def start(self, robot_id: str, principal_id: str, *, mode: str = "map",
                    map_id: Optional[str] = None, reference_revision: Optional[str] = None,
                    expected_revision: Optional[str] = None) -> dict:
        if self._recording is not None:
            raise TeachError(409, "TEACH_BUSY", {"teach_id": self._recording.teach_id,
                                                 "robot_id": self._recording.robot_id})
        if mode not in {"map", "survey"}:
            raise TeachError(422, "TEACH_MODE_INVALID")
        reference, anchor, epoch, map_frame = None, None, 0, None
        if mode == "survey":
            if robot_id not in set(self._roster()):
                raise TeachError(404, "UNKNOWN_ROBOT")
            draft = self._store.draft_view()
            body = draft["map"] or {}
            reference = survey_reference(body)
            if reference is None:
                raise TeachError(422, "TEACH_SURVEY_REQUIRED")
            if expected_revision is None or draft["revision"] != expected_revision:
                raise TeachError(409, "SITE_MAP_DRAFT_CHANGED")
            if map_id != body.get("map_id") or reference_revision != reference["revision"]:
                raise TeachError(409, "TEACH_SURVEY_CHANGED")
            sample = await self._survey_odom(robot_id)
            if sample is None:
                raise TeachError(422, "TEACH_ODOM_UNAVAILABLE")
            anchor, _stamp, epoch = sample
            if self._store.draft_view()["revision"] != expected_revision:
                raise TeachError(409, "SITE_MAP_DRAFT_CHANGED")
        else:
            if any(value is not None for value in (map_id, reference_revision, expected_revision)):
                raise TeachError(422, "TEACH_MODE_INVALID")
            map_frame = self._map_frame(await self._localized(robot_id))
            map_id = map_frame[0]
        if self._recording is not None:  # another start won while we read the pose
            raise TeachError(409, "TEACH_BUSY", {"teach_id": self._recording.teach_id,
                                                 "robot_id": self._recording.robot_id})
        session = self._recording = Session(uuid.uuid4().hex, robot_id, principal_id, self._clock(),
            mode=mode, map_id=map_id, draft_revision=expected_revision, reference=reference,
            odom_anchor=anchor, odom_epoch=epoch, map_frame=map_frame)
        session.last_kept_at = session.started_at
        self._store.record_event("teach_started", principal_id, {"teach_id": session.teach_id, "robot_id": robot_id})
        if mode == "survey":
            session.points.append(tuple(round(v, 3) for v in reference["origin"]))
        else:
            try:  # a failed first read leaves the sampler to retry
                await self.sample()
            except Exception:
                _LOG.exception("teach: first sample failed")
        self._task = asyncio.ensure_future(self._run())
        return self.view()

    async def stop(self, principal_id: str, *, reason: str = "operator") -> dict:
        session = self._recording
        if session is None:
            raise TeachError(409, "TEACH_NOT_RECORDING")
        self._recording = None
        if self._task is not None and self._task is not asyncio.current_task():
            self._task.cancel()
        self._task = None
        session.stopped_at = self._clock()
        line = teach.simplify(session.points)
        detail = {"teach_id": session.teach_id, "robot_id": session.robot_id,
                  "points": len(session.points), "kept": len(line), "reason": reason,
                  "map_id": session.map_id}
        if session.mode == "map" and session.map_frame[1] is not None:
            detail["survey_reference"] = session.map_frame[1]
        if session.mode == "survey":
            detail.update(mode="survey", map_id=session.map_id, reference_revision=session.reference["revision"],
                          survey_reference=session.reference)
        self._store.record_event("teach_stopped", principal_id, detail)
        if len(line) < 2 or polyline_length(line) <= MIN_EDGE_M:
            raise TeachError(422, "TEACH_TOO_SHORT", {**detail, "min_m": MIN_EDGE_M})
        places = self._base()["places"]
        if (self._base().get("map_id", "site") != session.map_id
                or (session.mode == "survey" and survey_reference(self._base()) != session.reference)):
            places = []
        session.result = {**detail, "polyline": [list(p) for p in line],
                          "from_candidates": teach.candidates(places, line[0]),
                          "to_candidates": teach.candidates(places, line[-1]),
                          "expires_at": session.stopped_at + PENDING_S}
        session.points = []        # the result keeps the simplified line
        self._prune()
        self._pending[session.teach_id] = session
        return session.result

    def _prune(self) -> None:
        now = self._clock()
        for teach_id in [k for k, s in self._pending.items() if now - s.stopped_at > PENDING_S]:
            del self._pending[teach_id]

    def _base(self) -> dict:
        """The draft, else a copy of the active map, else an empty map."""
        draft = self._store.draft_view()["map"]
        if draft is not None:
            return draft
        active = self._store.active_view()
        return active["map"] if active else {"schema": "rosy.site_map/1", "places": [], "edges": []}

    def _save(self, body: dict, expected_revision: Optional[str], principal_id: str) -> dict:
        if body.get("survey"):
            body["survey"] = {**body["survey"], "reviewed": False, "review_note": ""}
        try:
            site_map = SiteMap.model_validate(body)
        except ValidationError as exc:
            raise TeachError(422, "SITE_MAP_INVALID", {"errors": invalid_errors(exc)}) from exc
        if len(json.dumps(site_map.body(), ensure_ascii=False).encode("utf-8")) > MAX_DRAFT_BYTES:
            raise TeachError(413, "SITE_MAP_TOO_LARGE", {"limit_bytes": MAX_DRAFT_BYTES})
        return self._store.save_draft(site_map, expected_revision=expected_revision, principal_id=principal_id)

    def _map_frame(self, pose=None) -> tuple:
        """Operational geometry belongs to the active frame, never an unrelated draft."""
        base, active = self._base(), self._store.active_view()
        map_id, reference = base.get("map_id", "site"), survey_reference(base)
        if ((active is None and reference is not None)
                or (active is not None and (active["map"].get("map_id", "site") != map_id
                    or survey_reference(active["map"]) != reference))
                or (pose is not None and getattr(pose, "map_id", None) not in {None, map_id})):
            raise TeachError(409, "TEACH_MAP_CHANGED")
        return map_id, reference, active["version"] if active else None

    def confirm(self, teach_id: str, *, start, end, direction: str, drive_mode: str, speed_cap_mps: float,
                width_m: Optional[float], expected_revision: Optional[str], principal_id: str) -> dict:
        self._prune()
        session = self._pending.get(teach_id)
        if session is None:
            raise TeachError(404, "TEACH_UNKNOWN")
        base = self._base()
        if session.mode == "survey" and (base.get("map_id") != session.map_id
                                         or survey_reference(base) != session.reference):
            raise TeachError(409, "TEACH_SURVEY_CHANGED")
        if session.mode == "map" and self._map_frame() != session.map_frame:
            raise TeachError(409, "TEACH_MAP_CHANGED")
        try:
            body, edge_id = teach.append_edge(
                base, [tuple(p) for p in session.result["polyline"]], start=start, end=end,
                direction=direction, drive_mode=drive_mode, speed_cap_mps=speed_cap_mps,
                width_m=width_m if width_m is not None else IMPORT_WIDTH_M)
        except teach.TeachRefused as exc:
            raise TeachError(422, exc.code, exc.detail) from exc
        if body.get("survey"):
            edge = next(edge for edge in body["edges"] if edge["id"] == edge_id)
            edge["evidence"] = {"source": "odometry", "status": "observed",
                                "reference_revision": body["survey"]["revision"], "note": ""}
            body["survey"] = {**body["survey"], "reviewed": False, "review_note": ""}
        draft = self._save(body, expected_revision, principal_id)  # SiteMapError passes through
        del self._pending[teach_id]
        self._store.record_event("teach_confirmed", principal_id, {"teach_id": teach_id, "edge_id": edge_id,
                                                                   "revision": draft["revision"]})
        return {"edge_id": edge_id, "draft": draft}

    async def place(self, robot_id: str, *, name: str, kind: str, expected_revision: Optional[str],
                    principal_id: str) -> dict:
        pose = await self._localized(robot_id)
        body = self._base()
        place_id = teach.add_place(body, name, kind, pose.x, pose.y, pose.yaw)
        draft = self._save(body, expected_revision, principal_id)
        self._store.record_event("teach_place", principal_id, {"robot_id": robot_id, "place_id": place_id,
                                                               "revision": draft["revision"]})
        return {"place_id": place_id, "draft": draft}

    def place_from_marker(self, marker_id: int, *, name: Optional[str], kind: Optional[str],
                          place_id: Optional[str], expected_revision: Optional[str], principal_id: str) -> dict:
        """D-564: add (or move, with ``place_id``) a draft place at a fresh floor place marker."""
        if self._place_markers is None:
            raise TeachError(503, "PLACE_MARKERS_DISABLED")
        row = self._place_markers(marker_id)
        if row is None:
            raise TeachError(409, "PLACE_MARKER_STALE", {"marker_id": marker_id})
        active = self._store.active()
        if active is not None and active[1].map_id != row["map_id"]:
            raise TeachError(409, "PLACE_MARKER_MAP_MISMATCH",
                             {"marker_map_id": row["map_id"], "active_map_id": active[1].map_id})
        body = self._base()
        self._map_frame()
        if body.get("map_id", "site") != row["map_id"]:  # the draft (or empty base) is another map frame
            raise TeachError(409, "PLACE_MARKER_MAP_MISMATCH",
                             {"marker_map_id": row["map_id"], "draft_map_id": body.get("map_id", "site")})
        updated = place_id is not None
        if not updated:
            if not name:
                raise TeachError(422, "PLACE_NAME_REQUIRED")
            place_id = teach.add_place(body, name, kind or "junction", row["x"], row["y"], row["yaw"])
        else:
            body = {**body, "places": [dict(p) for p in body["places"]], "edges": [dict(e) for e in body["edges"]]}
            place = next((p for p in body["places"] if p["id"] == place_id), None)
            if place is None:
                raise TeachError(404, "PLACE_UNKNOWN", {"place_id": place_id})
            if place.get("kind") == "bend" or kind == "bend":
                raise TeachError(422, "PLACE_MARKER_BEND", {"place_id": place_id})
            place.update(x=round(row["x"], 4), y=round(row["y"], 4),
                         yaw=math.atan2(math.sin(row["yaw"]), math.cos(row["yaw"])))
            if name:
                place["name"] = name
            if kind:
                place["kind"] = kind
            for edge in body["edges"]:  # a lane keeps ending on its moved place
                ends = {0: edge["from"] == place_id, -1: edge["to"] == place_id}
                if any(ends.values()):
                    edge["polyline"] = [list(p) for p in edge["polyline"]]
                    for index in (i for i, hit in ends.items() if hit):
                        edge["polyline"][index] = [place["x"], place["y"]]
                    if body.get("survey") or edge.get("evidence"):
                        edge["evidence"] = {"source": "operator", "status": "observed",
                            "reference_revision": (body["survey"]["revision"] if body.get("survey")
                                else edge["evidence"]["reference_revision"]), "note": edge.get("evidence", {}).get("note", "")}
        draft = self._save(body, expected_revision, principal_id)
        self._store.record_event("teach_place", principal_id, {
            "marker_id": marker_id, "source_id": row["source_id"], "place_id": place_id,
            "updated": updated,
            "revision": draft["revision"]})
        return {"place_id": place_id, "draft": draft}

    def view(self) -> dict:
        self._prune()
        live = self._recording
        recording = None if live is None else {k: v for k, v in asdict(live).items()
            if k not in {"reference", "odom_anchor", "odom_epoch", "map_frame"}}
        if recording is not None:
            recording["points"] = [list(point) for point in live.points]
            if live.mode == "map" and live.map_frame[1] is not None:
                recording["survey_reference"] = live.map_frame[1]
        if recording is not None and live.reference is not None:
            recording["reference_revision"] = live.reference["revision"]
            recording["survey_reference"] = live.reference
        return {"recording": recording,
                "pending": [s.result for s in reversed(self._pending.values())]}  # newest first
