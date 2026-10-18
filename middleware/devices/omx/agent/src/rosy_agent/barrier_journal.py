"""Durable PHASE_WAIT and barrier release records in the owner's Action journal (D-780 §3).

The barrier rows live in the same SQLite file as the Action store and the local stop latch.
Every arrival, release and expiry also appends an ``omx_action_events`` row, so the Action's
journal watermark covers it. Nothing here submits a ROS goal; the phase runner does that only
after the gate reads a recorded release.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from core_common.protocol.cell_transfer import CellTransferBarrier, FleetCellTransferGrant
from core_common.protocol.workcell_barrier import BarrierState


#: Boot id given to rows written before boot ids existed; never equal to a live ``uuid4().hex``.
PRE_BOOT_ID = "pre-boot-id"


class BarrierRefused(PermissionError):
    """The barrier journal state does not permit the requested transition."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("barrier timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


class BarrierJournal:
    """Barrier arrival/release/expiry rows keyed by Action attempt and barrier id.

    ``arrived_monotonic``/``released_monotonic`` are only comparable within one process: each
    row records the ``boot_id`` of the journal object that wrote it. A row from an earlier boot is
    never released and never timed against this boot's clock (the owner does not resume an
    execution after a restart; D-386, no replay).
    """

    def __init__(self, path: Path | str, *, now: Callable[[], datetime] | None = None,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.path = Path(path)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic
        self.boot_id = uuid.uuid4().hex
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS omx_action_barriers (
                    action_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    barrier_id TEXT NOT NULL,
                    gated_phase TEXT NOT NULL,
                    coupling_after TEXT NOT NULL,
                    max_wait_s REAL NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('waiting', 'released', 'expired')),
                    authority_epoch INTEGER NOT NULL,
                    dispatch_generation INTEGER NOT NULL,
                    arrived_at TEXT NOT NULL,
                    arrived_monotonic REAL NOT NULL,
                    released_at TEXT,
                    released_monotonic REAL,
                    release_json TEXT,
                    expired_at TEXT,
                    boot_id TEXT NOT NULL,
                    PRIMARY KEY(action_id, attempt_id, barrier_id)
                )
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(omx_action_barriers)")}
            if "boot_id" not in columns:
                # A table from before boot ids: its rows get a boot id no process ever has, so they
                # are never released or timed against this boot's clock (fail closed).
                connection.execute("ALTER TABLE omx_action_barriers ADD COLUMN boot_id TEXT NOT NULL "
                                   f"DEFAULT '{PRE_BOOT_ID}'")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _view(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        view = dict(row)
        release = view.pop("release_json")
        view["release"] = json.loads(release) if release else None
        return view

    @staticmethod
    def _event(connection: sqlite3.Connection, action_id: str, attempt_id: str,
               event_type: str, detail: Mapping[str, Any], created_at: str) -> None:
        action = connection.execute("SELECT state FROM omx_actions WHERE action_id=?",
                                    (action_id,)).fetchone()
        if action is None:
            raise KeyError(action_id)
        connection.execute(
            """INSERT INTO omx_action_events
               (action_id, attempt_id, state, event_type, actor_id, detail_json, created_at)
               VALUES (?, ?, ?, ?, 'system', ?, ?)""",
            (action_id, attempt_id, action["state"], event_type,
             json.dumps(dict(detail), sort_keys=True, separators=(",", ":")), created_at),
        )

    def _select(self, connection, action_id: str, attempt_id: str, barrier_id: str):
        return connection.execute(
            "SELECT * FROM omx_action_barriers WHERE action_id=? AND attempt_id=? AND barrier_id=?",
            (action_id, attempt_id, barrier_id)).fetchone()

    def arrive(self, grant: FleetCellTransferGrant, barrier: CellTransferBarrier) -> dict[str, Any]:
        """Record PHASE_WAIT once; later calls return the stored row unchanged."""
        stamp = _stamp(self.now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select(connection, grant.action_id, grant.attempt_id, barrier.barrier_id)
            if row is None:
                connection.execute(
                    """INSERT INTO omx_action_barriers
                       (action_id, attempt_id, barrier_id, gated_phase, coupling_after, max_wait_s,
                        state, authority_epoch, dispatch_generation, arrived_at, arrived_monotonic, boot_id)
                       VALUES (?, ?, ?, ?, ?, ?, 'waiting', ?, ?, ?, ?, ?)""",
                    (grant.action_id, grant.attempt_id, barrier.barrier_id, barrier.gated_phase,
                     barrier.coupling_after, barrier.max_wait_s, grant.authority_epoch,
                     grant.dispatch_generation, stamp, self.monotonic(), self.boot_id))
                self._event(connection, grant.action_id, grant.attempt_id, "PHASE_WAIT", {
                    "barrier_id": barrier.barrier_id, "gated_phase": barrier.gated_phase,
                    "arrived_at": stamp}, stamp)
                row = self._select(connection, grant.action_id, grant.attempt_id, barrier.barrier_id)
            connection.commit()
        return self._view(row)

    def waiting(self) -> list[dict[str, Any]]:
        """Every waiting row of this boot (the owner's stop sweep reads it)."""
        with closing(self._connect()) as connection:
            found = connection.execute(
                "SELECT * FROM omx_action_barriers WHERE state='waiting' AND boot_id=?",
                (self.boot_id,)).fetchall()
        return [self._view(row) for row in found]

    def rows(self, action_id: str, attempt_id: str) -> dict[str, dict[str, Any]]:
        with closing(self._connect()) as connection:
            found = connection.execute(
                "SELECT * FROM omx_action_barriers WHERE action_id=? AND attempt_id=?",
                (action_id, attempt_id)).fetchall()
        return {row["barrier_id"]: self._view(row) for row in found}

    def release(self, action_id: str, attempt_id: str, barrier_id: str, *,
                release: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        """Record one release; a repeated release returns the stored one (idempotent)."""
        stamp = _stamp(self.now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select(connection, action_id, attempt_id, barrier_id)
            if row is None:
                raise BarrierRefused("BARRIER_NOT_REACHED", "this arm has not arrived at the barrier")
            if row["state"] == BarrierState.RELEASED.value:
                connection.rollback()
                return self._view(row), False
            if row["state"] != BarrierState.WAITING.value:
                raise BarrierRefused("BARRIER_EXPIRED", "the barrier wait already expired")
            if row["boot_id"] != self.boot_id:
                raise BarrierRefused("BARRIER_STALE_BOOT", "the arrival was recorded before an owner restart")
            connection.execute(
                """UPDATE omx_action_barriers SET state='released', released_at=?,
                   released_monotonic=?, release_json=?
                   WHERE action_id=? AND attempt_id=? AND barrier_id=?""",
                (stamp, self.monotonic(), json.dumps(dict(release), sort_keys=True),
                 action_id, attempt_id, barrier_id))
            self._event(connection, action_id, attempt_id, "BARRIER_RELEASED",
                        {"barrier_id": barrier_id, "released_at": stamp, **dict(release)}, stamp)
            row = self._select(connection, action_id, attempt_id, barrier_id)
            connection.commit()
        return self._view(row), True

    def expire(self, action_id: str, attempt_id: str, barrier_id: str, *,
               fail_unmoved_reason: str | None = None) -> bool:
        """Expire one waiting barrier; with ``fail_unmoved_reason``, in the same transaction end an
        Action that never submitted a phase as FAILED. Returns whether the Action was failed here."""
        stamp = _stamp(self.now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select(connection, action_id, attempt_id, barrier_id)
            if row is None or row["state"] != BarrierState.WAITING.value:
                raise BarrierRefused("BARRIER_NOT_WAITING", "only a waiting barrier can expire")
            connection.execute(
                """UPDATE omx_action_barriers SET state='expired', expired_at=?
                   WHERE action_id=? AND attempt_id=? AND barrier_id=?""",
                (stamp, action_id, attempt_id, barrier_id))
            self._event(connection, action_id, attempt_id, "BARRIER_EXPIRED",
                        {"barrier_id": barrier_id, "expired_at": stamp}, stamp)
            failed = False
            if fail_unmoved_reason is not None:
                action = connection.execute(
                    "SELECT state FROM omx_actions WHERE action_id=? AND attempt_id=?",
                    (action_id, attempt_id)).fetchone()
                moved = connection.execute(
                    "SELECT COUNT(*) FROM omx_action_phases WHERE action_id=? AND attempt_id=?",
                    (action_id, attempt_id)).fetchone()[0]
                if action is not None and action["state"] == "SUBMITTING" and not moved:
                    # Nothing moved, so no HOLD (D-780 3): the Action ends FAILED.
                    connection.execute(
                        """UPDATE omx_actions SET state='FAILED', reason=?, result_source='owner-barrier',
                           result_observed_at=?, result_json=?, updated_at=?
                           WHERE action_id=? AND attempt_id=?""",
                        (fail_unmoved_reason, stamp, json.dumps({"reason": fail_unmoved_reason}), stamp,
                         action_id, attempt_id))
                    self._event(connection, action_id, attempt_id, "BARRIER_UNMOVED_FAILED",
                                {"reason": fail_unmoved_reason, "barrier_id": barrier_id}, stamp)
                    failed = True
            connection.commit()
        return failed


__all__ = ["BarrierJournal", "BarrierRefused"]
