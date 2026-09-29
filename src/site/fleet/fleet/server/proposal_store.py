"""Durable, non-executable operator/model candidate records for Fleet Missions."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .sqlite_policy import configure_connection, enable_wal


class ProposalConflict(ValueError):
    """A proposal identity was reused or a state transition conflicts."""


class ProposalRejected(ValueError):
    """A candidate cannot be resolved against current trusted evidence."""

    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code):
            raise ValueError("proposal rejection must use a stable uppercase reason code")
        self.code = code
        super().__init__(code)


_ALLOWED_FIELDS = {
    "request_id", "source", "model_id", "instruction", "provider_interaction_id",
    "provider_call_id", "source_observation", "target_selector", "destination_selector",
}
_SOURCE_FIELDS = {
    "observation_id", "camera_id", "frame_id", "observed_at", "image_sha256",
    "coordinate_space", "image_transform", "calibration_revision", "transform_revision",
}
_TRANSFORM_FIELDS = {
    "source_width", "source_height", "crop_xyxy", "model_width", "model_height",
    "rotation_quadrants_clockwise",
}
_SELECTOR_FIELDS = {"label", "point_yx_1000", "box_yxyx_1000"}
_MAX_CANDIDATE_BYTES = 32 * 1024


def _text(name: str, value: object, *, limit: int = 192) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{name} must be a non-empty trimmed string of at most {limit} characters")
    return value


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("proposal data must be finite JSON") from exc


def _check_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("candidate must be a JSON object")
    document = dict(value)

    if set(document) - _ALLOWED_FIELDS:
        forbidden = set(document) - _ALLOWED_FIELDS
        if forbidden & {"principal_id", "actor_id"}:
            raise ValueError("authenticated principal cannot come from candidate data")
        if forbidden & {"image", "image_bytes", "image_data", "raw_image", "frame_bytes",
                        "jpeg", "png", "base64"}:
            raise ValueError("candidate image bytes must not be persisted")
        raise ValueError("candidate contains fields outside the selector metadata contract")
    for field, limit in (("request_id", 160), ("source", 96), ("model_id", 128),
                         ("instruction", 2000), ("provider_interaction_id", 160),
                         ("provider_call_id", 160)):
        if field in document:
            _text(field, document[field], limit=limit)
    source = document.get("source_observation")
    if not isinstance(source, Mapping) or set(source) - _SOURCE_FIELDS:
        raise ValueError("candidate source_observation has unsupported fields")
    for field in _SOURCE_FIELDS - {"image_transform"}:
        if field in source:
            _text(f"source_observation.{field}", source[field],
                  limit=160 if field in {"observation_id", "camera_id", "frame_id"} else 96)
    transform = source.get("image_transform")
    if transform is not None and (
            not isinstance(transform, Mapping) or set(transform) - _TRANSFORM_FIELDS):
        raise ValueError("candidate image transform has unsupported fields")
    for selector_name in ("target_selector", "destination_selector"):
        selector = document.get(selector_name)
        if not isinstance(selector, Mapping) or set(selector) - _SELECTOR_FIELDS:
            raise ValueError(f"candidate {selector_name} has unsupported fields")
        if "label" in selector:
            _text(f"{selector_name}.label", selector["label"], limit=160)
    encoded = _json(document)
    if len(encoded.encode("utf-8")) > _MAX_CANDIDATE_BYTES:
        raise ValueError("candidate metadata exceeds 32 KiB")
    return json.loads(encoded)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class ProposalStore:
    """SQLite proposal metadata store; it never stores source image bytes."""

    def __init__(self, path: Path | str, *, retention_days: int = 30) -> None:
        if type(retention_days) is not int or not 1 <= retention_days <= 365:
            raise ValueError("retention_days must be an integer from 1 to 365")
        self.path = Path(path)
        self.retention_days = retention_days
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS fleet_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    workcell_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    candidate_digest TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('PROPOSED', 'RESOLVING', 'UNRESOLVED', 'RESOLVED', 'REJECTED')),
                    mission_id TEXT,
                    resolved_json TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    UNIQUE(principal_id, request_key)
                );
                CREATE INDEX IF NOT EXISTS fleet_proposals_expiry
                    ON fleet_proposals(expires_at);
                """
            )
        self.purge_expired()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["candidate"] = json.loads(result.pop("candidate_json"))
        if result["resolved_json"] is not None:
            result["resolution"] = json.loads(result.pop("resolved_json"))
        else:
            del result["resolved_json"]
        return result

    def create(self, *, principal_id: str, request_key: str,
               workcell_id: str, instance_id: str,
               candidate: Mapping[str, Any]) -> dict[str, Any]:
        principal_id = _text("principal_id", principal_id, limit=96)
        request_key = _text("request_key", request_key, limit=160)
        workcell_id = _text("workcell_id", workcell_id, limit=96)
        instance_id = _text("instance_id", instance_id, limit=96)
        candidate_json = _json(_check_candidate(candidate))
        request_json = _json({"candidate": json.loads(candidate_json),
                              "workcell_id": workcell_id, "instance_id": instance_id})
        digest = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        self.purge_expired()
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        expires = now.replace(microsecond=0) + timedelta(days=self.retention_days)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT * FROM fleet_proposals WHERE principal_id=? AND request_key=?",
                (principal_id, request_key),
            ).fetchone()
            if prior is not None:
                if prior["candidate_digest"] != digest:
                    raise ProposalConflict("request_key is already bound to a different candidate")
                connection.commit()
                return {"proposal": self._row(prior), "created": False}
            proposal_id = str(uuid.uuid4())
            stamp = now.isoformat(timespec="microseconds")
            connection.execute(
                """INSERT INTO fleet_proposals
                   (proposal_id, principal_id, request_key, workcell_id, instance_id,
                    candidate_digest, candidate_json,
                    state, created_at, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?, ?)""",
                (proposal_id, principal_id, request_key, workcell_id, instance_id,
                 digest, candidate_json,
                 stamp, stamp, expires.isoformat()),
            )
            row = connection.execute("SELECT * FROM fleet_proposals WHERE proposal_id=?",
                                     (proposal_id,)).fetchone()
            connection.commit()
        return {"proposal": self._row(row), "created": True}

    def finalize_resolution(self, mission_store: Any, *, proposal_id: str,
                            principal_id: str, resolution: Mapping[str, Any],
                            mission_request: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
        """Atomically insert a Mission draft and mark its source proposal resolved."""
        proposal_id = _text("proposal_id", proposal_id)
        principal_id = _text("principal_id", principal_id, limit=96)
        resolution_json = _json(dict(resolution))
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fleet_proposals WHERE proposal_id=? AND principal_id=?",
                (proposal_id, principal_id),
            ).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            if row["state"] == "RESOLVED":
                mission = mission_store.get_mission(proposal_id)
                if mission is None:
                    raise ProposalConflict("resolved proposal has no durable Mission")
                connection.commit()
                return self._row(row), mission, False
            if row["state"] != "PROPOSED":
                raise ProposalConflict("proposal is not available for resolution")
            mission_result = mission_store.create_proposal(
                mission_id=proposal_id, principal_id=principal_id,
                request_key=row["request_key"], action_kind="PICK_PLACE",
                workcell_id=row["workcell_id"], instance_id=row["instance_id"],
                plan=mission_request["plan"], goal_predicate=mission_request["goal_predicate"],
                connection=connection,
            )
            connection.execute(
                """UPDATE fleet_proposals SET state='RESOLVED', resolved_json=?, mission_id=?,
                   reason=NULL, updated_at=? WHERE proposal_id=? AND principal_id=?""",
                (resolution_json, proposal_id, _now(), proposal_id, principal_id),
            )
            updated = connection.execute("SELECT * FROM fleet_proposals WHERE proposal_id=?",
                                         (proposal_id,)).fetchone()
            mission = mission_result["mission"]
            connection.commit()
        if mission is None:
            raise ProposalConflict("Mission draft was not persisted")
        return self._row(updated), mission, True

    def get(self, proposal_id: str, *, principal_id: str | None = None) -> dict[str, Any] | None:
        proposal_id = _text("proposal_id", proposal_id)
        self.purge_expired()
        with closing(self._connect()) as connection:
            if principal_id is None:
                row = connection.execute("SELECT * FROM fleet_proposals WHERE proposal_id=?",
                                         (proposal_id,)).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM fleet_proposals WHERE proposal_id=? AND principal_id=?",
                    (proposal_id, _text("principal_id", principal_id, limit=96)),
                ).fetchone()
        return self._row(row)

    def by_request(self, *, principal_id: str, request_key: str) -> dict[str, Any] | None:
        self.purge_expired()
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM fleet_proposals WHERE principal_id=? AND request_key=?",
                (_text("principal_id", principal_id, limit=96),
                 _text("request_key", request_key, limit=160)),
            ).fetchone()
        return self._row(row)

    def set_resolution(self, proposal_id: str, *, state: str,
                       resolution: Mapping[str, Any] | None = None,
                       mission_id: str | None = None, reason: str | None = None) -> dict[str, Any]:
        if state not in {"UNRESOLVED", "RESOLVED", "REJECTED"}:
            raise ValueError("invalid proposal resolution state")
        if state == "RESOLVED" and (resolution is None or mission_id is None):
            raise ValueError("resolved proposal requires a resolution and mission_id")
        if state != "RESOLVED" and resolution is not None:
            raise ValueError("only resolved proposals may contain a resolution")
        resolution_json = _json(dict(resolution)) if resolution is not None else None
        reason = _text("reason", reason, limit=96) if reason is not None else None
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM fleet_proposals WHERE proposal_id=?",
                                     (proposal_id,)).fetchone()
            if row is None:
                raise KeyError(proposal_id)
            if row["state"] not in {"PROPOSED", "RESOLVING"}:
                if row["state"] == state and row["mission_id"] == mission_id:
                    connection.commit()
                    return self._row(row)
                raise ProposalConflict("proposal resolution is immutable")
            connection.execute(
                """UPDATE fleet_proposals SET state=?, resolved_json=?, mission_id=?,
                   reason=?, updated_at=? WHERE proposal_id=?""",
                (state, resolution_json, mission_id, reason, _now(), proposal_id),
            )
            updated = connection.execute("SELECT * FROM fleet_proposals WHERE proposal_id=?",
                                         (proposal_id,)).fetchone()
            connection.commit()
        return self._row(updated)

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Delete expired candidate metadata while leaving Mission history intact."""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("proposal expiry time must be timezone-aware")
        stamp = current.astimezone(timezone.utc).isoformat()
        with closing(self._connect()) as connection:
            cursor = connection.execute("DELETE FROM fleet_proposals WHERE expires_at<=?", (stamp,))
            return cursor.rowcount
