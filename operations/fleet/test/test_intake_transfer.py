"""D-996 5: an arrived trip with an object_ref becomes one supply-arm ARM_TRANSFER proposal, never an admission."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from contextlib import closing

from fleet.server.intake_transfer import (INTAKE_PRINCIPAL, declared_object_ref, propose_arrived, release_vehicles,
                                          validate_intake)
from fleet.server.port_event_store import PortEventStore
from fleet.server.mission_store import MissionConflict
from test_physical_transfer_store import admit, installation, rig  # noqa: F401 - pytest fixtures
from test_physical_transfer_evidence import geometry, policy  # noqa: F401 - pytest fixtures


def _trips(tmp_path, rows):
    """The two columns of each table the intake reads, as a trip proposal store would hold them."""
    path = tmp_path / "trips.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE fleet_trip_proposals (mission_id TEXT, object_ref TEXT, body_json TEXT, "
                           "status TEXT)")
        connection.execute("CREATE TABLE fleet_cell_jobs (mission_id TEXT, status TEXT, updated_at TEXT, "
                           "instance_id TEXT DEFAULT 'rosy_01')")
        for index, (mission, ref, place, proposal, job) in enumerate(rows):
            body = {"candidates": ["rosy_01"], "steps": [{"to": "A", "via": []}, {"to": place, "via": []}]}
            connection.execute("INSERT INTO fleet_trip_proposals VALUES (?, ?, ?, ?)",
                               (mission, ref, json.dumps(body), proposal))
            connection.execute("INSERT INTO fleet_cell_jobs (mission_id, status, updated_at) VALUES (?, ?, ?)",
                               (mission, job, f"t{index}"))

    def connect():
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection
    return SimpleNamespace(store=SimpleNamespace(_connect=connect))


def test_only_admitted_arrived_trips_with_an_object_ref_at_the_supply_place_are_proposed(tmp_path, rig):
    _, _, control, store = rig
    trips = _trips(tmp_path, [("trip-1", "CNTR-1", "SUPPLY", "ADMITTED", "GOAL_CONFIRMED"),
                              ("trip-2", None, "SUPPLY", "ADMITTED", "GOAL_CONFIRMED"),
                              ("trip-3", "CNTR-3", "ELSEWHERE", "ADMITTED", "GOAL_CONFIRMED"),
                              ("trip-4", "CNTR-4", "SUPPLY", "ADMITTED", "RUNNING")])
    instance = store.installation.policy.primary[1]
    made = propose_arrived(trips, store, supply_place="SUPPLY", instance_id=instance)
    assert len(made) == 1
    job = store.get(made[0], principal=INTAKE_PRINCIPAL)
    assert job["status"] == "PROPOSED" and job["proposal_principal_id"] == "fleet-intake"
    assert job["request"]["object_ref"] == store.installation.policy.object_ref  # the owner's object profile
    assert declared_object_ref(store, made[0]) == "CNTR-1"  # the app's code rides beside the job
    # a rerun (or a restart) returns the same proposal, never a second one
    assert propose_arrived(trips, store, supply_place="SUPPLY", instance_id=instance) == made
    # the proposer is not a named operator: it cannot approve its own job
    with pytest.raises(PermissionError):
        admit(store, job, control, principal=INTAKE_PRINCIPAL)


def test_intake_names_an_installed_participant(rig):
    store = rig[3]
    validate_intake({"supply_place": "SUPPLY", "instance_id": store.installation.policy.primary[1]}, store)
    for bad in ({"supply_place": "SUPPLY", "instance_id": "nobody"}, {"supply_place": "SUPPLY"},
                {"supply_place": "", "instance_id": store.installation.policy.primary[1]}):
        with pytest.raises(ValueError):
            validate_intake(bad, store)
    with pytest.raises(ValueError):
        validate_intake({"supply_place": "SUPPLY", "instance_id": "x"}, None)


def test_a_second_trip_cannot_rebind_a_proposal_to_another_object_ref(tmp_path, rig):
    store = rig[3]
    instance = store.installation.policy.primary[1]
    propose_arrived(_trips(tmp_path, [("trip-1", "CNTR-1", "SUPPLY", "ADMITTED", "GOAL_CONFIRMED")]), store,
                    supply_place="SUPPLY", instance_id=instance)
    (tmp_path / "trips.sqlite3").unlink()
    changed = _trips(tmp_path, [("trip-1", "CNTR-9", "SUPPLY", "ADMITTED", "GOAL_CONFIRMED")])
    with pytest.raises((ValueError, MissionConflict)):
        propose_arrived(changed, store, supply_place="SUPPLY", instance_id=instance)


def test_a_supply_job_that_confirmed_its_goal_releases_the_trips_vehicle_once(tmp_path, rig):
    store = rig[3]
    trips = _trips(tmp_path, [("trip-1", "CNTR-1", "SUPPLY", "ADMITTED", "GOAL_CONFIRMED")])
    [mission] = propose_arrived(trips, store, supply_place="SUPPLY", instance_id=store.installation.policy.primary[1])
    ports = PortEventStore(tmp_path / "ports.sqlite3")
    assert release_vehicles(trips, store, ports) == []  # proposed, not done: the vehicle stays
    with closing(store._journal._connect()) as connection:
        connection.execute("UPDATE fleet_cell_jobs SET status='GOAL_CONFIRMED' WHERE mission_id=?", (mission,))
        connection.commit()
    first = release_vehicles(trips, store, ports)
    assert release_vehicles(trips, store, ports) == first  # every pass rebuilds the same event: one row
    [row] = ports.after(0, 10)
    assert row["event"].kind == "vehicle.release_permitted" and row["event"].vehicle_id == "rosy_01"
    assert row["event"].object_ref is None  # the vehicle event names no container
