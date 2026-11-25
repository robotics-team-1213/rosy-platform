"""Durable claim before a USB recovery can move held cargo."""
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


class PlacementJournal:
    def __init__(self, directory, arm):
        self.path = Path(directory) / "recovery-placement.sqlite3"
        self.arm = arm

    @contextmanager
    def _open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA synchronous = FULL")
            db.execute("""CREATE TABLE IF NOT EXISTS placement (
                arm TEXT PRIMARY KEY, incident TEXT NOT NULL, target TEXT NOT NULL, verified INTEGER NOT NULL
            )""")
            yield db

    def pending(self):
        with self._open() as db:
            return db.execute("SELECT 1 FROM placement WHERE arm=? AND verified=0", (self.arm,)).fetchone() is not None

    def confirmed(self, incident_id):
        with self._open() as db:
            return db.execute("SELECT 1 FROM placement WHERE arm=? AND incident=? AND verified=1",
                              (self.arm, incident_id)).fetchone() is not None

    def begin(self, incident_id, target):
        if not all(isinstance(item, str) and item.strip() for item in (self.arm, incident_id, target)):
            return False
        with self._open() as db:
            return db.execute("""INSERT INTO placement VALUES (?, ?, ?, 0)
                ON CONFLICT(arm) DO UPDATE SET incident=excluded.incident, target=excluded.target, verified=0
                WHERE placement.verified=1 AND placement.incident<>excluded.incident""",
                (self.arm, incident_id, target)).rowcount == 1

    def verified(self, incident_id, target):
        with self._open() as db:
            return db.execute("UPDATE placement SET verified=1 WHERE arm=? AND incident=? AND target=? AND verified=0",
                              (self.arm, incident_id, target)).rowcount == 1
