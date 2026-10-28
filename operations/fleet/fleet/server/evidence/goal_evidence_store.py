"""Durable idempotent storage for accepted, bounded goal-evidence envelopes."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from .sqlite_policy import configure_connection, enable_wal

_MAX_EVIDENCE_BYTES = 16 * 1024


class GoalEvidenceConflict(ValueError):
    """An evidence identifier was replayed with different content."""


class GoalEvidenceStore:
    """Persist accepted evidence only; callers validate producer scope first."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.execute(
                """CREATE TABLE IF NOT EXISTS fleet_goal_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    producer_id TEXT NOT NULL,
                    mission_id TEXT,
                    action_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    CHECK(length(evidence_json) <= 16384)
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS fleet_goal_evidence_attempt "
                "ON fleet_goal_evidence(mission_id, action_id, attempt_id, received_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)

    @staticmethod
    def _serialize(evidence: Mapping[str, Any]) -> tuple[str, str]:
        if not isinstance(evidence, Mapping):
            raise ValueError("goal evidence must be an object")
        try:
            payload = json.dumps(
                dict(evidence), sort_keys=True, separators=(",", ":"), allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("goal evidence must be finite JSON") from exc
        if len(payload.encode("utf-8")) > _MAX_EVIDENCE_BYTES:
            raise ValueError("goal evidence exceeds the 16 KiB limit")
        return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _required_text(evidence: Mapping[str, Any], field: str) -> str:
        value = evidence.get(field)
        if (not isinstance(value, str) or not value.strip() or value != value.strip()
                or len(value) > 192 or any(ord(char) < 32 for char in value)):
            raise ValueError(f"goal evidence {field} is invalid")
        return value

    def submit(self, evidence: Mapping[str, Any], *, received_at: float,
               mission_id: str | None = None) -> dict[str, Any]:
        if isinstance(received_at, bool) or not isinstance(received_at, (int, float)):
            raise ValueError("received_at must be a finite timestamp")
        received_at = float(received_at)
        if not math.isfinite(received_at):
            raise ValueError("received_at must be a finite timestamp")
        evidence_id = self._required_text(evidence, "evidence_id")
        producer_id = self._required_text(evidence, "producer_id")
        action_id = self._required_text(evidence, "action_id")
        attempt_id = self._required_text(evidence, "attempt_id")
        payload, digest = self._serialize(evidence)
        if mission_id is not None and (not isinstance(mission_id, str) or not mission_id.strip()):
            raise ValueError("mission_id must be a non-blank string")

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                prior = connection.execute(
                    "SELECT * FROM fleet_goal_evidence WHERE evidence_id=?", (evidence_id,),
                ).fetchone()
                if prior is not None:
                    if (prior["payload_digest"] != digest or prior["mission_id"] != mission_id):
                        raise GoalEvidenceConflict(
                            "evidence identity was reused with different content or mission"
                        )
                    result = self._row(prior)
                    result["created"] = False
                    connection.commit()
                    return result
                connection.execute(
                    """INSERT INTO fleet_goal_evidence
                       (evidence_id, producer_id, mission_id, action_id, attempt_id,
                        payload_digest, evidence_json, received_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (evidence_id, producer_id, mission_id, action_id, attempt_id,
                     digest, payload, received_at),
                )
                connection.commit()
                return {
                    "evidence_id": evidence_id, "producer_id": producer_id,
                    "mission_id": mission_id, "action_id": action_id,
                    "attempt_id": attempt_id, "payload_digest": digest,
                    "evidence": json.loads(payload), "received_at": received_at,
                    "created": True,
                }
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["evidence"] = json.loads(result.pop("evidence_json"))
        return result

    def get(self, evidence_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM fleet_goal_evidence WHERE evidence_id=?", (evidence_id,),
            ).fetchone()
        return None if row is None else self._row(row)

    def latest_for_attempt(self, *, mission_id: str, action_id: str,
                           attempt_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT * FROM fleet_goal_evidence
                   WHERE mission_id=? AND action_id=? AND attempt_id=?
                   ORDER BY received_at DESC, evidence_id DESC LIMIT 1""",
                (mission_id, action_id, attempt_id),
            ).fetchone()
        return None if row is None else self._row(row)
