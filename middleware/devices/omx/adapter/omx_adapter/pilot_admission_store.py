"""Internal durable Pilot dispatch fence; no replay or automatic restart recovery."""

from contextlib import closing
import sqlite3


class PilotAdmissionStore:
    def __init__(self, path, workcell_id, instance_id):
        self.path = path
        self.identity = (workcell_id, instance_id)
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS omx_pilot_admissions (
                workcell_id TEXT NOT NULL, instance_id TEXT NOT NULL,
                command_id TEXT NOT NULL, owner_session TEXT NOT NULL,
                ros_goal_id TEXT, terminal INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(workcell_id, instance_id, command_id))""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def has_pending(self):
        with closing(self._connect()) as db:
            return db.execute("SELECT 1 FROM omx_pilot_admissions WHERE workcell_id=? AND instance_id=? LIMIT 1",
                              self.identity).fetchone() is not None

    def reserve(self, command_id, session_id):
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO omx_pilot_admissions(workcell_id,instance_id,command_id,owner_session) VALUES(?,?,?,?)",
                       (*self.identity, command_id, session_id))

    def update(self, command_id, session_id, goal_id, terminal):
        with closing(self._connect()) as db, db:
            db.execute("UPDATE omx_pilot_admissions SET ros_goal_id=?,terminal=? WHERE workcell_id=? AND instance_id=? AND command_id=? AND owner_session=?",
                       (goal_id, int(terminal), *self.identity, command_id, session_id))

    def clear_completed(self, session_id):
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM omx_pilot_admissions WHERE workcell_id=? AND instance_id=? AND owner_session=? AND terminal=1",
                       (*self.identity, session_id))
