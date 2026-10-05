"""Row-정규화 사전 준비 — 모든 공개 함수가 처음에 부른다."""

from __future__ import annotations

import sqlite3


def prepare(connection: sqlite3.Connection) -> None:
    """Row 접근을 이름으로 쓸 수 있게 하고 구간 표가 없으면 만든다(멱등)."""
    if connection.row_factory is None:
        connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS fleet_segments (
            segment_id TEXT PRIMARY KEY,
            map_revision TEXT NOT NULL,
            center_x REAL NOT NULL, center_y REAL NOT NULL,
            radius_m REAL NOT NULL,
            entry_x REAL NOT NULL, entry_y REAL NOT NULL,
            exit_x REAL NOT NULL, exit_y REAL NOT NULL,
            wait_x REAL NOT NULL, wait_y REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fleet_segment_grants (
            segment_id TEXT PRIMARY KEY REFERENCES fleet_segments(segment_id),
            state TEXT NOT NULL CHECK(state IN ('RESERVED','OCCUPIED','RELEASING','UNKNOWN')),
            task_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            robot_id TEXT NOT NULL,
            map_revision TEXT NOT NULL,
            generation INTEGER NOT NULL,
            entry_deadline TEXT NOT NULL,
            granted_at TEXT NOT NULL,
            entry_confirmed_at TEXT,
            exit_observed_at TEXT,
            terminal_status TEXT
        );
        """
    )
