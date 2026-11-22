"""Site-wide named-stop custody stored in the Fleet site journal."""

import json
import sqlite3
from contextlib import closing

from fleet.server.named_stop_motion import NamedStopMotion
from fleet.server.sqlite_policy import configure_connection


class NamedStopStore:
    def __init__(self, path):
        self.path = path
        with closing(self._connect()) as connection, connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS named_stop_claim (
                slot INTEGER PRIMARY KEY CHECK (slot = 1), reservation_id TEXT NOT NULL,
                robot_id TEXT NOT NULL, boot_id TEXT NOT NULL, correlation_id TEXT NOT NULL,
                run_id TEXT, repark_correlation_id TEXT, repark_run_id TEXT,
                precision_required INTEGER NOT NULL DEFAULT 0 CHECK (precision_required IN (0, 1)))""")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""CREATE TABLE IF NOT EXISTS named_stop_repark_completion (
                robot_id TEXT NOT NULL, boot_id TEXT NOT NULL, nav_run_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL, completion TEXT NOT NULL,
                PRIMARY KEY (robot_id, boot_id, nav_run_id))""")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(named_stop_claim)")}
            if "repark_correlation_id" not in columns:
                connection.execute("ALTER TABLE named_stop_claim ADD COLUMN repark_correlation_id TEXT")
            if "repark_run_id" not in columns:
                connection.execute("ALTER TABLE named_stop_claim ADD COLUMN repark_run_id TEXT")
            if "precision_required" not in columns:
                connection.execute("ALTER TABLE named_stop_claim ADD COLUMN precision_required INTEGER NOT NULL DEFAULT 0")

    def _connect(self):
        connection = sqlite3.connect(self.path)
        try:
            configure_connection(connection)
            # The dispatch callback is synchronous. A locked writer means wait before sending.
            connection.execute("PRAGMA busy_timeout=0")
        except Exception:
            connection.close()
            raise
        return connection

    def current(self) -> NamedStopMotion | None:
        with closing(self._connect()) as connection:
            row = connection.execute("""SELECT robot_id, boot_id, correlation_id, run_id, reservation_id,
                repark_correlation_id, repark_run_id, precision_required FROM named_stop_claim WHERE slot=1""").fetchone()
        return None if row is None else NamedStopMotion(*row[:4], reservation_id=row[4],
                                                        repark_correlation_id=row[5], repark_run_id=row[6],
                                                        precision_required=bool(row[7]))

    def claim(self, motion: NamedStopMotion) -> bool:
        with closing(self._connect()) as connection, connection:
            changed = connection.execute("""INSERT INTO named_stop_claim
                (slot, reservation_id, robot_id, boot_id, correlation_id, precision_required) VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(slot) DO NOTHING""",
                (motion.reservation_id, motion.robot_id, motion.boot_id, motion.correlation_id,
                 int(motion.precision_required))).rowcount
        return changed == 1

    def bind_run(self, motion: NamedStopMotion) -> bool:
        with closing(self._connect()) as connection, connection:
            changed = connection.execute("""UPDATE named_stop_claim SET run_id=?
                WHERE slot=1 AND reservation_id=? AND (run_id IS NULL OR run_id=?)""",
                (motion.run_id, motion.reservation_id, motion.run_id)).rowcount
        return changed == 1

    def arm_repark(self, motion: NamedStopMotion, correlation_id: str) -> bool:
        with closing(self._connect()) as connection, connection:
            changed = connection.execute("""UPDATE named_stop_claim SET repark_correlation_id=?
                WHERE slot=1 AND reservation_id=? AND run_id=? AND repark_correlation_id IS NULL""",
                (correlation_id, motion.reservation_id, motion.run_id)).rowcount
        return changed == 1

    def bind_repark_run(self, motion: NamedStopMotion) -> bool:
        with closing(self._connect()) as connection, connection:
            changed = connection.execute("""UPDATE named_stop_claim SET repark_run_id=?
                WHERE slot=1 AND reservation_id=? AND repark_correlation_id=?
                AND (repark_run_id IS NULL OR repark_run_id=?)""",
                (motion.repark_run_id, motion.reservation_id, motion.repark_correlation_id, motion.repark_run_id)).rowcount
        return changed == 1

    def repark_completion(self, robot_id, operation) -> dict | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT completion FROM named_stop_repark_completion "
                "WHERE robot_id=? AND boot_id=? AND nav_run_id=? AND correlation_id=?",
                (robot_id, operation["boot_id"], operation["run_id"], operation["correlation_id"])).fetchone()
        return None if row is None else json.loads(row[0])

    def release(self, motion: NamedStopMotion) -> bool:
        with closing(self._connect()) as connection, connection:
            changed = connection.execute("""DELETE FROM named_stop_claim WHERE slot=1 AND reservation_id=?
                AND repark_correlation_id IS ? AND repark_run_id IS ?""",
                (motion.reservation_id, motion.repark_correlation_id, motion.repark_run_id)).rowcount
            if changed == 1 and motion.repark_completion is not None:
                connection.execute("INSERT INTO named_stop_repark_completion "
                    "(robot_id, boot_id, nav_run_id, correlation_id, completion) VALUES (?, ?, ?, ?, ?)",
                    (motion.robot_id, motion.boot_id, motion.run_id, motion.correlation_id,
                     json.dumps(motion.repark_completion, allow_nan=False)))
        return changed == 1
