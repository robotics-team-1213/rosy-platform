"""Durable physical attempt preparation confers no submission or release authority."""
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import json

import pytest

from core_common.protocol.arm_transfer import FleetArmTransferGrant
from fleet.server.cell_job_store import CellJobStore
from fleet.server.mission_store import MissionConflict
from fleet.server.step_action_kinds import dispatch_open, step_grant_digest
from test_physical_transfer_evidence import geometry, policy
from test_physical_transfer_store import (
    NOW, PROPOSER, installation, rig, create, admit, claims, connect,
)


def execution(store):
    try:
        module = import_module("fleet.server.physical_transfer_execution")
    except ModuleNotFoundError:
        pytest.fail("durable physical attempt preparation is missing")
    return module.PhysicalTransferExecution(store)


def prepare(executor, mission_id, store, **changes):
    args = dict(capabilities=store.installation.capabilities, capabilities_observed_at_ns=NOW - 1)
    return executor.prepare(mission_id, **{**args, **changes})


def test_prepare_is_durable_idempotent_and_keeps_ready_claims_without_legacy_dispatch(rig):
    path, _, control, store = rig
    ready = admit(store, create(store), control)
    executor = execution(store)
    original_claims = claims(path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        prepared = list(pool.map(lambda _: prepare(executor, ready["mission_id"], store), range(8)))
    assert all(value == prepared[0] for value in prepared)
    row = prepared[0]
    grant = FleetArmTransferGrant.model_validate(row["grant"])
    assert grant.request_digest == step_grant_digest(grant)
    assert grant.mission_id == ready["mission_id"]
    assert grant.arm_transfer.object_ref == store.installation.policy.object_ref
    assert grant.arm_transfer.resource_policy_digest == store.installation.policy.digest
    assert row["prepared_at_ns"] == NOW and row["status"] == "PREPARED"
    assert row["context"]["action_id"] == grant.action_id and row["context"]["attempt_id"] == grant.attempt_id
    assert row["context"]["phase"] == "PRE_DISPATCH" and row["context"]["not_before_ns"] == NOW
    assert len(row["context"]["owners"]) == len(store.installation.policy.participants)
    assert prepare(execution(store), ready["mission_id"], store) == row
    assert store.get(ready["mission_id"], principal=PROPOSER)["status"] == "READY"
    assert claims(path) == original_claims
    assert CellJobStore(path).get(ready["mission_id"]) is None
    assert not dispatch_open("simulation", "ARM_TRANSFER")
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_steps").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_attempts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_events WHERE event_type='PHYSICAL_TRANSFER_PREPARED'").fetchone()[0] == 1
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("failure", ["proposed", "capability", "fence", "claim", "installation", "clock"])
def test_invalid_preparation_or_replay_never_mints_an_attempt_or_changes_claims(rig, failure):
    path, tasks, control, store = rig
    job = create(store)
    if failure != "proposed":
        job = admit(store, job, control)
    args = {}
    if failure == "capability":
        args["capabilities"] = (store.installation.capabilities[0].model_copy(update={"owner_session_id": "changed"}),
                                *store.installation.capabilities[1:])
    elif failure == "fence":
        tasks.trip_stop_latch(actor_id="operator")
    elif failure == "claim":
        with connect(path) as connection:
            connection.execute("UPDATE fleet_action_claims SET phase='HELD'")
    elif failure == "installation":
        store.installation = store.installation.model_copy(update={"source": "changed"})
    elif failure == "clock":
        store._clock_ns = lambda: NOW - 1
    before = claims(path)
    with pytest.raises((MissionConflict, ValueError)):
        prepare(execution(store), job["mission_id"], store, **args)
    assert claims(path) == before
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_attempts").fetchone()[0] == 0


def test_prepared_replay_revalidates_current_fence_capability_and_immutable_grant(rig):
    path, _, control, store = rig
    job = admit(store, create(store), control)
    executor = execution(store)
    row = prepare(executor, job["mission_id"], store)
    changed = (store.installation.capabilities[0].model_copy(update={"owner_session_id": "changed"}),
               *store.installation.capabilities[1:])
    with pytest.raises(MissionConflict):
        prepare(executor, job["mission_id"], store, capabilities=changed)
    with connect(path) as connection:
        tampered = {**row["grant"], "owner_session_id": "tampered"}
        connection.execute("UPDATE fleet_physical_transfer_attempts SET grant_json=?", (json.dumps(tampered),))
    with pytest.raises((MissionConflict, ValueError)):
        prepare(executor, job["mission_id"], store)
    assert {c["phase"] for c in claims(path)} == {"CLAIMED"}


def test_old_host_rejects_prepared_journal_before_changing_any_table(rig, monkeypatch):
    path, _, control, store = rig
    job = admit(store, create(store), control)
    prepare(execution(store), job["mission_id"], store)
    module = import_module("fleet.server.cell_job_store")
    monkeypatch.setattr(module, "_MIGRATION_VERSION", 6)
    before = claims(path)
    with pytest.raises(RuntimeError, match="version 7"):
        CellJobStore(path)
    assert claims(path) == before
