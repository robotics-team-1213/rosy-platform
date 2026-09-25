"""Read-only site-map sightings accepted from source-scoped vision workers (D-257)."""

from __future__ import annotations

import hmac
import math
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from core_common.protocol.sightings import SiteSightingPayload
from fleet.server.sighting_store import SightingStore

SIGHTING_LEASE_S = 1.0
MAX_FUTURE_S = 0.05


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
    corner_marker_ids: tuple[int, int, int, int]


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
    ) -> None:
        self._clock = clock
        if not math.isfinite(lease_s) or lease_s <= 0:
            raise ValueError("sighting lease must be positive and finite")
        self.lease_s = lease_s
        self._store = store
        known = set(known_robot_ids)
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
            if (len(set(source.corner_marker_ids)) != 4
                    or any(type(v) is not int or v < 0 for v in source.corner_marker_ids)):
                raise ValueError("sighting source needs four distinct non-negative corner ids")
            tokens.add(source.token)
            self._by_id[source.source_id] = source
        self._latest: dict[str, dict] = store.load_latest() if store is not None else {}

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
        if payload.robot_id not in source.robot_ids:
            raise SightingError(403, "SIGHTING_TARGET_FORBIDDEN", "source cannot report this robot")
        if payload.map_id != source.map_id:
            raise SightingError(409, "MAP_MISMATCH", "sighting map does not match source configuration")
        if (payload.calibration_revision != source.calibration_revision
                or payload.corner_marker_ids != source.corner_marker_ids):
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

    def snapshot(self) -> dict:
        now = self._clock()
        return {
            "sightings": [self._render(row, now) for row in self._latest.values()],
            "ts": now,
            "lease_s": self.lease_s,
        }

    def _authenticate(self, authorization: str | None) -> SightingSource:
        candidate = authorization or ""
        matched: SightingSource | None = None
        for source in self._sources:
            if hmac.compare_digest(candidate, f"Bearer {source.token}"):
                matched = source
        if matched is None:
            raise SightingError(401, "SIGHTING_UNAUTHORIZED", "source token required")
        return matched

    def _render(self, row: dict, now: float) -> dict:
        out = dict(row)
        age_s = max(0.0, now - float(row["captured_at"]))
        out["age_ms"] = round(age_s * 1000.0)
        out["stale"] = age_s > self.lease_s
        return out
