"""D-610 9·10: problem episodes, the human-required class table and the trend that proposes classes.

``fleet_problem_episodes`` (``--tasks-db``, 30 days): one row per answered problem with its type key, context,
cited evidence (frame ids, ages, sha256; never pictures), proposal, Fleet verdict and ``floor_would_hold`` notes,
the decision sent, CORE's reply and the closed-loop outcome. ``fleet_human_classes`` holds one row per change
(add / reject / remove, who, why, the statistics shown); it starts empty and only an operator changes it.
The trend never writes the table: it lists candidates. Times are epoch seconds (``time.time()``).
Without ``--tasks-db`` everything is kept in an in-memory SQLite database.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

from fleet.server.sqlite_policy import configure_connection

KEEP_S = 30 * 86400.0
TREND_S = 7 * 86400.0
#: D-610 9: n >= 5 and (unresolved >= 0.5 or near miss >= 0.2 or human >= 0.5); one near miss is enough alone.
MIN_N, UNRESOLVED, NEAR_MISS, HUMAN = 5, 0.5, 0.2, 0.5


class ProblemLog:
    def __init__(self, path: Optional[Path | str] = None, *, wall: Callable[[], float] = time.time) -> None:
        self.wall = wall
        self._lock = threading.Lock()   # one connection, used from the event loop's worker threads
        self._db = configure_connection(sqlite3.connect(":memory:" if path is None else path, timeout=5.0,
                                                        check_same_thread=False))
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS fleet_problem_episodes (
                       episode_row INTEGER PRIMARY KEY AUTOINCREMENT, opened_at REAL NOT NULL,
                       robot_id TEXT NOT NULL, problem_id TEXT NOT NULL, kind TEXT NOT NULL, type_key TEXT NOT NULL,
                       context TEXT NOT NULL, proposal TEXT, verdict TEXT, floor TEXT, decision TEXT, tier TEXT,
                       core_code TEXT, outcome TEXT, outcome_at REAL, near_miss INTEGER NOT NULL DEFAULT 0,
                       human INTEGER NOT NULL DEFAULT 0)""")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS fleet_human_classes (
                       change_row INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, type_key TEXT NOT NULL,
                       action TEXT NOT NULL, principal_id TEXT NOT NULL, reason TEXT NOT NULL, stats TEXT)""")
        self._active = self._replay()

    @contextmanager
    def _connect(self):
        with self._lock, self._db:
            yield self._db

    # ---- episodes -------------------------------------------------------------------------

    def opened(self, *, robot_id: str, problem_id: str, kind: str, type_key: str, context: dict,
               decision: Optional[str], tier: Optional[str], proposal: Optional[dict] = None,
               verdict: Optional[str] = None, floor=(), core_code: Optional[str] = None) -> None:
        now = self.wall()
        with self._connect() as connection:
            connection.execute("DELETE FROM fleet_problem_episodes WHERE opened_at < ?", (now - KEEP_S,))
            connection.execute(
                """INSERT INTO fleet_problem_episodes (opened_at, robot_id, problem_id, kind, type_key, context,
                   proposal, verdict, floor, decision, tier, core_code) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, robot_id, problem_id, kind, type_key, json.dumps(context, default=str),
                 None if proposal is None else json.dumps(proposal, default=str), verdict,
                 json.dumps(list(floor)), decision, tier, core_code))

    def outcome(self, row: dict) -> None:
        """The newest open episode of that robot/problem/decision gets the closed-loop outcome."""
        with self._connect() as connection:
            connection.execute(
                """UPDATE fleet_problem_episodes SET outcome = ?, outcome_at = ?, near_miss = ?
                   WHERE episode_row = (SELECT MAX(episode_row) FROM fleet_problem_episodes WHERE robot_id = ?
                   AND problem_id = ? AND outcome IS NULL)""",
                (row["outcome"], self.wall(), int(row.get("near_miss", False)), row["robot_id"], row["problem_id"]))

    def human(self, robot_id: str, problem_id: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE fleet_problem_episodes SET human = 1 WHERE robot_id = ? AND problem_id = ?",
                               (robot_id, problem_id))

    def episodes(self, limit: int = 500, robot_id: Optional[str] = None, since: float = 0.0) -> list[dict]:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT * FROM fleet_problem_episodes WHERE opened_at >= ? AND (? IS NULL OR robot_id = ?)
                   ORDER BY episode_row DESC LIMIT ?""", (since, robot_id, robot_id, limit)).fetchall()
            connection.row_factory = None
        out = []
        for row in rows:
            item = dict(row)
            for key in ("context", "proposal", "floor"):
                item[key] = None if item[key] is None else json.loads(item[key])
            out.append(item)
        return out

    # ---- human-required classes ------------------------------------------------------------

    def classes(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT at, type_key, action, principal_id, reason, stats FROM fleet_human_classes ORDER BY change_row"
            ).fetchall()
        return [{"at": r[0], "type_key": r[1], "action": r[2], "principal_id": r[3], "reason": r[4],
                 "stats": None if r[5] is None else json.loads(r[5])} for r in rows]

    def active(self) -> frozenset:
        """The active keys, cached: the resolver reads this on the event loop."""
        return self._active

    def _replay(self) -> frozenset:
        keys: set = set()
        for change in self.classes():
            if change["action"] == "add":
                keys.add(change["type_key"])
            elif change["action"] == "remove":
                keys.discard(change["type_key"])
        return frozenset(keys)

    def change(self, type_key: str, action: str, principal_id: str, reason: str, stats: Optional[dict]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO fleet_human_classes (at, type_key, action, principal_id, reason, stats) VALUES (?,?,?,?,?,?)",
                (self.wall(), type_key, action, principal_id, reason, None if stats is None else json.dumps(stats)))
        self._active = self._replay()

    def trend(self) -> list[dict]:
        """Per type key over 7 days; candidates past the D-610 9 thresholds, not active and not rejected since."""
        now = self.wall()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT type_key, COUNT(*), SUM(outcome = 'unresolved'), SUM(outcome = 'refused'), SUM(human),
                   SUM(near_miss), MAX(opened_at) FROM fleet_problem_episodes WHERE opened_at >= ?
                   GROUP BY type_key""", (now - TREND_S,)).fetchall()
        active = self.active()
        rejected = {c["type_key"]: c["at"] for c in self.classes() if c["action"] == "reject"}
        out = []
        for key, n, unresolved, refused, human, near, newest in rows:
            stats = {"n": n, "unresolved": round((unresolved or 0) / n, 3), "refused": round((refused or 0) / n, 3),
                     "human": round((human or 0) / n, 3), "near_miss": round((near or 0) / n, 3),
                     "near_miss_count": near or 0}
            candidate = bool(near) or n >= MIN_N and (stats["unresolved"] >= UNRESOLVED
                                                    or stats["near_miss"] >= NEAR_MISS or stats["human"] >= HUMAN)
            candidate = candidate and key not in active and rejected.get(key, -1.0) < newest
            out.append({"type_key": key, **stats, "candidate": candidate, "active": key in active})
        return sorted(out, key=lambda item: (not item["candidate"], item["type_key"]))
