"""D-721 Amendment: durable 사람 부탁 (person requests) in the shared Fleet SQLite DB.

``open`` -> ``done`` | ``cannot`` | ``expired`` | ``withdrawn``; a closed request never changes again. The record
is a person's statement and nothing else: no method here, and no caller of it, moves a robot, releases a stop or
passes a check.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Optional
from uuid import uuid4

from fleet.server.sqlite_policy import configure_connection, enable_wal

COLUMNS = ("id", "robot_id", "kind", "text", "why", "requested_by", "state", "answered_by", "answer_note",
           "created_at", "expires_at", "answered_at", "delivery")
LISTED_MAX = 200
ACTIVE_DELIVERY = frozenset({"not_sent", "waiting", "delivered", "not_delivered"})


class PersonRequestStore:
    def __init__(self, path=None, *, wall=time.time):
        self._wall, self._lock = wall, threading.Lock()
        self._db = configure_connection(sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False))
        if path:
            enable_wal(self._db)
        with self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS person_requests (id TEXT PRIMARY KEY, robot_id TEXT, kind TEXT NOT NULL, "
                "text TEXT NOT NULL, why TEXT NOT NULL, requested_by TEXT NOT NULL, state TEXT NOT NULL, "
                "answered_by TEXT, answer_note TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL, "
                "answered_at REAL, delivery TEXT NOT NULL)")

    def _row(self, row) -> dict:
        out = dict(zip(COLUMNS, row))
        out["delivery"] = json.loads(out["delivery"])
        at = out["delivery"].get("at")
        out["delivery"]["age_s"] = None if at is None else round(max(0.0, self._wall() - at), 1)
        return out

    def create(self, *, robot_id: Optional[str], kind: str, text: str, why: str, requested_by: str,
               ttl_s: float) -> dict:
        now = self._wall()
        delivery = {"state": "not_sent" if robot_id else "no_robot", "at": None, "error": None}
        record = (uuid4().hex, robot_id, kind, text, why, requested_by, "open", None, None, now, now + ttl_s, None,
                  json.dumps(delivery))
        with self._lock, self._db:
            self._db.execute(f"INSERT INTO person_requests VALUES ({','.join('?' * len(COLUMNS))})", record)
        return self._row(record)

    def expire_due(self) -> list[dict]:
        """Close every open request past its expiry; the records just closed (the robot may still hold them)."""
        now = self._wall()
        with self._lock, self._db:
            rows = self._db.execute("SELECT * FROM person_requests WHERE state='open' AND expires_at<=?",
                                    (now,)).fetchall()
            self._db.execute("UPDATE person_requests SET state='expired' WHERE state='open' AND expires_at<=?",
                             (now,))
        return [{**self._row(r), "state": "expired"} for r in rows]

    def get(self, request_id: str) -> Optional[dict]:
        self.expire_due()
        with self._lock:
            row = self._db.execute("SELECT * FROM person_requests WHERE id=?", (request_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, *, state: Optional[str] = None, robot_id: Optional[str] = None) -> list[dict]:
        self.expire_due()
        where, args = [], []
        for column, value in (("state", state), ("robot_id", robot_id)):
            if value is not None:
                where.append(f"{column}=?")
                args.append(value)
        sql = "SELECT * FROM person_requests" + (" WHERE " + " AND ".join(where) if where else "")
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*args, LISTED_MAX)).fetchall()
        return [self._row(r) for r in rows]

    def close(self, request_id: str, state: str, *, by: str, note: str = "") -> Optional[dict]:
        """Open -> ``state``; None when the request is not open (unknown, answered, withdrawn or expired)."""
        self.expire_due()
        with self._lock, self._db:
            changed = self._db.execute(
                "UPDATE person_requests SET state=?, answered_by=?, answer_note=?, answered_at=? "
                "WHERE id=? AND state='open'", (state, by, note, self._wall(), request_id)).rowcount
        return self.get(request_id) if changed else None

    def open_for(self, robot_id: Optional[str], requested_by: Optional[str] = None) -> list[dict]:
        """Open requests for one robot (or none), newest first; optionally only one requester's."""
        self.expire_due()
        sql, args = "SELECT * FROM person_requests WHERE state='open' AND robot_id IS ?", [robot_id]
        if requested_by is not None:
            sql, args = sql + " AND requested_by=?", [*args, requested_by]
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY created_at DESC", args).fetchall()
        return [self._row(r) for r in rows]

    def set_delivery(self, request_id: str, state: str, error: Optional[str] = None) -> bool:
        """Record what Fleet last learned about the robot's screen. A closed request is never marked as shown
        (``delivered``, ``waiting``, ``not_delivered``, ``not_sent`` need it open), and an open one is never marked
        cleared: the write that lost the race changes nothing."""
        guard = "state='open'" if state in ACTIVE_DELIVERY else "state<>'open'"
        with self._lock, self._db:
            changed = self._db.execute(
                f"UPDATE person_requests SET delivery=? WHERE id=? AND {guard}",
                (json.dumps({"state": state, "at": self._wall(), "error": error}), request_id)).rowcount
        return bool(changed)
