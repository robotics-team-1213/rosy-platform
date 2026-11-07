"""D-996 5: a trip that carried an object_ref and arrived at the supply place gets the supply arm's ARM_TRANSFER
proposal (Pinky -> conveyor). Only a proposal: admission, the D-977 handoff confirmation and the D-911 guards are
unchanged, and the cell's own loop no longer loads (cell_role keeps rescue only).

The ARM request's own object_ref stays the installed policy's object profile: the owner grant, receipts and evidence
are bound to it. The app's declared cargo code rides beside the job in ``fleet_intake_bindings``, written in the
proposal's own transaction, and only the port event producer reads it."""
import asyncio
from contextlib import closing
from datetime import datetime
import json

from core_common.protocol.port_events import PortEvent, event_id
from .mission_store import MissionConflict
from .port_event_store import PortEventConflict

from .site_auth import SitePrincipal

#: The proposer is Fleet itself: never a named operator, so it can never approve its own proposal.
INTAKE_PRINCIPAL = SitePrincipal(principal_id="fleet-intake", role="service")
_BINDINGS = """CREATE TABLE IF NOT EXISTS fleet_intake_bindings (
    arm_mission_id TEXT PRIMARY KEY, trip_mission_id TEXT NOT NULL UNIQUE, object_ref TEXT NOT NULL)"""


def _binder(trip_mission_id: str, object_ref: str):
    def bind(connection, arm_mission_id):
        connection.execute(_BINDINGS)
        connection.execute("INSERT OR IGNORE INTO fleet_intake_bindings VALUES (?, ?, ?)",
                           (arm_mission_id, trip_mission_id, object_ref))
        row = connection.execute("SELECT trip_mission_id, object_ref FROM fleet_intake_bindings WHERE arm_mission_id=?",
                                 (arm_mission_id,)).fetchone()
        if tuple(row) != (trip_mission_id, object_ref):
            raise ValueError("intake binding disagrees with its ARM_TRANSFER proposal")
    return bind


def declared_object_ref(arm_store, arm_mission_id: str) -> str | None:
    """The cargo code the trip declared for this supply-arm job, or None when it was not an intake proposal."""
    with closing(arm_store._journal._connect()) as connection:
        connection.execute(_BINDINGS)
        row = connection.execute("SELECT object_ref FROM fleet_intake_bindings WHERE arm_mission_id=?",
                                 (arm_mission_id,)).fetchone()
    return None if row is None else row[0]


def arrived(trip_store, supply_place: str) -> list[dict]:
    """Admitted trips with an object_ref whose job confirmed its last step at the supply place."""
    with closing(trip_store.store._connect()) as connection:
        rows = connection.execute(
            "SELECT p.mission_id, p.object_ref, p.body_json FROM fleet_trip_proposals p JOIN fleet_cell_jobs j "
            "ON j.mission_id=p.mission_id WHERE p.status='ADMITTED' AND p.object_ref IS NOT NULL "
            "AND j.status='GOAL_CONFIRMED' ORDER BY j.updated_at").fetchall()
    return [{"mission_id": row["mission_id"], "object_ref": row["object_ref"]} for row in rows
            if json.loads(row["body_json"])["steps"][-1]["to"] == supply_place]


def propose_arrived(trip_store, arm_store, *, supply_place: str, instance_id: str) -> list[str]:
    """One ARM_TRANSFER proposal per arrived trip; the request key is the trip's mission, so a rerun (or a restart)
    returns the same proposal instead of a second one. Returns the proposal mission ids."""
    installed = arm_store.installation
    participant = next(p for p in installed.policy.participants if p.instance_id == instance_id)
    made = []
    # shortcut: rescans every arrived trip each pass (create() is idempotent); keep a high-water mark if trips pile up
    for trip in arrived(trip_store, supply_place):
        request = {"workcell_id": participant.workcell_id, "instance_id": instance_id,
                   "object_ref": installed.policy.object_ref, "source": installed.source, "target": installed.target}
        try:
            job = arm_store.create(principal=INTAKE_PRINCIPAL, request_key="intake:" + trip["mission_id"],
                                   request=request, bind=_binder(trip["mission_id"], trip["object_ref"]))
        except (ValueError, MissionConflict):  # this trip's binding disagrees: it stays for a person, others go on
            continue
        made.append(job["mission_id"])
    return made


def release_vehicles(trip_store, arm_store, port_store) -> list[int]:
    """D-996 1: a supply-arm intake job that confirmed its goal releases the trip's vehicle. One event per job:
    the observation is the job, the time is the job's own, so every pass rebuilds the same event (idempotent)."""
    with closing(arm_store._journal._connect()) as connection:
        connection.execute(_BINDINGS)
        done = connection.execute(
            "SELECT b.arm_mission_id, b.trip_mission_id, j.workcell_id, j.updated_at FROM fleet_intake_bindings b "
            "JOIN fleet_cell_jobs j ON j.mission_id=b.arm_mission_id WHERE j.status='GOAL_CONFIRMED'").fetchall()
    seqs = []
    for row in done:
        with closing(trip_store.store._connect()) as connection:
            trip = connection.execute("SELECT instance_id FROM fleet_cell_jobs WHERE mission_id=?",
                                      (row["trip_mission_id"],)).fetchone()
        if trip is None:
            continue
        kind, ref = "vehicle.release_permitted", "s-done:" + row["arm_mission_id"]
        event = PortEvent(event_id=event_id(row["workcell_id"], ref, kind), kind=kind, observation_ref=ref,
                          vehicle_id=trip["instance_id"], observed_at=datetime.fromisoformat(row["updated_at"]))
        try:
            seqs.append(port_store.append(row["workcell_id"], event))
        except PortEventConflict:  # the job row changed after the event was recorded: the first event stands
            continue
    return seqs


def validate_intake(intake, arm_store) -> None:
    if not isinstance(intake, dict) or set(intake) != {"supply_place", "instance_id"} or not all(
            isinstance(value, str) and value for value in intake.values()):
        raise ValueError("intake needs exactly supply_place and instance_id")
    if arm_store is None or intake["instance_id"] not in {
            p.instance_id for p in arm_store.installation.policy.participants}:
        raise ValueError("intake instance_id is not an installed ARM transfer participant")


async def intake_loop(trip_store, arm_store, intake, log, period_s: float = 2.0, port_store=None):
    while True:
        try:
            await asyncio.to_thread(propose_arrived, trip_store, arm_store, **intake)
            if port_store is not None:
                await asyncio.to_thread(release_vehicles, trip_store, arm_store, port_store)
        except asyncio.CancelledError:
            raise
        except Exception:  # a bad row must not stop later trips; the next pass retries
            log.exception("intake ARM_TRANSFER proposal failed")
        await asyncio.sleep(period_s)
