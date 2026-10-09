"""Read-only site-map sightings accepted from source-scoped vision workers (D-257)."""

from __future__ import annotations

import hmac
import math
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from core_common.protocol.place_markers import PlaceMarkerPayload
from core_common.protocol.sightings import SiteSightingPayload
from fleet.server.sighting_store import SightingStore

SIGHTING_LEASE_S = 1.0
MAX_FUTURE_S = 0.05
#: D-564: a place marker observation teaches a place only this long after capture.
PLACE_MARKER_LEASE_S = 2.0


class SightingError(ValueError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class SightingSource:
    """One revocable credential and the exact sighting domain it may write."""

    source_id: str
    token: str
    robot_ids: tuple[str, ...]
    map_id: str
    calibration_revision: str
    # D-484: None for a field_boundary source (no printed corner markers).
    corner_marker_ids: tuple[int, int, int, int] | None
    # Display geometry only (the surveyed rectangle in the map frame); never motion input.
    corner_world_m: tuple[tuple[float, float], ...] | None = None
    robot_markers: tuple[tuple[str, int], ...] = ()
    # D-341 6: how the phone feeding this source authenticates to Vision (static | paired).
    credential: str = "static"
    # D-484: where the worker measures the image-to-map calibration from.
    calibration_source: str = "corner_markers"
    # D-564: floor place marker ids this source may report (display and teach only).
    place_markers: tuple[int, ...] = ()


class SightingService:
    """Keep one derived pose per robot; no video or command surface is exposed."""

    def __init__(
        self,
        sources: Sequence[SightingSource],
        *,
        known_robot_ids: Sequence[str],
        clock: Callable[[], float] = time.time,
        lease_s: float = SIGHTING_LEASE_S,
        store: SightingStore | None = None,
        approved_revision: Callable[[SightingSource], str | None] | None = None,
    ) -> None:
        self._clock = clock
        #: D-587 2: the source's approved D-457 record revision on its map, or None (the app
        #: wires TrackingService.approved_revision). Without it no approved_record sighting passes.
        self.approved_revision = approved_revision
        if not math.isfinite(lease_s) or lease_s <= 0:
            raise ValueError("sighting lease must be positive and finite")
        self.lease_s = lease_s
        self._store = store
        known = set(known_robot_ids)
        #: The live roster (D-361 5); SiteRoster replaces it on add/remove.
        self.known_robot_ids = frozenset(known)
        self._sources: list[SightingSource] = list(sources)
        self._by_id: dict[str, SightingSource] = {}
        tokens: set[str] = set()
        for source in self._sources:
            if (not isinstance(source.source_id, str) or not source.source_id.strip()
                    or not isinstance(source.token, str) or not source.token):
                raise ValueError("sighting source id and token are required")
            if source.source_id in self._by_id:
                raise ValueError("sighting source ids must be unique")
            if source.token in tokens:
                raise ValueError("sighting source tokens must be unique")
            if (not source.robot_ids or any(not isinstance(robot_id, str) for robot_id in source.robot_ids)
                    or not set(source.robot_ids).issubset(known)):
                raise ValueError(f"sighting source {source.source_id!r} has an unknown robot target")
            if len(set(source.robot_ids)) != len(source.robot_ids):
                raise ValueError("sighting source robot targets must be unique")
            if (not isinstance(source.map_id, str) or not source.map_id.strip()
                    or not isinstance(source.calibration_revision, str)
                    or not source.calibration_revision.strip()):
                raise ValueError("sighting map and calibration revision are required")
            if source.calibration_source not in ("corner_markers", "field_boundary"):
                raise ValueError("sighting calibration source must be corner_markers or field_boundary")
            if source.calibration_source == "field_boundary":
                if source.corner_marker_ids is not None:
                    raise ValueError(f"sighting source {source.source_id!r} is field_boundary "
                                     "and must not carry corner marker ids")
                if source.corner_world_m is None:
                    raise ValueError(f"sighting source {source.source_id!r} is field_boundary "
                                     "and needs the surveyed corner_world_m rectangle")
            elif (len(set(source.corner_marker_ids)) != 4
                    or any(type(v) is not int or v < 0 for v in source.corner_marker_ids)):
                raise ValueError("sighting source needs four distinct non-negative corner ids")
            tokens.add(source.token)
            self._by_id[source.source_id] = source
        self._latest: dict[str, dict] = store.load_latest() if store is not None else {}
        #: D-564: (source_id, marker_id) -> newest accepted place marker row; memory only.
        self._place_markers: dict[tuple[str, int], dict] = {}

    @property
    def sources(self) -> tuple[SightingSource, ...]:
        return tuple(self._sources)

    @property
    def enabled(self) -> bool:
        return bool(self._sources)

    def uses_token(self, token: str) -> bool:
        matched = False
        for source in self._sources:
            matched |= hmac.compare_digest(token, source.token)
        return matched

    def reuses_any(self, predicate: Callable[[str], bool]) -> bool:
        reused = False
        for source in self._sources:
            reused |= predicate(source.token)
        return reused

    def accept(self, authorization: str | None, payload: SiteSightingPayload) -> dict:
        source = self._authenticate(authorization)
        if payload.robot_id not in source.robot_ids or payload.robot_id not in self.known_robot_ids:
            raise SightingError(403, "SIGHTING_TARGET_FORBIDDEN", "source cannot report this robot")
        if payload.map_id != source.map_id:
            raise SightingError(409, "MAP_MISMATCH", "sighting map does not match source configuration")
        payload_source = payload.calibration_source or "corner_markers"
        if payload_source == "approved_record":
            approved = self.approved_revision(source) if self.approved_revision is not None else None
            mismatch = approved is None or payload.calibration_revision != approved
        else:
            mismatch = (payload.calibration_revision != source.calibration_revision
                        or payload.corner_marker_ids != source.corner_marker_ids
                        or payload_source != source.calibration_source)
        if mismatch:
            raise SightingError(409, "CALIBRATION_MISMATCH",
                                "sighting calibration does not match source configuration")

        now = self._clock()
        age_s = now - payload.captured_at
        if age_s < -MAX_FUTURE_S:
            raise SightingError(409, "SIGHTING_FUTURE", "sighting capture time is in the future")
        if age_s > self.lease_s:
            raise SightingError(409, "SIGHTING_STALE", "sighting exceeded the display lease")
        prior = self._latest.get(payload.robot_id)
        if prior is not None and payload.captured_at <= prior["captured_at"]:
            raise SightingError(409, "SIGHTING_OUT_OF_ORDER", "sighting is not newer than readback")

        row = payload.model_dump(mode="json")
        row.update(source_id=source.source_id, received_at=now)
        if self._store is not None:
            self._store.save_sighting(row)
        self._latest[payload.robot_id] = row
        return self._render(row, now)

    def accept_place_markers(self, authorization: str | None, payload: PlaceMarkerPayload) -> dict:
        """D-564: same token, map, calibration and ordering checks as a sighting."""
        source = self._authenticate(authorization)
        if any(m.marker_id not in source.place_markers for m in payload.markers):
            raise SightingError(403, "PLACE_MARKER_FORBIDDEN", "source cannot report this place marker")
        if payload.map_id != source.map_id:
            raise SightingError(409, "MAP_MISMATCH", "place marker map does not match source configuration")
        if payload.calibration_revision != source.calibration_revision:
            raise SightingError(409, "CALIBRATION_MISMATCH",
                                "place marker calibration does not match source configuration")
        now = self._clock()
        age_s = now - payload.captured_at
        if age_s < -MAX_FUTURE_S:
            raise SightingError(409, "SIGHTING_FUTURE", "capture time is in the future")
        if age_s > PLACE_MARKER_LEASE_S:
            raise SightingError(409, "SIGHTING_STALE", "place marker exceeded the teach lease")
        if any(payload.captured_at <= self._place_markers.get((source.source_id, m.marker_id),
                                                              {"captured_at": -math.inf})["captured_at"]
               for m in payload.markers):
            raise SightingError(409, "SIGHTING_OUT_OF_ORDER", "place marker is not newer than readback")
        rows = []
        for marker in payload.markers:
            row = {**marker.model_dump(mode="json"), "source_id": source.source_id, "map_id": payload.map_id,
                   "calibration_revision": payload.calibration_revision,
                   "captured_at": payload.captured_at, "seq": payload.seq, "received_at": now}
            self._place_markers[(source.source_id, marker.marker_id)] = row
            rows.append(self._render(row, now, PLACE_MARKER_LEASE_S))
        return {"markers": rows}

    def place_markers_snapshot(self) -> dict:
        now = self._clock()
        return {"markers": [self._render(row, now, PLACE_MARKER_LEASE_S)
                            for row in self._place_markers.values()],
                "ts": now, "lease_s": PLACE_MARKER_LEASE_S}

    def fresh_place_marker(self, marker_id: int) -> dict | None:
        """The newest place marker row within the lease whose source config still matches, else None."""
        now = self._clock()
        best = None
        for (source_id, seen_id), row in self._place_markers.items():
            source = self._by_id.get(source_id)
            if (seen_id != marker_id or source is None or marker_id not in source.place_markers
                    or row["map_id"] != source.map_id
                    or row["calibration_revision"] != source.calibration_revision
                    or not -MAX_FUTURE_S <= now - row["captured_at"] <= PLACE_MARKER_LEASE_S):
                continue
            if best is None or row["captured_at"] > best["captured_at"]:
                best = row
        return dict(best) if best is not None else None

    def snapshot(self) -> dict:
        now = self._clock()
        return {
            "sightings": [self._render(row, now) for row in self._latest.values()],
            "ts": now,
            "lease_s": self.lease_s,
        }

    def site_map(self) -> dict | None:
        """Group configured site rectangles by map id; tokens are never included."""
        maps: dict[str, dict] = {}
        for source in self._sources:
            if source.corner_world_m is None:
                continue
            entry = maps.get(source.map_id)
            if entry is None:
                xs = [point[0] for point in source.corner_world_m]
                ys = [point[1] for point in source.corner_world_m]
                entry = maps[source.map_id] = {
                    "map_id": source.map_id,
                    "frame": "map",
                    "units": "m",
                    "polygon_m": [list(point) for point in source.corner_world_m],
                    "bounds_m": {"min_x": min(xs), "min_y": min(ys),
                                 "max_x": max(xs), "max_y": max(ys)},
                    "sources": [],
                }
            entry["sources"].append({
                "source_id": source.source_id,
                "calibration_revision": source.calibration_revision,
                "calibration_source": source.calibration_source,
                "corner_marker_ids": (None if source.corner_marker_ids is None
                                      else list(source.corner_marker_ids)),
                "robot_ids": list(source.robot_ids),
                "robot_markers": dict(source.robot_markers),
            })
        return {"maps": list(maps.values())} if maps else None

    def _authenticate(self, authorization: str | None) -> SightingSource:
        candidate = authorization or ""
        matched: SightingSource | None = None
        for source in self._sources:
            if hmac.compare_digest(candidate, f"Bearer {source.token}"):
                matched = source
        if matched is None:
            raise SightingError(401, "SIGHTING_UNAUTHORIZED", "source token required")
        return matched

    def _render(self, row: dict, now: float, lease_s: float | None = None) -> dict:
        out = dict(row)
        age_s = max(0.0, now - float(row["captured_at"]))
        out["age_ms"] = round(age_s * 1000.0)
        out["stale"] = age_s > (self.lease_s if lease_s is None else lease_s)
        return out
