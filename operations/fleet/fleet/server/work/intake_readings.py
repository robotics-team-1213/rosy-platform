"""D-996 3-4: the cell Fleet turns a cell PC's tag readings into port events. The PC sends tag ids only; the tag ->
object_ref table and the declarations stay here, so the PC never holds an app's cargo code (D4).

conveyor end: a read tag whose object_ref a supply job delivered and nobody received yet -> received_at_intake
(observed); any other read tag, two tags or two faces -> handling_failed(MISMATCH); nothing read -> UNREADABLE.
wrist: a mismatch fails at once (the PC already held before the place); a read tag becomes container.stored when its
A/B job confirmed its goal on a slot anchor. Each reading is translated once: a resend returns the same rows.
"""
from contextlib import closing
import re

from core_common.protocol.port_events import IntakeReading, PortEvent, event_id
from .intake_transfer import _BINDINGS
from .port_event_store import PortEventConflict

_READINGS = """CREATE TABLE IF NOT EXISTS fleet_intake_readings (
    observation_ref TEXT PRIMARY KEY, workcell_id TEXT NOT NULL, reading_json TEXT NOT NULL)"""
SLOT = re.compile(r"^[A-Za-z0-9_]+-r\d+-c\d+-l\d+$")


def _event(source, reading, kind, **fields) -> PortEvent:
    return PortEvent(event_id=event_id(source, reading.observation_ref, kind), kind=kind,
                     observation_ref=reading.observation_ref, observed_at=reading.observed_at, **fields)


def _refs(port_store, kind) -> set:
    with closing(port_store._connect()) as connection:
        return {row[0] for row in connection.execute(
            "SELECT json_extract(event_json, '$.object_ref') FROM fleet_port_events "
            "WHERE json_extract(event_json, '$.kind')=?", (kind,))}


def pending(arm_store, port_store) -> set:
    """Declared object_refs whose supply job confirmed its goal and that no reading received yet."""
    with closing(arm_store._journal._connect()) as connection:
        connection.execute(_BINDINGS)
        delivered = {row[0] for row in connection.execute(
            "SELECT b.object_ref FROM fleet_intake_bindings b JOIN fleet_cell_jobs j ON j.mission_id=b.arm_mission_id "
            "WHERE j.status='GOAL_CONFIRMED'")}
    return delivered - _refs(port_store, "container.received_at_intake")


def conveyor_end_event(source, reading, tags, waiting, intake_point) -> PortEvent:
    if reading.state != "read":
        return _event(source, reading, "container.handling_failed",
                      reason="MISMATCH" if reading.state == "mismatch" else "UNREADABLE")
    ref = tags.get(str(reading.tag))
    if ref is None or ref not in waiting:  # an unknown tag, or a container nobody delivered here: never a guess
        return _event(source, reading, "container.handling_failed", reason="MISMATCH", object_ref=ref)
    return _event(source, reading, "container.received_at_intake", object_ref=ref, intake_point=intake_point,
                  identity="observed")


def record(arm_store, port_store, intake, source, reading: IntakeReading) -> list[int]:
    """Keep the reading once and translate it once; the seqs of its port events (none yet for a wrist read)."""
    body = reading.model_dump_json()
    with closing(arm_store._journal._connect()) as connection:
        connection.execute(_READINGS)
        connection.execute("INSERT OR IGNORE INTO fleet_intake_readings VALUES (?, ?, ?)",
                           (reading.observation_ref, source, body))
        connection.commit()
        prior = connection.execute("SELECT workcell_id, reading_json FROM fleet_intake_readings WHERE observation_ref=?",
                                   (reading.observation_ref,)).fetchone()
    if prior[0] != source or IntakeReading.model_validate_json(prior[1]) != reading:
        raise PortEventConflict("observation_ref was already used for another reading")
    done = port_store.by_observation(source, reading.observation_ref)
    if done:
        return done
    if reading.point == "wrist":
        if reading.state != "mismatch":
            return []
        event = _event(source, reading, "container.handling_failed", reason="MISMATCH")
    else:
        # shortcut: pending() and append() are two transactions; one cell PC posts one reading at a time
        event = conveyor_end_event(source, reading, intake.get("container_tags") or {},
                                   pending(arm_store, port_store), intake["intake_point"])
    return [port_store.append(source, event)]


def stored_due(arm_store, port_store, intake) -> list[int]:
    """container.stored for each wrist reading whose A/B job confirmed its goal on a slot anchor."""
    with closing(arm_store._journal._connect()) as connection:
        connection.execute(_READINGS)
        rows = connection.execute("SELECT workcell_id, reading_json FROM fleet_intake_readings").fetchall()
    received, stored, seqs = (_refs(port_store, "container.received_at_intake"),
                              _refs(port_store, "container.stored"), [])
    tags = intake.get("container_tags") or {}
    for source, raw in rows:
        reading = IntakeReading.model_validate_json(raw)
        ref = tags.get(str(reading.tag))
        if reading.point != "wrist" or reading.state != "read" or ref not in received or ref in stored:
            continue
        job = arm_store.peek(reading.arm_mission_id) if reading.arm_mission_id else None
        if job is None or job["status"] != "GOAL_CONFIRMED" or not SLOT.match(job["request"]["target"]):
            continue
        try:
            seqs.append(port_store.append(source, _event(source, reading, "container.stored", object_ref=ref,
                                                         slot_ref=job["request"]["target"], identity="observed")))
        except PortEventConflict:
            continue
        stored.add(ref)
    return seqs
