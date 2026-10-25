"""D-865 P2c 정책 승인 감사 저장소 — 상한·감사의 재시작 생존.

LineStuckAnswerLog(reports.py) 패턴: 같은 Fleet SQLite, CREATE IF NOT EXISTS +
INSERT. 사람 승인 원장 행위는 mission_store 이벤트가 이미 남긴다 — 이 표는 정책
principal 판정(ADMITTED/HELD)과 범위 revision만 담는다. 상한 `_issued` 는 이 표의
ADMITTED 행 수에서 읽는다(재시작 후에도 유지).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

from fleet.server.sqlite_policy import configure_connection

_SCHEMA = """CREATE TABLE IF NOT EXISTS fleet_policy_admission_audit (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    mission_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    scope_revision TEXT NOT NULL,
    generation INTEGER NOT NULL,
    reason TEXT
)"""


class PolicyAdmissionAuditLog:
    """Bounded by use, not by schema: /audit reads the newest rows only."""

    def __init__(self, path: str):
        self.path = str(path)
        with closing(self._connect()) as connection:
            connection.execute(_SCHEMA)
            connection.commit()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        configure_connection(connection)
        return connection

    def append(self, *, at: str, mission_id: str, outcome: str,
               scope_revision: str, generation: int, reason: str | None) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO fleet_policy_admission_audit "
                "(at, mission_id, outcome, scope_revision, generation, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (at, mission_id, outcome, scope_revision, generation, reason))
            connection.commit()

    def issued_count(self, scope_revision: str) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM fleet_policy_admission_audit "
                "WHERE scope_revision=? AND outcome='ADMITTED'",
                (scope_revision,)).fetchone()
        return int(row["n"])

    def latest(self, limit: int = 100) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT at, mission_id, outcome, scope_revision, generation, reason "
                "FROM fleet_policy_admission_audit ORDER BY entry_id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(row) for row in rows]
