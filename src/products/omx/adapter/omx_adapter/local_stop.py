"""Persistent local software stop latch and serialized submit fence."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

from core_common.protocol.schemas import (
    LocalStopRequest,
    LocalStopSnapshot,
    LocalStopState,
    StopRequestSource,
)


T = TypeVar("T")


class LocalStopBlocked(PermissionError):
    """A latch or generation fence prevents a local driver submission."""


def _stamp(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("local stop timestamps must be timezone-aware")
    return now.astimezone(timezone.utc).isoformat(timespec="microseconds")


class LocalStopController:
    """Serialize stop and final submit within the single local workcell owner."""

    def __init__(self, path: Path | str, *, workcell_id: str, instance_id: str,
                 now: Callable[[], datetime] | None = None) -> None:
        self.path = Path(path)
        self.workcell_id = workcell_id
        self.instance_id = instance_id
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._forced_closed = True
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS omx_local_stop (
                    workcell_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    authority_epoch INTEGER NOT NULL,
                    dispatch_generation INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN
                        ('OPEN', 'REQUESTED', 'LOCAL_LATCHED', 'UNKNOWN')),
                    source TEXT NOT NULL CHECK(source IN ('fleet', 'operator_local')),
                    dispatch_enabled INTEGER NOT NULL CHECK(dispatch_enabled IN (0, 1)),
                    observed_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    PRIMARY KEY(workcell_id, instance_id)
                )
                """
            )
            connection.execute(
                """INSERT OR IGNORE INTO omx_local_stop
                   (workcell_id, instance_id, authority_epoch, dispatch_generation,
                    state, source, dispatch_enabled, observed_at, reason)
                   VALUES (?, ?, 0, 0, 'UNKNOWN', 'fleet', 0, ?, 'STARTUP_STOP_UNCONFIRMED')""",
                (self.workcell_id, self.instance_id, _stamp(self.now())),
            )
            connection.execute(
                """UPDATE omx_local_stop SET state='UNKNOWN', dispatch_enabled=0,
                   observed_at=?, reason='PROCESS_RESTARTED_REQUIRES_REARM'
                   WHERE workcell_id=? AND instance_id=? AND state='OPEN'""",
                (_stamp(self.now()), self.workcell_id, self.instance_id),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _snapshot(row: sqlite3.Row) -> LocalStopSnapshot:
        return LocalStopSnapshot(
            workcell_id=row["workcell_id"], instance_id=row["instance_id"],
            authority_epoch=row["authority_epoch"],
            dispatch_generation=row["dispatch_generation"], state=row["state"],
            source=row["source"], observed_at=row["observed_at"], reason=row["reason"],
        )

    def snapshot(self, *, workcell_id: str, instance_id: str) -> LocalStopSnapshot:
        if (workcell_id, instance_id) != (self.workcell_id, self.instance_id):
            raise KeyError("unknown workcell instance")
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM omx_local_stop WHERE workcell_id=? AND instance_id=?",
                (self.workcell_id, self.instance_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("local stop state is unavailable")
        return self._snapshot(row)

    def trip(self, request: LocalStopRequest, *, source: StopRequestSource,
             cancel_active: Callable[[], object] | None = None) -> LocalStopSnapshot:
        if (request.workcell_id, request.instance_id) != (self.workcell_id, self.instance_id):
            raise KeyError("unknown workcell instance")
        if not isinstance(source, StopRequestSource):
            raise ValueError("stop source must be derived from the authenticated local peer")
        observed_at = _stamp(self.now())
        try:
            with self._lock, closing(self._connect()) as connection:
                self._forced_closed = True
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM omx_local_stop WHERE workcell_id=? AND instance_id=?",
                    (self.workcell_id, self.instance_id),
                ).fetchone()
                if row is None:
                    raise RuntimeError("local stop state is unavailable")
                incoming = (request.authority_epoch, request.dispatch_generation)
                current = (row["authority_epoch"], row["dispatch_generation"])
                epoch, generation = max(current, incoming)
                connection.execute(
                    """UPDATE omx_local_stop SET authority_epoch=?, dispatch_generation=?,
                       state='REQUESTED', source=?, dispatch_enabled=0, observed_at=?, reason=?
                       WHERE workcell_id=? AND instance_id=?""",
                    (epoch, generation, source.value, observed_at, request.reason,
                     self.workcell_id, self.instance_id),
                )
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """UPDATE omx_local_stop SET state='LOCAL_LATCHED', observed_at=?
                       WHERE workcell_id=? AND instance_id=?""",
                    (_stamp(self.now()), self.workcell_id, self.instance_id),
                )
                latched = connection.execute(
                    "SELECT * FROM omx_local_stop WHERE workcell_id=? AND instance_id=?",
                    (self.workcell_id, self.instance_id),
                ).fetchone()
                connection.commit()
        except Exception:
            self._cancel_best_effort(cancel_active)
            raise
        self._cancel_best_effort(cancel_active)
        return self._snapshot(latched)

    @staticmethod
    def _cancel_best_effort(callback: Callable[[], object] | None) -> None:
        if callback is not None:
            try:
                callback()
            except Exception:
                # Latch persistence and cancel acceptance are independent facts.
                pass

    def rearm(self, *, authority_epoch: int, dispatch_generation: int,
              operator_confirmed: bool,
              fleet_fence_current: Callable[[int, int], bool]) -> LocalStopSnapshot:
        """Explicitly clear a local latch only on a newer, reconciled Fleet generation."""
        if (type(authority_epoch) is not int or authority_epoch < 0
                or type(dispatch_generation) is not int or dispatch_generation < 0):
            raise ValueError("rearm generation values must be non-negative integers")
        if operator_confirmed is not True:
            raise LocalStopBlocked("operator confirmation and zero unresolved actions required")
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            actions_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='omx_actions'"
            ).fetchone()
            if actions_table is None:
                raise LocalStopBlocked("local Action journal is unavailable")
            unresolved = connection.execute(
                """SELECT COUNT(*) FROM omx_actions WHERE workcell_id=? AND state IN
                   ('SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED', 'UNKNOWN', 'HOLD')""",
                (self.workcell_id,),
            ).fetchone()[0]
            if unresolved:
                raise LocalStopBlocked("unresolved local Actions must be reconciled before rearm")
            if not fleet_fence_current(authority_epoch, dispatch_generation):
                raise LocalStopBlocked("Fleet dispatch is not open at the rearm generation")
            row = connection.execute(
                "SELECT * FROM omx_local_stop WHERE workcell_id=? AND instance_id=?",
                (self.workcell_id, self.instance_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("local stop state is unavailable")
            if (authority_epoch, dispatch_generation) <= (
                    row["authority_epoch"], row["dispatch_generation"]):
                raise LocalStopBlocked("rearm must use a strictly newer authority/generation")
            connection.execute(
                """UPDATE omx_local_stop SET authority_epoch=?, dispatch_generation=?,
                   state='OPEN', source='fleet', dispatch_enabled=1, observed_at=?,
                   reason='OPERATOR_REARM' WHERE workcell_id=? AND instance_id=?""",
                (authority_epoch, dispatch_generation, _stamp(self.now()),
                 self.workcell_id, self.instance_id),
            )
            updated = connection.execute(
                "SELECT * FROM omx_local_stop WHERE workcell_id=? AND instance_id=?",
                (self.workcell_id, self.instance_id),
            ).fetchone()
            connection.commit()
            self._forced_closed = False
        return self._snapshot(updated)

    def run_if_open(self, *, authority_epoch: int, dispatch_generation: int,
                    fleet_fence_current: Callable[[], bool], operation: Callable[[], T]) -> T:
        """Hold the stop lock through the final freshness check and driver submit."""
        with self._lock:
            if self._forced_closed:
                raise LocalStopBlocked("local process has not completed stop rearm")
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM omx_local_stop WHERE workcell_id=? AND instance_id=?",
                    (self.workcell_id, self.instance_id),
                ).fetchone()
            if (row is None or row["state"] != LocalStopState.OPEN.value
                    or not row["dispatch_enabled"]
                    or (row["authority_epoch"], row["dispatch_generation"])
                    != (authority_epoch, dispatch_generation)):
                raise LocalStopBlocked("local stop latch or generation is closed")
            if not fleet_fence_current():
                self._forced_closed = True
                with closing(self._connect()) as connection:
                    connection.execute(
                        """UPDATE omx_local_stop SET state='UNKNOWN', dispatch_enabled=0,
                           observed_at=?, reason='FLEET_FENCE_STALE'
                           WHERE workcell_id=? AND instance_id=?""",
                        (_stamp(self.now()), self.workcell_id, self.instance_id),
                    )
                raise LocalStopBlocked("Fleet authority or generation is stale")
            return operation()
