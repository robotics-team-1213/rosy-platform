"""Durable policy-evidence submissions with fail-closed validation (D-268).

Every v1 submission is rejected: the observation-kind registry is empty by
design and the dispatch valve lives in task_service, not here. This module
never issues robot commands and never stores credentials or media.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Callable, Mapping

from pydantic import ValidationError

from core_common.protocol.policy_evidence import PolicyEvidencePayload
from fleet.server.policy_evidence_config import PolicyEvidenceSource
from fleet.server.sqlite_policy import configure_connection, enable_wal

TRANSIT_MAX_S = 0.300  # D-268 Decision 4: capture-to-Fleet receive bound.

_REASON_STATUS = {
    "EVIDENCE_SOURCE_UNKNOWN": 401,
    "EVIDENCE_INVALID": 422,
}


def status_code_for(reason: str) -> int:
    """Map an audit rejection reason to its HTTP status (409 by default)."""
    code = reason.split(":", 1)[0].strip()
    return _REASON_STATUS.get(code, 409)


class PolicyEvidenceError(ValueError):
    """The submission is rejected; `reason` is the audit vocabulary."""


class PolicyEvidenceStore:
    """Persist evidence attempts and their outcome without trusting the client source."""

    OBSERVATION_KINDS: frozenset[str] = frozenset()  # v1: empty — fail-closed.

    def __init__(self, sources: list[PolicyEvidenceSource], path: Path | str, *,
                 clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._by_token = {source.token: source for source in sources}
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS policy_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    outcome TEXT NOT NULL,
                    reason TEXT
                );
                CREATE TABLE IF NOT EXISTS policy_evidence_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    received_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS policy_evidence_received_at
                    ON policy_evidence(received_at DESC, evidence_id);
                PRAGMA user_version=1;
                """
            )
        if os.name != "nt":
            self.path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        return configure_connection(connection)

    def uses_token(self, token: str) -> bool:
        return token in self._by_token

    def reuses_any(self, predicate: Callable[[str], bool]) -> bool:
        return any(predicate(token) for token in self._by_token)

    def accept(self, authorization: str | None, payload: PolicyEvidencePayload | Mapping) -> dict:
        """Route entry: derive the source token from the Authorization header."""
        if not authorization or not authorization.startswith("Bearer "):
            raise PolicyEvidenceError("EVIDENCE_SOURCE_UNKNOWN")
        return self.submit(payload, token=authorization[len("Bearer "):], now=self._clock())

    def get(self, evidence_id: str) -> dict | None:
        """Return one decoded evidence record for task admission binding."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT evidence_id, source_id, payload_json, received_at, outcome, reason"
                " FROM policy_evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row(dict(zip(
            ["evidence_id", "source_id", "payload_json", "received_at", "outcome", "reason"],
            row)))

    def submit(self, payload: Mapping, *, token: str, now: float) -> dict:
        """Validate one submission and return its durable outcome record."""
        source = self._by_token.get(token)
        if source is None or source.revoked:
            raise PolicyEvidenceError("EVIDENCE_SOURCE_UNKNOWN")
        try:
            model = PolicyEvidencePayload.model_validate(dict(payload))
        except ValidationError as exc:
            raise PolicyEvidenceError(f"EVIDENCE_INVALID: {exc.error_count()} field errors") from exc

        canonical = model.model_dump_json()
        with closing(self._connect()) as connection:
            existing = connection.execute(
                "SELECT evidence_id, source_id, payload_json, received_at, outcome, reason"
                " FROM policy_evidence WHERE evidence_id = ?",
                (model.evidence_id,),
            ).fetchone()
            if existing is not None:
                if existing[2] != canonical or existing[1] != source.source_id:
                    raise PolicyEvidenceError("EVIDENCE_REPLAY")
                return self._row(dict(zip(
                    ["evidence_id", "source_id", "payload_json", "received_at", "outcome", "reason"],
                    existing)))

            reason = self._rejection_reason(model, source, now=now)
            outcome = "accepted" if reason is None else "rejected"
            with connection:
                connection.execute(
                    """INSERT INTO policy_evidence
                       (evidence_id, source_id, payload_json, received_at, outcome, reason)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (model.evidence_id, source.source_id, canonical, float(now), outcome, reason),
                )
                connection.execute(
                    """INSERT INTO policy_evidence_audit
                       (event, evidence_id, source_id, received_at) VALUES (?, ?, ?, ?)""",
                    (outcome, model.evidence_id, source.source_id, float(now)),
                )
            return {
                "evidence_id": model.evidence_id,
                "source_id": source.source_id,
                "payload": model.model_dump(),
                "received_at": float(now),
                "outcome": outcome,
                "reason": reason,
            }

    def _rejection_reason(self, model: PolicyEvidencePayload, source: PolicyEvidenceSource,
                          *, now: float) -> str | None:
        transit = now - model.captured_at
        if not 0.0 <= transit <= TRANSIT_MAX_S:
            return "EVIDENCE_TRANSIT_LATE"
        if model.task_kind not in source.task_kinds:
            return "EVIDENCE_TASK_KIND_NOT_REGISTERED"
        if model.asset_kind not in source.asset_kinds:
            return "EVIDENCE_ASSET_NOT_PERMITTED"
        if (model.map_id != source.map_id
                or model.calibration_revision != source.calibration_revision
                or model.model_revision not in source.model_revisions):
            return "EVIDENCE_REVISION_MISMATCH"
        if model.observation.kind not in self.OBSERVATION_KINDS:
            return "EVIDENCE_OBSERVATION_KIND_UNKNOWN"
        return None

    def latest(self, *, limit: int = 50) -> list[dict]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT evidence_id, source_id, payload_json, received_at, outcome, reason
                   FROM policy_evidence ORDER BY received_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        records = []
        for row in rows:
            record = self._row(dict(zip(
                ["evidence_id", "source_id", "payload_json", "received_at", "outcome", "reason"],
                row)))
            records.append(record)
        return records

    @staticmethod
    def _row(mapping: Mapping) -> dict:
        payload_json = mapping["payload_json"]
        return {
            "evidence_id": mapping["evidence_id"],
            "source_id": mapping["source_id"],
            "payload": json.loads(payload_json) if isinstance(payload_json, str) else payload_json,
            "received_at": mapping["received_at"],
            "outcome": mapping["outcome"],
            "reason": mapping["reason"],
        }
