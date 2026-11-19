"""D-996 end to end in one Fleet (simulation profile): a trip with an object_ref arrives, the supply job is proposed
and approved by a named operator, the vehicle is released, the conveyor end and the A/B wrist report tag ids, and the
app reads every port event in order behind one cursor. Statuses a real arm would reach are set directly."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import sqlite3

import pytest

from core_common.protocol.port_events import IntakeReading
from fleet.server.intake_readings import record, stored_due
from fleet.server.intake_transfer import INTAKE_PRINCIPAL, propose_arrived, release_vehicles
from fleet.server.port_event_routes import read_page
from fleet.server.port_event_store import PortEventConflict, PortEventStore
from test_cell_job_store import _stores
from test_intake_transfer import _trips
from test_physical_transfer_evidence import geometry, policy  # noqa: F401 - pytest fixtures
from test_physical_transfer_store import NOW, PROPOSER, admit, api, installation  # noqa: F401

T = datetime(2026, 11, 8, 3, 0, tzinfo=timezone.utc)
CELL = "supply"


@pytest.fixture
def cell(tmp_path, installation):
    path, _, _, control = _stores(tmp_path)
    slotted = api().TransferInstallation(policy=installation.policy, source="conveyor-end", target="yard-r1-c2-l1",
                                         capabilities=installation.capabilities)
    store = api().PhysicalTransferStore(path, installation=slotted, deployment_profile="simulation",
                                        clock_ns=lambda: NOW)
    intake = {"supply_place": "SUPPLY", "instance_id": slotted.policy.primary[1], "intake_point": "intake-A",
              "container_tags": {"100": "CNTR-1", "101": "CNTR-2"}}
    return path, control, store, PortEventStore(path), intake


def confirm(path, mission_id):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE fleet_cell_jobs SET status='GOAL_CONFIRMED' WHERE mission_id=?", (mission_id,))
        connection.commit()


def read(point, ref, state="read", tag=100, mission=None):
    return IntakeReading(observation_ref=ref, point=point, state=state, tag=tag if state == "read" else None,
                         arm_mission_id=mission, observed_at=T)


def test_trip_to_stored_reads_back_in_order_behind_one_cursor(tmp_path, cell):
    path, control, store, ports, intake = cell
    trips = _trips(tmp_path, [("trip-1", "CNTR-1", "SUPPLY", "ADMITTED", "GOAL_CONFIRMED")])
    [supply] = propose_arrived(trips, store, supply_place="SUPPLY", instance_id=intake["instance_id"])
    assert record(store, ports, intake, CELL, read("conveyor_end", "early")) != []  # before delivery: not a match
    assert ports.after(0, 9)[0]["event"].reason == "MISMATCH"
    first = asyncio.run(read_page(ports, None, None, 50))
    admit(store, store.get(supply, principal=INTAKE_PRINCIPAL), control)  # a named operator approves
    confirm(path, supply)  # the S carry put the container on the belt
    assert release_vehicles(trips, store, ports)
    record(store, ports, intake, CELL, read("conveyor_end", "end-1"))
    placing = store.create(principal=PROPOSER, request_key="place-1", request=dict(
        workcell_id=store.installation.policy.primary[0], instance_id=store.installation.policy.primary[1],
        object_ref=store.installation.policy.object_ref, source="conveyor-end", target="yard-r1-c2-l1"))
    assert record(store, ports, intake, CELL, read("wrist", "wrist-1", mission=placing["mission_id"])) == []
    assert stored_due(store, ports, intake) == []  # the A/B job has not confirmed its goal yet
    confirm(path, placing["mission_id"])
    assert len(stored_due(store, ports, intake)) == 1 and stored_due(store, ports, intake) == []
    page = asyncio.run(read_page(ports, None, first["cursor"], 50))
    assert [e["kind"] for e in page["events"]] == ["vehicle.release_permitted", "container.received_at_intake",
                                                   "container.stored"]
    assert page["events"][1]["object_ref"] == page["events"][2]["object_ref"] == "CNTR-1"
    assert page["events"][2]["slot_ref"] == "yard-r1-c2-l1" and page["events"][2]["identity"] == "observed"
    assert page["complete"] is True
    assert asyncio.run(read_page(ports, None, page["cursor"], 50))["events"] == []


def test_the_conveyor_end_never_guesses_and_translates_each_reading_once(tmp_path, cell):
    path, control, store, ports, intake = cell
    trips = _trips(tmp_path, [("trip-1", "CNTR-1", "SUPPLY", "ADMITTED", "GOAL_CONFIRMED")])
    [supply] = propose_arrived(trips, store, supply_place="SUPPLY", instance_id=intake["instance_id"])
    confirm(path, supply)
    cases = [(read("conveyor_end", "a", state="unreadable"), ("container.handling_failed", "UNREADABLE", None)),
             (read("conveyor_end", "b", state="mismatch"), ("container.handling_failed", "MISMATCH", None)),
             (read("conveyor_end", "c", tag=150), ("container.handling_failed", "MISMATCH", None)),  # not in the table
             (read("conveyor_end", "d", tag=101), ("container.handling_failed", "MISMATCH", "CNTR-2")),  # undelivered
             (read("wrist", "e", state="mismatch"), ("container.handling_failed", "MISMATCH", None)),
             (read("conveyor_end", "f"), ("container.received_at_intake", None, "CNTR-1"))]
    for reading, (kind, reason, ref) in cases:
        [seq] = record(store, ports, intake, CELL, reading)
        event = ports.after(seq - 1, 1)[0]["event"]
        assert (event.kind, event.reason, event.object_ref) == (kind, reason, ref)
        assert record(store, ports, intake, CELL, reading) == [seq]  # a resend is the same row
    with pytest.raises(PortEventConflict):
        record(store, ports, intake, CELL, read("conveyor_end", "f", tag=101))
    [again] = record(store, ports, intake, CELL, read("conveyor_end", "g"))  # already received: not twice
    assert ports.after(again - 1, 1)[0]["event"].reason == "MISMATCH"
