"""Join the stopped carry's local evidence to Fleet's accepted incident ID."""
import json
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path


@contextmanager
def _store(directory):
    path = Path(directory) / "recovery-cargo.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS cargo (
            arm TEXT NOT NULL, session TEXT NOT NULL, payload TEXT NOT NULL, incident TEXT,
            stopped_at REAL, PRIMARY KEY (arm,session), UNIQUE (arm,incident)
        )""")
        yield db


def remember_cargo(directory, arm, session_id, cargo):
    if not isinstance(cargo, dict) or not cargo:
        return
    try:
        with _store(directory) as db:
            db.execute("INSERT OR IGNORE INTO cargo(arm,session,payload) VALUES (?,?,?)",
                       (arm, str(session_id), json.dumps(cargo, allow_nan=False)))
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        print(f"cargo recovery context unavailable: {type(exc).__name__}")


def bind_incident(directory, arm, session_id, incident_id):
    if not incident_id or not (Path(directory) / "recovery-cargo.sqlite3").is_file():
        return
    with _store(directory) as db:
        db.execute("UPDATE cargo SET incident=?, stopped_at=? WHERE arm=? AND session=? AND incident IS NULL",
                   (str(incident_id), time.time(), arm, str(session_id)))


def load_context(directory, arm, incident_id):
    if not (Path(directory) / "recovery-cargo.sqlite3").is_file():
        return None
    with _store(directory) as db:
        row = db.execute("SELECT payload,stopped_at FROM cargo WHERE arm=? AND incident=?",
                         (arm, incident_id)).fetchone()
        return {"cargo": json.loads(row[0]), "stopped_at": row[1]} if row else None
