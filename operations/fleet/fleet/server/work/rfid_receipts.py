"""Cell-local RFID evidence and root Fleet's durable intake reconciliation."""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from core_common.protocol.arm_transfer_preflight import ArmPhysicalRef
from core_common.protocol.port_events import Epc, IntakeCandidate, IntakeCandidatePage, PortEvent, event_id
from .port_event_store import PortEventConflict

Reference = Annotated[ArmPhysicalRef, Field(max_length=128)]


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_name: str = Field(alias="schema", pattern=r"^rosy\.intake-rfid-manifest\.v1$")
    workcell_id: Reference
    revision: Reference
    container_epcs: dict[Epc, Reference] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_labels(self):
        if len(self.container_epcs) != len(set(self.container_epcs.values())):
            raise ValueError("RFID manifest maps one label to multiple EPCs")
        return self


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate RFID manifest key")
        result[key] = value
    return result


class RfidReceipts:
    def __init__(self, store, *, manifest=None, encoded=None, workcell=None, window=300, epoch=None):
        if manifest and encoded or not 0 < window <= 3600:
            raise ValueError("ambiguous RFID mode or invalid evidence window")
        self.store, self.manifest, self.encoded = store, manifest, encoded
        self.workcell, self.window, self.epoch = workcell, window, epoch
        with closing(store._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS rfid_local (
                    seq INTEGER PRIMARY KEY, workcell TEXT, ref TEXT, digest TEXT, body TEXT,
                    UNIQUE(workcell, ref));
                CREATE TABLE IF NOT EXISTS rfid_labels (label TEXT, epc TEXT, PRIMARY KEY(label,epc));
                CREATE TABLE IF NOT EXISTS rfid_manifests (revision TEXT PRIMARY KEY, digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rfid_import (
                    peer TEXT, seq INTEGER, body TEXT, at REAL, coverage REAL, epoch TEXT, outcome TEXT, label TEXT,
                    PRIMARY KEY(peer,seq));
                CREATE INDEX IF NOT EXISTS rfid_events_at ON rfid_import(peer,at);
                CREATE INDEX IF NOT EXISTS rfid_outcomes ON rfid_import(peer,outcome,label,at);
                CREATE TABLE IF NOT EXISTS rfid_receipts (
                    occurrence TEXT PRIMARY KEY, cargo TEXT NOT NULL, peer TEXT, seq INTEGER,
                    supply_task TEXT NOT NULL, delivered_at REAL NOT NULL,
                    UNIQUE(peer,seq));
            """)
            if manifest:
                db.execute("BEGIN IMMEDIATE")
                digest = sha256(json.dumps(manifest.model_dump(), sort_keys=True).encode()).hexdigest()
                prior = db.execute("SELECT digest FROM rfid_manifests WHERE revision=?", (manifest.revision,)).fetchone()
                if prior and prior[0] != digest:
                    raise ValueError("RFID manifest revision changed contents")
                for epc, label in manifest.container_epcs.items():
                    if db.execute("SELECT 1 FROM rfid_labels WHERE (epc=? AND label!=?) OR (label=? AND epc!=?)",
                                  (epc, label, label, epc)).fetchone():
                        raise ValueError("RFID manifest contradicts the registered mapping")
                    db.execute("INSERT OR IGNORE INTO rfid_labels VALUES(?,?)", (label, epc))
                db.execute("INSERT OR IGNORE INTO rfid_manifests VALUES(?,?)", (manifest.revision, digest))
                db.commit()

    @classmethod
    def configured(cls, store):
        path = os.getenv("ROSY_INTAKE_RFID_MANIFEST")
        encoded = os.getenv("ROSY_INTAKE_RFID_ENCODED_WORKCELL")
        workcell = os.getenv("ROSY_INTAKE_RFID_WORKCELL")
        if not any((path, encoded, workcell)):
            return None
        ref = TypeAdapter(Reference)
        manifest = None
        if path:
            source = Path(path)
            if not source.is_absolute():
                raise ValueError("RFID manifest path must be absolute")
            data = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
            if any(key != key.upper() for key in data["container_epcs"]):
                raise ValueError("manifest EPC keys must be canonical uppercase")
            manifest = Manifest.model_validate(data)
        epoch = os.getenv("ROSY_INTAKE_RFID_READER_EPOCH")
        return cls(store, manifest=manifest, encoded=ref.validate_python(encoded) if encoded else None,
                   workcell=ref.validate_python(workcell) if workcell else None,
                   epoch=ref.validate_python(epoch) if epoch else None,
                   window=int(os.getenv("ROSY_INTAKE_RFID_WINDOW_SECONDS", "300")))

    @property
    def reader_workcell(self):
        return self.manifest.workcell_id if self.manifest else self.encoded

    def record(self, workcell, reading):
        if workcell != self.reader_workcell:
            raise PermissionError("RFID_WORKCELL_UNBOUND")
        digest = sha256(reading.model_dump_json().encode()).hexdigest()
        with closing(self.store._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT digest FROM rfid_local WHERE workcell=? AND ref=?",
                             (workcell, reading.observation_ref)).fetchone()
            if old:
                if old[0] != digest:
                    raise PortEventConflict("RFID_READING_CONFLICT")
                return
            if self.epoch is not None or reading.reader_epoch is not None:
                if reading.reader_epoch != self.epoch or not self.epoch:
                    raise PortEventConflict("RFID_READER_EPOCH_MISMATCH")
                previous = db.execute("""SELECT body FROM rfid_local WHERE workcell=?
                    AND json_extract(body,'$.reader_epoch')=? ORDER BY seq DESC LIMIT 1""",
                    (workcell, self.epoch)).fetchone()
                last = IntakeCandidate.model_validate_json(previous[0]) if previous else None
                if reading.reader_seq != (last.reader_seq+1 if last else 1):
                    raise PortEventConflict("RFID_READER_SEQUENCE_GAP")
                if last and (reading.observed_at < last.observed_at or
                             last.outcome == "CLOSED_THROUGH" and reading.observed_at == last.observed_at):
                    raise PortEventConflict("RFID_READER_CLOCK_REGRESSION")
            label = None
            outcome = "CLOSED_THROUGH" if reading.state == "closed_through" else "NO_READ"
            if reading.epc:
                if self.manifest:
                    label = self.manifest.container_epcs.get(reading.epc)
                else:
                    decoded = bytes.fromhex(reading.epc).rstrip(b"\0")
                    if re.fullmatch(rb"C-(?:[1-9]|1[0-9]|2[01])", decoded):
                        label = decoded.decode("ascii")
                outcome = "MAPPED" if label else "UNKNOWN_EPC"
                if label:
                    db.execute("INSERT OR IGNORE INTO rfid_labels VALUES (?,?)", (label, reading.epc))
                    if db.execute("SELECT COUNT(*) FROM rfid_labels WHERE label=?", (label,)).fetchone()[0] > 1:
                        outcome = "LABEL_CONFLICT"
            row = IntakeCandidate(workcell_id=workcell, observation_ref=reading.observation_ref,
                observed_at=reading.observed_at, object_ref=label, outcome=outcome,
                reader_epoch=reading.reader_epoch, reader_seq=reading.reader_seq, coverage_start=reading.coverage_start,
                mapping_revision=self.manifest.revision if self.manifest else "encoded-c1-c21-v1")
            db.execute("INSERT INTO rfid_local(workcell,ref,digest,body) VALUES(?,?,?,?)",
                       (workcell, reading.observation_ref, digest, row.model_dump_json()))

    def page(self, after, limit):
        with closing(self.store._connect()) as db:
            rows = db.execute("SELECT seq,body FROM rfid_local WHERE seq>? ORDER BY seq LIMIT ?", (after, limit))
            return {"rows": [{"seq": seq, "candidate": json.loads(body)} for seq, body in rows]}

    def cursor(self, peer):
        with closing(self.store._connect()) as db:
            return db.execute("SELECT COALESCE(MAX(seq),0) FROM rfid_import WHERE peer=?", (peer,)).fetchone()[0]

    def accept_page(self, peer, after, page):
        rows = IntakeCandidatePage.model_validate(page).rows
        with closing(self.store._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            for expected, row in enumerate(rows, after+1):
                if row.seq != expected or row.candidate.workcell_id != self.workcell:
                    raise ValueError("RFID_SOURCE_GAP_OR_SCOPE")
                body = row.candidate.model_dump_json()
                old = db.execute("SELECT body FROM rfid_import WHERE peer=? AND seq=?", (peer, row.seq)).fetchone()
                if old and old[0] != body:
                    raise PortEventConflict("RFID_PEER_HISTORY_CONFLICT")
                candidate = row.candidate
                db.execute("INSERT OR IGNORE INTO rfid_import VALUES(?,?,?,?,?,?,?,?)",
                    (peer, row.seq, body, candidate.observed_at.timestamp(),
                     candidate.coverage_start.timestamp() if candidate.coverage_start else None,
                     candidate.reader_epoch, candidate.outcome, candidate.object_ref))
        return len(rows)

    def received(self, occurrence, cargo):
        with closing(self.store._connect()) as db:
            return db.execute("SELECT 1 FROM rfid_receipts WHERE occurrence=? AND cargo=?",
                              (occurrence, cargo)).fetchone() is not None

    def tracked_source(self, occurrence, cargo, start, end, tasks):
        """Was this occurrence the only tracked cargo on the belt throughout this move?"""
        if not isinstance(start, (float, int)) or not isinstance(end, (float, int)) or not 0 < start <= end:
            return False
        with closing(self.store._connect()) as db:
            db.execute("BEGIN")
            receipt = db.execute("SELECT supply_task,delivered_at FROM rfid_receipts WHERE occurrence=? AND cargo=?",
                                 (occurrence, cargo)).fetchone()
            if receipt is None or receipt["delivered_at"] > start:
                return False
            delivered = receipt["delivered_at"]
            # A competing receipt cannot clear the belt until Fleet records its observed placement.
            competing = db.execute("""SELECT r.occurrence FROM rfid_receipts r
                WHERE r.occurrence!=? AND r.delivered_at<=? AND NOT EXISTS (
                  SELECT 1 FROM fleet_port_events e WHERE e.source='cell_ab'
                  AND json_extract(e.event_json,'$.kind')='container.stored'
                  AND json_extract(e.event_json,'$.intake_occurrence_id')=r.occurrence
                  AND json_extract(e.event_json,'$.object_ref')=r.cargo
                  AND julianday(json_extract(e.event_json,'$.observed_at'))<julianday(?,'unixepoch')) LIMIT 1""",
                (occurrence, end, delivered)).fetchone()
            stored = db.execute("""SELECT 1 FROM fleet_port_events WHERE source='cell_ab'
                AND json_extract(event_json,'$.kind')='container.stored'
                AND json_extract(event_json,'$.intake_occurrence_id')=? LIMIT 1""", (occurrence,)).fetchone()
            if competing or stored:
                return False
        supply_seen = False
        movement_count = 0
        for task in tasks:
            claimed = task.get("claimed_at")
            if task.get("task_id") == receipt["supply_task"]:
                supply_seen = (_physical_delivery(task) and task.get("intake_occurrence_id") == occurrence
                               and task["completed_at"] == delivered)
                continue
            if not claimed or claimed > end:
                continue
            if task.get("completed_at") and task["completed_at"] < delivered:
                continue
            if task.get("cell_id") == "cell_s":
                return False
            if task.get("cell_id") == "cell_ab" and "belt" in (task.get("src_site"), task.get("dst_site")):
                if (task.get("intake_occurrence_id") != occurrence or task.get("object_ref") != cargo
                        or claimed != start or task.get("completed_at") != end):
                    return False
                movement_count += 1
        return supply_seen and movement_count == 1

    def reconcile(self, peer, tasks):
        with closing(self.store._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            now = datetime.now(timezone.utc)
            consumed = {r[0] for r in db.execute("SELECT occurrence FROM rfid_receipts")}
            for task in tasks:
                occurrence = task.get("intake_occurrence_id")
                if not occurrence or occurrence in consumed or not _physical_delivery(task):
                    continue
                start, end = task["claimed_at"], task["completed_at"]
                expected = task.get("object_ref")
                if not expected and not self._sealed(db, peer, start, end, now):
                    continue
                observations = db.execute("""SELECT seq,body FROM rfid_import WHERE peer=?
                    AND at BETWEEN ? AND ? AND outcome!='CLOSED_THROUGH' ORDER BY seq""",
                    (peer, start, min(now.timestamp(), end + (self.window if expected else 0))))
                readings = [(seq, IntakeCandidate.model_validate_json(body)) for seq, body in observations]
                candidates = [(seq, r) for seq, r in readings if r.outcome == "MAPPED"
                              and (not expected or r.object_ref == expected)]
                if not candidates:
                    continue
                seq, row = candidates[0]
                if any(r.outcome == "MAPPED" and r.object_ref != row.object_ref for _, r in readings):
                    continue
                if not expected and any(r.reader_epoch != self.epoch or r.outcome != "MAPPED" for _, r in readings):
                    continue
                if db.execute("SELECT 1 FROM rfid_receipts WHERE peer=? AND seq=?", (peer, seq)).fetchone():
                    continue
                if db.execute("""SELECT 1 FROM rfid_import WHERE peer=? AND outcome='LABEL_CONFLICT'
                                 AND label=? LIMIT 1""", (peer, row.object_ref)).fetchone():
                    continue
                if any(self._overlaps(other, candidate) for _, candidate in candidates
                       for other in tasks if other is not task):
                    continue
                kind = "container.received_at_intake"
                event = PortEvent(event_id=event_id(row.workcell_id, row.observation_ref, kind), kind=kind,
                    intake_point=self.workcell, observation_ref=row.observation_ref, object_ref=row.object_ref,
                    observed_at=row.observed_at, identity="observed", intake_occurrence_id=occurrence)
                self.store._append(db, row.workcell_id, event)
                db.execute("INSERT INTO rfid_receipts VALUES(?,?,?,?,?,?)",
                           (occurrence, row.object_ref, peer, seq, task["task_id"], task["completed_at"]))
                consumed.add(occurrence)

    def _sealed(self, db, peer, start, end, now):
        return self.epoch and db.execute("""SELECT 1 FROM rfid_import WHERE peer=? AND outcome='CLOSED_THROUGH'
            AND epoch=? AND coverage<=? AND at BETWEEN ? AND ? LIMIT 1""",
            (peer, self.epoch, start, end, now.timestamp())).fetchone()

    def _overlaps(self, task, reading):
        expected = task.get("object_ref")
        if expected and expected != reading.object_ref:
            return False
        at, end = reading.observed_at.timestamp(), task.get("completed_at")
        return task["claimed_at"] <= at and (end is None or at <= end + (self.window if expected else 0))


def _physical_delivery(task):
    return (task.get("status") == "COMPLETED" and task.get("completed_at")
            and (task.get("receipt") or {}).get("physical_completion") is True
            and (task.get("receipt") or {}).get("simulated_success") is False
            and (task.get("receipt") or {}).get("phase") == "RELEASED"
            and (task.get("receipt") or {}).get("stage_id") == task["task_id"]
            and (task.get("receipt") or {}).get("handoff_lease_id") == task.get("handoff_lease_id")
            and bool(task.get("handoff_lease_id"))
            and (task.get("stage_result") or {}).get("task_verified") is True)


def is_inbound_supply(task):
    return (task.get("cell_id") == "cell_s" and task.get("arm_id") == "arm_s"
            and task.get("dst_site") == "belt" and task.get("src_site") in ("vehicle", "pinky")
            and not task.get("auto_recovered") and not task.get("displaced_to")
            and task.get("preset") != "export_s3_belt" and task.get("zone_id") != "EXP_S3_BELT")


def supply_intervals(tasks, workcell):
    intervals = []
    for task in tasks:
        if (task.get("intake_workcell") not in (None, workcell) or task.get("cell_id") != "cell_s"
                or task.get("arm_id") != "arm_s" or not task.get("claimed_at")):
            continue
        interval = dict(task)
        if not is_inbound_supply(task):
            # An overlapping recovery can make a scan ambiguous but can never receive cargo.
            interval.update(intake_occurrence_id=None, object_ref=None)
        intervals.append(interval)
    return intervals
