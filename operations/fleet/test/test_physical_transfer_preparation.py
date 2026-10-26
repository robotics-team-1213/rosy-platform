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
    monkeypatch.setattr(module, "_MIGRATION_VERSION", 7)
    before = claims(path)
    with pytest.raises(RuntimeError, match="version 8"):
        CellJobStore(path)
    assert claims(path) == before


def test_site_stop_holds_the_prepared_attempt_and_preserves_all_occupancy(rig):
    path, tasks, control, store = rig
    job = admit(store, create(store), control)
    executor = execution(store)
    prepare(executor, job["mission_id"], store)
    tasks.trip_stop_latch(actor_id="operator")
    with connect(path) as connection:
        assert connection.execute("SELECT status FROM fleet_physical_transfer_attempts").fetchone()[0] == "HOLD"
    assert len(claims(path)) == len(store.installation.policy.resources)
    assert {c["phase"] for c in claims(path)} == {"HELD"}
    with pytest.raises(MissionConflict):
        prepare(executor, job["mission_id"], store)


def test_event_failure_rolls_back_attempt_and_preserves_ready_approval_and_claims(rig):
    path, _, control, store = rig
    job = admit(store, create(store), control)
    before = claims(path)
    with connect(path) as connection:
        connection.execute("CREATE TRIGGER fail_preparation BEFORE INSERT ON fleet_cell_events "
                           "WHEN NEW.event_type='PHYSICAL_TRANSFER_PREPARED' BEGIN SELECT RAISE(ABORT,'injected'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        prepare(execution(store), job["mission_id"], store)
    assert claims(path) == before
    assert store.get(job["mission_id"], principal=PROPOSER) == job
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_attempts").fetchone()[0] == 0


@pytest.mark.parametrize("delta", [-1, 15_000_000_001])
def test_preparation_replay_never_renews_ids_on_clock_regression_or_expiry(rig, delta):
    path, _, control, store = rig
    job = admit(store, create(store), control)
    executor = execution(store)
    first = prepare(executor, job["mission_id"], store)
    store._clock_ns = lambda: NOW + delta
    with pytest.raises(MissionConflict):
        prepare(executor, job["mission_id"], store, capabilities_observed_at_ns=NOW + delta)
    with connect(path) as connection:
        row = connection.execute("SELECT action_id,attempt_id,prepared_at_ns FROM fleet_physical_transfer_attempts").fetchone()
        assert (row["action_id"], row["attempt_id"], row["prepared_at_ns"]) == (
            first["grant"]["action_id"], first["grant"]["attempt_id"], NOW)


def test_preparation_ttl_must_support_the_installed_observation_window(rig):
    _, _, control, store = rig
    policy = store.installation.policy.model_copy(update={"min_separation_ns": 10_000_000_000,
                                                         "max_age_ns": 11_000_000_000})
    capabilities = tuple(c.model_copy(update={"resource_policy_digest": policy.digest})
                         for c in store.installation.capabilities)
    store.installation = store.installation.model_copy(update={"policy": policy, "capabilities": capabilities})
    with pytest.raises(ValueError, match="window"):
        execution(store)
    module = import_module("fleet.server.physical_transfer_execution")
    executor = module.PhysicalTransferExecution(store, grant_ttl_s=30)
    job = admit(store, create(store), control)
    row = prepare(executor, job["mission_id"], store)
    from datetime import datetime
    assert (datetime.fromisoformat(row["grant"]["expires_at"].replace("Z", "+00:00"))
            - datetime.fromisoformat(row["grant"]["issued_at"].replace("Z", "+00:00"))).total_seconds() == 30
