"""Single-reader capture and in-order delivery of RFID observations and interval closures."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
import sys
from threading import Event, Thread
import time
from uuid import uuid4

from port_event_outbox import IntakeReading, RFID_RESEND_SECONDS


def open_spool(path, epoch):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS stream (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), epoch TEXT NOT NULL,
            seq INTEGER NOT NULL, closed_at TEXT);
        CREATE TABLE IF NOT EXISTS pending (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS clock_quarantine (observed_at TEXT NOT NULL, epc TEXT);
    """)
    with db:
        db.execute("INSERT OR IGNORE INTO stream VALUES(1,?,0,NULL)", (epoch,))
    if db.execute("SELECT epoch FROM stream").fetchone() != (epoch,):
        db.close()
        raise ValueError("configured reader epoch differs from the durable spool")
    return db


class Capture:
    def __init__(self, db, *, utc=lambda: datetime.now(timezone.utc), monotonic=time.monotonic):
        self.db, self.utc, self.monotonic = db, utc, monotonic
        self.connected()

    def connected(self):
        self.start = self.last = self.utc()
        self.tick = self.monotonic()
        self.first_cycle = True

    def record(self, epc, *, triggered, max_interval):
        """Commit the trigger result and closure together, only after a confirmed inventory cycle."""
        now, tick = self.utc(), self.monotonic()
        elapsed = (now - self.last).total_seconds()
        discontinuity = elapsed < 0 or abs(elapsed - (tick - self.tick)) > 1
        stalled = tick - self.tick > max_interval
        self.last, self.tick = now, tick
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            epoch, seq, previous = self.db.execute("SELECT epoch, seq, closed_at FROM stream").fetchone()
            floor = datetime.fromisoformat(previous) if previous else None
            if discontinuity or stalled or (floor and now <= floor):
                if triggered:
                    self.db.execute("INSERT INTO clock_quarantine VALUES (?, ?)", (now.isoformat(), epc))
                self.start = None
                print("RFID capture time discontinuity; coverage interrupted", file=sys.stderr, flush=True)
                return
            if self.start is None or (self.first_cycle and floor and self.start <= floor):
                self.start = now
            self.first_cycle = False
            states = ["read" if epc else "unreadable"] if triggered else []
            for state in [*states, "closed_through"]:
                seq += 1
                item = IntakeReading(
                    observation_ref="obs-" + uuid4().hex, point="rfid_intake", state=state,
                    epc=epc if state == "read" else None, reader_epoch=epoch, reader_seq=seq,
                    coverage_start=self.start if state == "closed_through" else None, observed_at=now,
                )
                self.db.execute("INSERT INTO pending VALUES (?,?)", (seq, item.model_dump_json()))
            self.db.execute("UPDATE stream SET seq=?, closed_at=?", (seq, now.isoformat()))


def drain(db, link, stopped):
    """Stop on the first failed acknowledgement, including a lost response after Cell accepted it."""
    while not stopped.is_set():
        row = db.execute("SELECT seq,payload FROM pending ORDER BY seq LIMIT 1").fetchone()
        if row is None:
            return
        seq, body = row
        item = IntakeReading.model_validate_json(body)
        ack = link.post_intake_reading(item)
        if not isinstance(ack, dict) or ack.get("observation_ref") != item.observation_ref:
            raise ValueError("Cell response did not acknowledge the original observation")
        with db:
            db.execute("DELETE FROM pending WHERE seq=?", (seq,))


@contextmanager
def ordered_capture(arm):
    import fcntl
    from workcell_observation_bridge import ArmIncidentLink

    epoch = os.environ["ROSY_INTAKE_RFID_READER_EPOCH"].strip()
    link = ArmIncidentLink.from_environment(arm, os.environ)
    if not epoch or link is None:
        raise ValueError("ordered reader requires a provisioned epoch and Cell credential")
    directory = Path.home() / ".local/state/rosy/rfd40-intake"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "ordered.sqlite3"
    stopped = Event()

    def deliver():
        with closing(sqlite3.connect(path)) as worker_db:
            while not stopped.is_set():
                try:
                    drain(worker_db, link, stopped)
                except Exception as exc:
                    print(f"RFID FIFO awaiting Cell acknowledgement ({type(exc).__name__})",
                          file=sys.stderr, flush=True)
                stopped.wait(RFID_RESEND_SECONDS)

    with (directory / "reader.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with closing(open_spool(path, epoch)) as db:
            thread = Thread(target=deliver, name="rfid-fifo")
            thread.start()
            try:
                yield Capture(db)
            finally:
                stopped.set()
                thread.join()
