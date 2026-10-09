"""Overhead markerless tracking on the console map (D-457 4-6). Display and cross-check only.

Vision posts anonymous floor detections per camera source with that source's sighting
token. Fleet keeps the last payload per source for ``lease_s`` (1.0 s, the sighting
lease), checks its calibration revision against the corner-marker revision and the
approved paint-fit record, and pairs fresh map-frame robot poses with detections
(tracking_match.py). Robot states arrive through ``observe_states`` from the console
state route; nothing here calls a robot. Traffic, bays, missions and localization never
import this module (test_boundaries.py).
"""

from __future__ import annotations

import hmac
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Sequence

from core_common.protocol.overhead_detections import OverheadDetectionsPayload
from fleet.server.sightings import SightingSource
from fleet.server.tracking_calibration import TrackingCalibrationStore, build_record
from fleet.server.tracking_match import GATE_M, Pose, Seen, Track, better, match

DETECTION_LEASE_S = 1.0
MAX_FUTURE_S = 0.05
#: A robot state older than this (seen through the console state route) is no pose.
STATE_FRESH_S = 2.0
FPS_WINDOW_S = 3.0


class TrackingError(ValueError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass
class _SourceState:
    payload: Optional[OverheadDetectionsPayload] = None
    arrivals: deque = field(default_factory=deque)
    last_error: Optional[str] = None
    relearn_seq: int = 0


class TrackingService:
    def __init__(self, sources: Sequence[SightingSource], *, calibrations: TrackingCalibrationStore,
                 clock: Callable[[], float] = time.time, lease_s: float = DETECTION_LEASE_S,
                 state_fresh_s: float = STATE_FRESH_S, gate_m: float = GATE_M) -> None:
        for value in (lease_s, state_fresh_s, gate_m):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("tracking lease, state freshness and gate must be positive")
        self.sources = tuple(sources)
        self._by_id = {source.source_id: source for source in self.sources}
        if len(self._by_id) != len(self.sources):
            raise ValueError("tracking source ids must be unique")
        if len({source.token for source in self.sources}) != len(self.sources):
            raise ValueError("tracking source tokens must be unique")
        for source in self.sources:
            if len(set(source.robot_ids)) != len(source.robot_ids):
                raise ValueError(f"tracking source {source.source_id!r} repeats a robot target")
            markers = source.robot_markers
            if (len({robot for robot, _ in markers}) != len(markers)
                    or len({marker for _, marker in markers}) != len(markers)
                    or any(robot not in source.robot_ids or isinstance(marker, bool)
                           or not isinstance(marker, int) or marker < 0 for robot, marker in markers)):
                raise ValueError(f"tracking source {source.source_id!r} has invalid robot markers")
        self.calibrations = calibrations
        self._clock = clock
        self.lease_s = lease_s
        self.state_fresh_s = state_fresh_s
        self.gate_m = gate_m
        self._sources = {source.source_id: _SourceState() for source in self.sources}
        self._states: dict[str, tuple[dict, float]] = {}
        #: D-472 IdentityService (set by the app): its challenge rides the config, bindings follow detections.
        self.identity = None

    @property
    def enabled(self) -> bool:
        return bool(self.sources)

    def retarget(self, sources: Sequence[SightingSource]) -> None:
        """D-580: the sighting service's sources after a roster change (same ids and tokens)."""
        if [s.source_id for s in sources] != [s.source_id for s in self.sources]:
            raise ValueError("tracking sources cannot change identity")
        self.sources = tuple(sources)
        self._by_id = {source.source_id: source for source in self.sources}

    def authenticate(self, authorization: Optional[str]) -> SightingSource:
        candidate = authorization or ""
        matched: Optional[SightingSource] = None
        for source in self.sources:
            if hmac.compare_digest(candidate.encode("utf-8"), f"Bearer {source.token}".encode("utf-8")):
                matched = source
        if matched is None:
            raise TrackingError(401, "DETECTION_UNAUTHORIZED", "source token required")
        return matched

    def config_for(self, authorization: Optional[str]) -> dict:
        source = self.authenticate(authorization)
        record = self.calibrations.get(source.source_id)
        usable = record is not None and record.map_id == source.map_id
        config = {"source_id": source.source_id, "map_id": source.map_id,
                  "calibration": record.to_dict() if usable else None,
                  "relearn_seq": self._sources[source.source_id].relearn_seq,
                  # D-580: Vision uses these over its YAML (the roster's numbers, D-562).
                  "robot_markers": dict(source.robot_markers)}
        if self.identity is not None:
            config["identity_challenge"] = self.identity.challenge_for(source.source_id)
        return config

    def accept(self, authorization: Optional[str], payload: OverheadDetectionsPayload) -> dict:
        source = self.authenticate(authorization)
        state = self._sources[source.source_id]
        if payload.source_id != source.source_id:
            raise TrackingError(403, "SOURCE_MISMATCH", "payload source does not match the token")
        if payload.map_id != source.map_id:
            state.last_error = "MAP_MISMATCH"
            raise TrackingError(409, "MAP_MISMATCH", "detection map does not match source configuration")
        if (payload.calibration_revision is not None
                and payload.calibration_revision not in self._revisions(source)):
            state.last_error = "CALIBRATION_MISMATCH"
            raise TrackingError(409, "CALIBRATION_MISMATCH",
                                "detection calibration is neither the marker nor the approved one")
        now = self._clock()
        age_s = now - payload.captured_at
        if age_s < -MAX_FUTURE_S:
            state.last_error = "DETECTION_FUTURE"
            raise TrackingError(409, "DETECTION_FUTURE", "detection capture time is in the future")
        if age_s > self.lease_s:
            state.last_error = "DETECTION_STALE"
            raise TrackingError(409, "DETECTION_STALE", "detection exceeded the display lease")
        if state.payload is not None and payload.captured_at <= state.payload.captured_at:
            state.last_error = "DETECTION_OUT_OF_ORDER"
            raise TrackingError(409, "DETECTION_OUT_OF_ORDER", "detection is not newer than readback")
        state.payload = payload
        state.last_error = None
        state.arrivals.append(now)
        self._trim(state, now)
        if self.identity is not None:
            self.identity.on_detections(source.source_id, payload)
        return {"accepted": True, "source_id": source.source_id, "seq": payload.seq,
                "status": payload.status}

    def approve(self, body: Mapping, *, approved_by: str) -> dict:
        source = self._by_id.get(body.get("source_id"))
        if source is None:
            raise TrackingError(404, "UNKNOWN_SOURCE", "no configured source with this id")
        map_id = body.get("map_id") or source.map_id
        if map_id != source.map_id:
            raise TrackingError(409, "MAP_MISMATCH", "calibration map does not match source configuration")
        try:
            image = body["image"]
            bounds = body["track_bounds_m"]
            record = build_record(
                source_id=source.source_id, map_id=map_id, map_to_image=body["map_to_image"],
                image_width=image["width"], image_height=image["height"],
                track_bounds_m=(bounds["min_x"], bounds["min_y"], bounds["max_x"], bounds["max_y"]),
                lens=body.get("lens"), fit_score=body["fit_score"], frame_seq=body.get("frame_seq"),
                approved_by=approved_by, approved_at=self._clock())
        except (KeyError, TypeError, ValueError) as exc:
            raise TrackingError(422, "INVALID_CALIBRATION", str(exc)) from exc
        self.calibrations.put(record)
        return record.to_dict()

    def revoke(self, source_id: str, *, principal_id: str) -> dict:
        if source_id not in self._by_id:
            raise TrackingError(404, "UNKNOWN_SOURCE", "no configured source with this id")
        removed = self.calibrations.delete(source_id, principal_id=principal_id, at=self._clock())
        return {"source_id": source_id, "removed": removed}

    def calibration_listing(self) -> dict:
        return {"calibrations": [record.to_dict() for record in self.calibrations.all()],
                "use": "display-only"}

    def request_relearn(self, source_id: str) -> dict:
        if source_id not in self._by_id:
            raise TrackingError(404, "UNKNOWN_SOURCE", "no configured source with this id")
        state = self._sources[source_id]
        state.relearn_seq += 1
        return {"source_id": source_id, "relearn_seq": state.relearn_seq}

    def now(self) -> float:
        return self._clock()

    def observe_states(self, robots: Sequence[Mapping], *, now: Optional[float] = None,
                       observed: Optional[Mapping[str, float]] = None) -> None:
        """Remember the robot states the console state route just gathered.

        ``now`` is when the gather started (default: the clock now), so a slow robot read
        never makes its state look fresher than it is. ``observed`` (robot_id -> this clock)
        is when each robot's own state was read; it wins over ``now``. Without it a whole
        gather slower than ``state_fresh_s`` left every state stale on arrival, so LED
        identify always answered IDENTIFY_NOT_MOVING (site, 2026-10-09: 3.4 s gathers).
        An online row with a state replaces the robot's entry; any other row for that robot
        (offline, or no state) drops it, so a robot that went away keeps no stale pose.
        """
        if now is None:
            now = self._clock()
        observed = observed or {}
        for row in robots:
            if not isinstance(row, Mapping):
                continue
            robot_id = row.get("robot_id")
            if not isinstance(robot_id, str):
                continue
            state = row.get("state")
            if row.get("online") and isinstance(state, Mapping):
                self._states[robot_id] = (dict(state), observed.get(robot_id, now))
            else:
                self._states.pop(robot_id, None)

    def snapshot(self) -> dict:
        now = self._clock()
        sources_out: list[dict] = []
        unknown: list[dict] = []
        tracks: dict[str, Track] = {}
        track_source: dict[str, str] = {}
        for source in self.sources:
            state = self._sources[source.source_id]
            self._trim(state, now)
            payload = state.payload
            fresh = payload is not None and now - payload.captured_at <= self.lease_s
            status = payload.status if fresh else ("STALE" if payload is not None else "NONE")
            sources_out.append({
                "source_id": source.source_id,
                "map_id": source.map_id,
                "status": status,
                "calibration_revision": payload.calibration_revision if fresh else None,
                "age_ms": None if payload is None else max(0, round((now - payload.captured_at) * 1000.0)),
                "fps": round(len(state.arrivals) / FPS_WINDOW_S, 1),
                "last_error": state.last_error,
                "relearn_seq": state.relearn_seq,
                # D-589 8: the camera's recognition tuning as Vision last reported it.
                "tuning": (payload.tuning.model_dump(mode="json")
                           if fresh and payload.tuning is not None else None),
            })
            seen = ([Seen(d.x, d.y, d.footprint_m, d.score) for d in payload.detections
                     if d.marker_id is None]
                    if fresh and status == "OK" else None)
            # Map-frame eligibility is decided here, before the matcher: fresh state, same
            # map as this source, and (when D-395 fields exist) LOCALIZED in the map frame.
            poses = {rid: self._pose(rid, source.map_id, now) for rid in source.robot_ids}
            assignments = {marker: rid for rid, marker in source.robot_markers}
            measured = {}
            # D-575: a marker no robot is assigned to is still a robot on the floor: unknown, with its id.
            unassigned: dict[int, Seen] = {}
            if fresh and status == "OK":
                for detection in payload.detections:
                    if detection.marker_id is None:
                        continue
                    rid = assignments.get(detection.marker_id)
                    item = Seen(detection.x, detection.y, detection.footprint_m, detection.score)
                    if rid is not None and rid in source.robot_ids:
                        measured[rid] = item
                    else:
                        unassigned[detection.marker_id] = item
            marked = {**measured, **unassigned}
            if marked and seen is not None:
                # One anonymous blob per marker is that marker's robot, not another one.
                pairs = sorted((math.hypot(d.x - m.x, d.y - m.y), str(rid), index)
                               for rid, m in marked.items() for index, d in enumerate(seen)
                               if math.hypot(d.x - m.x, d.y - m.y) <= max(d.footprint_m, m.footprint_m))
                used_markers, duplicates = set(), set()
                for _, rid, index in pairs:
                    if rid not in used_markers and index not in duplicates:
                        used_markers.add(rid)
                        duplicates.add(index)
                seen = [d for index, d in enumerate(seen) if index not in duplicates]
            rows, extra = match([rid for rid in source.robot_ids if rid not in measured], poses, seen, self.gate_m)
            for rid, marker in measured.items():
                pose = poses[rid]
                offset = None if pose is None else math.hypot(marker.x - pose.x, marker.y - pose.y)
                rows.append(Track(rid, "MARKER", offset, marker, pose))
            for row in rows:
                prior = tracks.get(row.robot_id)
                chosen = row if prior is None else better(prior, row)
                if chosen is row:
                    track_source[row.robot_id] = source.source_id
                tracks[row.robot_id] = chosen
            unknown.extend({"source_id": source.source_id, "x": item.x, "y": item.y,
                            "footprint_m": item.footprint_m, "score": item.score, "marker_id": None}
                           for item in extra)
            unknown.extend({"source_id": source.source_id, "x": item.x, "y": item.y,
                            "footprint_m": item.footprint_m, "score": item.score, "marker_id": marker_id}
                           for marker_id, item in sorted(unassigned.items()))
        robots = [_render(tracks[rid], track_source[rid]) for rid in sorted(tracks)]
        return {"ts": now, "lease_s": self.lease_s, "gate_m": self.gate_m, "use": "display-only",
                "sources": sources_out, "robots": robots, "unknown": unknown}

    def latest(self, source_id: str) -> Optional[OverheadDetectionsPayload]:
        """The source's last accepted payload while inside the lease, else None."""
        state = self._sources.get(source_id)
        payload = None if state is None else state.payload
        if payload is None or self._clock() - payload.captured_at > self.lease_s:
            return None
        return payload

    def robot_state(self, robot_id: str) -> Optional[dict]:
        """The robot's state from the last console gather while fresh, else None."""
        entry = self._states.get(robot_id)
        if entry is None or not 0.0 <= self._clock() - entry[1] <= self.state_fresh_s:
            return None
        return entry[0]

    def approved_revision(self, source: SightingSource) -> Optional[str]:
        """D-587 2: the approved record's revision for this source's map, else None."""
        record = self.calibrations.get(source.source_id)
        if record is None or record.map_id != source.map_id:
            return None
        return record.calibration_revision

    def revisions(self, source: SightingSource) -> set[str]:
        return self._revisions(source)

    def _revisions(self, source: SightingSource) -> set[str]:
        allowed = {source.calibration_revision}  # corner-marker path (CameraMap), D-457 2
        record = self.calibrations.get(source.source_id)
        if record is not None and record.map_id == source.map_id:
            allowed.add(record.calibration_revision)
        return allowed

    def _pose(self, robot_id: str, map_id: str, now: float) -> Optional[Pose]:
        entry = self._states.get(robot_id)
        if entry is None or not 0.0 <= now - entry[1] <= self.state_fresh_s:
            return None
        state = entry[0]
        if state.get("map_id") != map_id:
            return None
        localization = state.get("localization")
        verified = False
        if localization is not None:
            if (not isinstance(localization, Mapping) or localization.get("pose_frame") != "map"
                    or localization.get("state") != "LOCALIZED"):
                return None
            verified = True
        pose = state.get("pose")
        try:
            x, y = float(pose["x"]), float(pose["y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        return Pose(x, y, verified)

    @staticmethod
    def _trim(state: _SourceState, now: float) -> None:
        while state.arrivals and now - state.arrivals[0] > FPS_WINDOW_S:
            state.arrivals.popleft()


def _render(track: Track, source_id: str) -> dict:
    return {
        "robot_id": track.robot_id,
        "status": track.status,
        "source_id": source_id,
        "offset_m": track.offset_m,
        "camera": None if track.camera is None else {
            "x": track.camera.x, "y": track.camera.y,
            "footprint_m": track.camera.footprint_m, "score": track.camera.score},
        "pose": None if track.pose is None else {"x": track.pose.x, "y": track.pose.y},
        "pose_frame_verified": None if track.pose is None else track.pose.verified,
    }
