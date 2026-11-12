"""Overhead markerless tracking on the console map (D-457 4-6). Display and cross-check only."""

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
STATE_FRESH_S = 2.0
FPS_WINDOW_S = 3.0
REGION_MARGIN_M = 0.03
ROBOT_RADIUS_M = 0.0826
OWN_POSE_EXTRA_M = 0.05
MAX_BRIDGE_EXTRA_M = 0.3
LAST_SEEN_S = 60.0


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
    last_ok: Optional[OverheadDetectionsPayload] = None  # D-600


class TrackingService:
    def __init__(self, sources: Sequence[SightingSource], *, calibrations: TrackingCalibrationStore,
                 clock: Callable[[], float] = time.time, lease_s: float = DETECTION_LEASE_S,
                 state_fresh_s: float = STATE_FRESH_S, gate_m: float = GATE_M,
                 drift_provider: Optional[Callable[[], Mapping[str, dict]]] = None,
                 health=None) -> None:
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
        self._drift_provider = drift_provider
        self.health = health
        self._sources = {source.source_id: _SourceState() for source in self.sources}
        self._states: dict[str, tuple[dict, float]] = {}
        self.identity = None
        self.auto_locate = None  # D-989
        self.map_pose: Optional[Callable[[str], object]] = None
        now_init = self._clock()
        self._anchors: dict[str, dict] = {
            "rosy_46": {"target_id": "rosy_46", "kind": "pinky", "label": "rosy-pinky-b8xy (rosy_46)",
                        "base_x": -0.4184, "base_y": 0.380, "base_yaw": -1.5708, "reach_m": 0.18, "zoom": 3, "updated_at": now_init},
            "rosy_45": {"target_id": "rosy_45", "kind": "pinky", "label": "rosy-pinky-y8xs (rosy_45)",
                        "base_x": -0.1896, "base_y": 0.380, "base_yaw": -1.5708, "reach_m": 0.18, "zoom": 3, "updated_at": now_init},
            "rosy_42": {"target_id": "rosy_42", "kind": "pinky", "label": "rosy-pinky-geg6 (rosy_42)",
                        "base_x": 0.6987, "base_y": -0.2512, "base_yaw": 3.1416, "reach_m": 0.18, "zoom": 3, "updated_at": now_init},
            "arm_a": {"target_id": "arm_a", "kind": "omx_ai", "label": "OMX-AI #1 (북동 상차 · Arm A)",
                      "base_x": 0.551, "base_y": 0.365, "base_yaw": -1.5708, "reach_m": 0.28, "zoom": 4, "updated_at": now_init},
            "arm_b": {"target_id": "arm_b", "kind": "omx_ai", "label": "OMX-AI #2 (동북 상차 · Arm B)",
                      "base_x": 0.956, "base_y": 0.370, "base_yaw": -1.5708, "reach_m": 0.28, "zoom": 4, "updated_at": now_init},
            "arm_s": {"target_id": "arm_s", "kind": "omx_ai", "label": "OMX-AI #3 (동남 분류 · Arm S)",
                      "base_x": 0.960, "base_y": -0.035, "base_yaw": 3.1416, "reach_m": 0.28, "zoom": 4, "updated_at": now_init},
        }
        self._anchor_states: dict[str, dict] = {}
        self._omx_cells: dict[str, dict] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.sources)

    def retarget(self, sources: Sequence[SightingSource]) -> None:
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
                  "robot_markers": dict(source.robot_markers),
                  "occupied": self.occupied(source)[0]}
        if self.identity is not None:
            config["identity_challenge"] = self.identity.challenge_for(source.source_id)
            config["identity_challenges"] = self.identity.challenges_for(source.source_id)
        if self.auto_locate is not None and self.auto_locate.stream_wanted():
            config["stream_wanted"] = True
        return config

    def accept(self, authorization: Optional[str], payload: OverheadDetectionsPayload) -> dict:
        source = self.authenticate(authorization)
        state = self._sources[source.source_id]
        if payload.source_id != source.source_id:
            raise TrackingError(403, "SOURCE_MISMATCH", "payload source does not match the token")
        if payload.map_id != source.map_id:
            state.last_error = "MAP_MISMATCH"
            raise TrackingError(409, "MAP_MISMATCH", "detection map does not match source configuration")
        if payload.calibration_revision is not None and payload.calibration_revision not in self._revisions(source):
            state.last_error = "CALIBRATION_MISMATCH"
            raise TrackingError(409, "CALIBRATION_MISMATCH", "detection calibration is neither the marker nor the approved one")
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
        if payload.status == "OK":
            state.last_ok = payload
        state.last_error = None
        state.arrivals.append(now)
        self._trim(state, now)
        if self.identity is not None:
            self.identity.on_detections(source.source_id, payload)
        return {"accepted": True, "source_id": source.source_id, "seq": payload.seq, "status": payload.status}

    def approve(self, body: Mapping, *, approved_by: str) -> dict:
        source = self._by_id.get(body.get("source_id"))
        if source is None:
            raise TrackingError(404, "UNKNOWN_SOURCE", "no configured source with this id")
        map_id = body.get("map_id") or source.map_id
        if map_id != source.map_id:
            raise TrackingError(409, "MAP_MISMATCH", "calibration map does not match source configuration")
        try:
            image, bounds = body["image"], body["track_bounds_m"]
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
        return {"calibrations": [record.to_dict() for record in self.calibrations.all()], "use": "display-only"}

    def request_relearn(self, source_id: str) -> dict:
        if source_id not in self._by_id:
            raise TrackingError(404, "UNKNOWN_SOURCE", "no configured source with this id")
        state = self._sources[source_id]
        state.relearn_seq += 1
        regions, unlocated = self.occupied(self._by_id[source_id])
        return {"source_id": source_id, "relearn_seq": state.relearn_seq,
                "occupied": len(regions), "unlocated": unlocated}

    def occupied(self, source: SightingSource) -> tuple[list[dict], list[str]]:
        now = self._clock()
        state = self._sources[source.source_id]
        regions, unlocated = [], []
        payload = state.payload if state.payload is not None and now - state.payload.captured_at <= self.lease_s else None
        markers = {d.marker_id: d for d in (payload.detections if payload is not None else ()) if d.marker_id is not None}
        assigned = dict(source.robot_markers)
        for rid in source.robot_ids:
            region = None
            marker = markers.pop(assigned.get(rid), None) if rid in assigned else None
            if marker is not None:
                region = (marker.x, marker.y, ROBOT_RADIUS_M + REGION_MARGIN_M, "marker")
            pose = self.map_pose(rid) if region is None and self.map_pose is not None else None
            if (region is None and pose is not None and getattr(pose, "state", "UNKNOWN") != "UNKNOWN"
                    and getattr(pose, "map_id", None) in (None, source.map_id)
                    and _finite(getattr(pose, "x", None), getattr(pose, "y", None))):
                extra = min(MAX_BRIDGE_EXTRA_M, max(0.0, float(getattr(pose, "dead_reckon_m", 0.0) or 0.0)))
                region = (pose.x, pose.y, ROBOT_RADIUS_M + REGION_MARGIN_M + extra,
                          getattr(pose, "anchor_source", None) or "map_pose")
            own = self._pose(rid, source.map_id, now) if region is None else None
            if own is not None and own.verified:
                region = (own.x, own.y, ROBOT_RADIUS_M + REGION_MARGIN_M + OWN_POSE_EXTRA_M, "own_pose")
            if region is None:
                unlocated.append(rid)
            else:
                regions.append({"robot_id": rid, "x": region[0], "y": region[1], "radius_m": region[2], "basis": region[3]})
        for marker in markers.values():
            regions.append({"robot_id": None, "x": marker.x, "y": marker.y,
                            "radius_m": ROBOT_RADIUS_M + REGION_MARGIN_M, "basis": "marker"})
        last = state.last_ok
        if last is not None and now - last.captured_at <= LAST_SEEN_S:
            regions.extend({"robot_id": None, "x": d.x, "y": d.y, "radius_m": d.footprint_m / 2 + REGION_MARGIN_M,
                            "basis": "blob"} for d in last.detections if d.marker_id is None)
        return regions, unlocated

    def now(self) -> float:
        return self._clock()

    def observe_states(self, robots: Sequence[Mapping], *, now: Optional[float] = None,
                       observed: Optional[Mapping[str, float]] = None) -> None:
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
        drift = dict(self._drift_provider()) if self._drift_provider is not None else {}
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
                "source_id": source.source_id, "map_id": source.map_id, "status": status,
                "calibration_revision": payload.calibration_revision if fresh else None,
                "age_ms": None if payload is None else max(0, round((now - payload.captured_at) * 1000.0)),
                "fps": round(len(state.arrivals) / FPS_WINDOW_S, 1),
                "last_error": state.last_error, "relearn_seq": state.relearn_seq,
                "unknown_floor": [area.model_dump() for area in payload.unknown_floor] if fresh else [],
                "tuning": payload.tuning.model_dump(mode="json") if fresh and payload.tuning is not None else None,
                "calibration_drift": drift.get(source.source_id),
                "calibration_health": self.health.view(source.source_id) if self.health is not None else None,
            })
            seen = ([Seen(d.x, d.y, d.footprint_m, d.score) for d in payload.detections if d.marker_id is None]
                    if fresh and status == "OK" else None)
            poses = {rid: self._pose(rid, source.map_id, now) for rid in source.robot_ids}
            assignments = {marker: rid for rid, marker in source.robot_markers}
            measured, unassigned = {}, {}
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

    def anchor_configs(self) -> list[dict]:
        return [dict(item) for item in self._anchors.values()]

    def accept_anchors(self, authorization: Optional[str], body: Mapping) -> dict:
        source = self.authenticate(authorization)
        now = self._clock()
        targets = body.get("targets") if isinstance(body, Mapping) else None
        if not isinstance(targets, Sequence):
            return {"accepted": False, "count": 0}
        count = 0
        for row in targets:
            if not isinstance(row, Mapping):
                continue
            tid = str(row.get("target_id") or "")
            if not tid:
                continue
            self._anchor_states[tid] = {**dict(row), "source_id": source.source_id, "received_at": now}
            count += 1
        return {"accepted": True, "source_id": source.source_id, "count": count}

    def set_anchor(self, body: Mapping, *, principal_id: str) -> dict:
        tid = str(body.get("target_id") or "").strip()
        if not tid:
            raise TrackingError(422, "INVALID_ANCHOR", "target_id is required")
        try:
            bx, by = float(body["base_x"]), float(body["base_y"])
            byaw = float(body.get("base_yaw", -1.5708))
            reach = float(body.get("reach_m", 0.28 if tid.startswith("arm_") else 0.38))
            zoom = int(body.get("zoom", 4 if tid.startswith("arm_") else 3))
        except (KeyError, TypeError, ValueError) as exc:
            raise TrackingError(422, "INVALID_ANCHOR", str(exc)) from exc
        if not _finite(bx, by, byaw, reach):
            raise TrackingError(422, "INVALID_ANCHOR", "anchor coordinates must be finite")
        now = self._clock()
        prior = self._anchors.get(tid, {})
        kind = str(body.get("kind") or prior.get("kind") or ("omx_ai" if tid.startswith("arm_") else "pinky"))
        label = str(body.get("label") or prior.get("label") or tid)
        self._anchors[tid] = {
            "target_id": tid, "kind": kind, "label": label,
            "base_x": round(bx, 4), "base_y": round(by, 4), "base_yaw": round(byaw, 4),
            "reach_m": round(max(0.12, min(0.80, reach)), 3), "zoom": max(2, min(6, zoom)),
            "updated_at": now, "updated_by": principal_id,
        }
        return self._anchors[tid]

    def anchors_snapshot(self, now: Optional[float] = None) -> dict:
        if now is None:
            now = self._clock()
        out = []
        for tid, anc in self._anchors.items():
            live = self._anchor_states.get(tid)
            fresh = live is not None and (now - float(live.get("received_at") or 0.0) <= self.lease_s * 2.0)
            ext = 0.08 if anc.get("kind") == "pinky" else 0.14
            byaw = float(anc.get("base_yaw") or -1.5708)
            default_hx = round(float(anc["base_x"]) + math.cos(byaw) * ext, 4)
            default_hy = round(float(anc["base_y"]) + math.sin(byaw) * ext, 4)
            row = {
                **anc,
                "head_x": round(float(live["head_x"]), 4) if fresh and "head_x" in live else default_hx,
                "head_y": round(float(live["head_y"]), 4) if fresh and "head_y" in live else default_hy,
                "head_yaw": round(float(live["head_yaw"]), 4) if fresh and "head_yaw" in live else round(byaw, 4),
                "extension_m": round(float(live.get("extension_m", ext)), 4) if fresh else ext,
                "speed_mps": round(float(live.get("speed_mps", 0.0)), 4) if fresh else 0.0,
                "moving": bool(live.get("moving", False)) if fresh else False,
                "confidence": round(float(live.get("confidence", 0.0)), 3) if fresh else 0.0,
                "source_id": live.get("source_id", "ceiling_north") if live else "ceiling_north",
                "age_ms": round(max(0.0, (now - float(live.get("captured_at") or now)) * 1000.0)) if fresh else None,
                "live": fresh,
            }
            if anc.get("kind") == "pinky" and fresh:
                row["base_x"] = round(float(live.get("base_x", anc["base_x"])), 4)
                row["base_y"] = round(float(live.get("base_y", anc["base_y"])), 4)
            cell = self._omx_cells.get(tid)
            if cell and cell.get("reachable"):
                row["cell_status"] = f"{cell.get('state', 'IDLE')}{' · 토크ON' if cell.get('torque') else ''}"
                if cell.get("joints_summary"):
                    row["joints_summary"] = cell["joints_summary"]
            out.append(row)
        return {"ts": now, "targets": out}

    def latest(self, source_id: str) -> Optional[OverheadDetectionsPayload]:
        state = self._sources.get(source_id)
        payload = None if state is None else state.payload
        if payload is None or self._clock() - payload.captured_at > self.lease_s:
            return None
        return payload

    def robot_state(self, robot_id: str) -> Optional[dict]:
        entry = self._states.get(robot_id)
        if entry is None or not 0.0 <= self._clock() - entry[1] <= self.state_fresh_s:
            return None
        return entry[0]

    def approved_revision(self, source: SightingSource) -> Optional[str]:
        record = self.calibrations.get(source.source_id)
        if record is None or record.map_id != source.map_id:
            return None
        if self.health is not None and self.health.blocks(source.source_id, record.calibration_revision):
            return None
        return record.calibration_revision

    def revisions(self, source: SightingSource) -> set[str]:
        return self._revisions(source)

    def _revisions(self, source: SightingSource) -> set[str]:
        allowed = {source.calibration_revision}
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


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def _render(track: Track, source_id: str) -> dict:
    return {
        "robot_id": track.robot_id, "status": track.status, "source_id": source_id, "offset_m": track.offset_m,
        "camera": None if track.camera is None else {
            "x": track.camera.x, "y": track.camera.y,
            "footprint_m": track.camera.footprint_m, "score": track.camera.score},
        "pose": None if track.pose is None else {"x": track.pose.x, "y": track.pose.y},
        "pose_frame_verified": None if track.pose is None else track.pose.verified,
    }
