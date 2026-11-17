"""D-996 2: this cell Fleet's port event ledger. Append-only, one monotonic seq per cell Fleet, idempotent on event_id.

Rows are never updated or deleted; a reader asks for the rows after a seq it last saw (the R relay keeps that seq inside
its opaque cursor). The same event_id with the same event is the same row; with a different event it is refused.
"""
from contextlib import closing
from datetime import datetime, timezone
import sqlite3

from core_common.protocol.port_events import PortEvent

_SCHEMA = """CREATE TABLE IF NOT EXISTS fleet_port_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, source TEXT NOT NULL,
    event_json TEXT NOT NULL, received_at TEXT NOT NULL)"""
_APPEND_ONLY = ("CREATE TRIGGER IF NOT EXISTS fleet_port_events_append_only BEFORE UPDATE ON fleet_port_events "
                "BEGIN SELECT RAISE(ABORT, 'port events are append-only'); END",
                "CREATE TRIGGER IF NOT EXISTS fleet_port_events_no_delete BEFORE DELETE ON fleet_port_events "
                "BEGIN SELECT RAISE(ABORT, 'port events are append-only'); END")


class PortEventConflict(ValueError):
    """The event_id is already in the ledger with a different event."""


class PortEventStore:
    def __init__(self, path) -> None:
        self.path = path
        with closing(self._connect()) as connection:
            connection.execute(_SCHEMA)
            for trigger in _APPEND_ONLY:
                connection.execute(trigger)
            connection.commit()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def append(self, source: str, event: PortEvent) -> int:
        """The seq of this event, appending it once. PermissionError when the event_id is not this source's."""
        if not event.matches(source):
            raise PermissionError("event_id is not sha256(source|observation_ref|kind) for this source")
        body = event.model_dump_json()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute("SELECT seq, event_json FROM fleet_port_events WHERE event_id=?",
                                       (event.event_id,)).fetchone()
            if prior is not None:
                connection.execute("ROLLBACK")
                if PortEvent.model_validate_json(prior["event_json"]) != event:
                    raise PortEventConflict("event_id was already recorded with a different event")
                return prior["seq"]
            seq = connection.execute(
                "INSERT INTO fleet_port_events (event_id, source, event_json, received_at) VALUES (?, ?, ?, ?)",
                (event.event_id, source, body, datetime.now(timezone.utc).isoformat())).lastrowid
            connection.execute("COMMIT")
            return seq

    def by_observation(self, source: str, observation_ref: str) -> list[int]:
        """Seqs already recorded for one observation of one source (a reading is translated once)."""
        with closing(self._connect()) as connection:
            return [row[0] for row in connection.execute(
                "SELECT seq FROM fleet_port_events WHERE source=? AND json_extract(event_json, '$.observation_ref')=? "
                "ORDER BY seq", (source, observation_ref))]

    def after(self, seq: int, limit: int) -> list[dict]:
        """[{"seq", "event"}] after ``seq``, oldest first. A seq the ledger never handed out stays a gap to the reader."""
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT seq, event_json FROM fleet_port_events WHERE seq>? ORDER BY seq LIMIT ?",
                                      (seq, limit)).fetchall()
        return [{"seq": row["seq"], "event": PortEvent.model_validate_json(row["event_json"])} for row in rows]
