"""Bounded Fleet observation history, alongside the existing CORE event journal."""

import hashlib
import json
import math
from itertools import islice
from threading import Lock
from uuid import uuid4
from contextlib import closing

from .events import CoreEventStore, EventRejected, MAX_EVENT_BYTES, _contains_sensitive_field


class ObservationStore(CoreEventStore):
    def __init__(self, path, *, max_rows=100_000, retention_s=30 * 86400):
        self._run_id, self._sequence, self._capture_lock = uuid4().hex, 0, Lock()
        super().__init__(path)
        self.max_rows, self.retention_s = max_rows, retention_s
        with closing(self._connect()) as connection, connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS fleet_observations (
                    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    robot_id TEXT NOT NULL, received_at REAL NOT NULL,
                    payload_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS fleet_observations_robot
                    ON fleet_observations(robot_id, observation_id);
                CREATE INDEX IF NOT EXISTS fleet_observations_time ON fleet_observations(received_at);
            """)

    def append_snapshot(self, rows, *, received_at, monotonic_now):
        with self._capture_lock:
            self._sequence += 1
            self._append_snapshot(rows, received_at=received_at, monotonic_now=monotonic_now)

    def _append_snapshot(self, rows, *, received_at, monotonic_now):
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in (received_at, monotonic_now)):
            raise EventRejected("observation clocks must be finite")
        rows = list(islice(rows, 1025))
        if len(rows) > 1024: raise EventRejected('observation roster exceeds the capture limit')
        identifiers = []
        for row in rows:
            if type(row) is not dict or type(row.get('robot_id')) is not str or not row['robot_id']:
                raise EventRejected('observation capture requires robot identities')
            identifiers.append(row['robot_id'])
        if len(set(identifiers)) != len(identifiers): raise EventRejected('duplicate capture robot identity')
        capture = dict(run_id=self._run_id, sequence=self._sequence,
                       monotonic_at=monotonic_now, robot_ids=sorted(identifiers))
        values = []
        for row in rows:
            rid = row.get("robot_id")
            if not isinstance(rid, str) or not rid or type(row.get("online")) is not bool:
                raise EventRejected("observation identity and online flag are required")
            stamp = row.get("_state_mono")
            age = (monotonic_now - stamp if isinstance(stamp, (int, float))
                   and not isinstance(stamp, bool) and math.isfinite(stamp) and stamp <= monotonic_now else None)
            body = {key: row.get(key) for key in ("robot_id", "online", "state", "gather_source",
                                                 "goal", "queued", "capabilities", "link", "link_reason")}
            body.update(received_at=received_at, observed_at=None if age is None else received_at - age,
                        state_age_s=age, clock="fleet_receive_epoch", source_monotonic=stamp,
                        verification="observed_not_labeled")
            body['capture'] = capture
            if _contains_sensitive_field(body):
                raise EventRejected("observation contains a forbidden credential field")
            try:
                payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise EventRejected("observation is not finite JSON") from exc
            if len(payload.encode("utf-8")) > MAX_EVENT_BYTES:
                raise EventRejected("observation exceeds the 64 KiB limit; media belongs in device recordings")
            values.append((rid, received_at, payload))
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                "INSERT INTO fleet_observations(robot_id, received_at, payload_json) VALUES (?, ?, ?)", values)
            connection.execute("DELETE FROM fleet_observations WHERE received_at < ?",
                               (received_at - self.retention_s,))
            # AUTOINCREMENT ids never repeat, so MAX(id) bounds the cap without walking 100k payload rows.
            connection.execute("""DELETE FROM fleet_observations WHERE observation_id <=
                (SELECT COALESCE(MAX(observation_id), 0) FROM fleet_observations) - ?""", (self.max_rows,))

    def read_observations(self, *, after_id=0, limit=100, robot_id=None):
        if after_id < 0 or not 1 <= limit <= 200:
            raise ValueError("cursor must be nonnegative and limit must be 1..200")
        where, params = "observation_id > ?", [after_id]
        if robot_id is not None:
            where += " AND robot_id = ?"
            params.append(robot_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM fleet_observations WHERE {where} ORDER BY observation_id LIMIT ?",
                (*params, limit + 1)).fetchall()
        return [dict(observation_id=row["observation_id"], robot_id=row["robot_id"],
                     received_at=row["received_at"], observation=json.loads(row["payload_json"]),
                     sha256=hashlib.sha256(row["payload_json"].encode("utf-8")).hexdigest()) for row in rows]
