"""Synthetic owner/World flow connects one recovery to existing submission and closure."""
import sqlite3

import pytest

from core_common.protocol.arm_transfer import FleetArmTransferGrant
from fleet.server.mission_store import MissionConflict
from fleet.server.local_action_transport import LocalActionUnavailable
from fleet.server.physical_transfer_observer import PhysicalObservationService
from fleet.server.physical_transfer_outcomes import export_transfer_outcomes, record_transfer_outcome
from test_physical_transfer_evidence import geometry, policy
from test_physical_transfer_store import NOW, PROPOSER, installation, rig, claims, connect
from test_physical_transfer_dispatcher import driver, ready, submit
from test_physical_transfer_recovery import arguments, measured


@pytest.fixture
def failed_driver(driver):
    before = ready(driver)
    original = driver.execution.snapshot(driver.job["mission_id"])
    submit(driver, before)
    driver.clock[0] = NOW + 400_000_000
    grant = FleetArmTransferGrant.model_validate(original["grant"])
    driver.execution.record_receipt(driver.job["mission_id"], driver.port.result(grant, "FAILED", 5))
    driver.clock[0] = NOW + 1_000_000_000
    case = (driver.path, driver.tasks, driver.store, driver.execution, driver.job, original)
    args = arguments(case)
    args.pop("capabilities")
    args.pop("capabilities_observed_at_ns")
    result = driver.port.result
    driver.port.result = lambda grant, state, event_id: result(grant, state,
        event_id if grant.mission_id == driver.job["mission_id"] else event_id + 10)
    return driver, args


def recover(failed_driver):
    d, args = failed_driver
    return d.dispatcher.recover(d.job["mission_id"], **args)


def test_recovery_prepares_a_new_attempt_then_uses_normal_send_and_physical_closure(failed_driver, tmp_path):
    d, _ = failed_driver
    result = recover(failed_driver)
    child, prepared = result["job"], result["execution"]
    assert child["status"] == "READY" and prepared["status"] == "PREPARED"
    assert prepared["grant"]["mission_id"] == child["mission_id"] != d.job["mission_id"]
    assert len(d.port.submitted) == 1
    assert PhysicalObservationService(d.dispatcher, None).context()["mission_id"] == child["mission_id"]
    d.clock[0] = NOW + 1_350_000_000
    source = measured(d.store, prepared, offset=1_000_000_000, sequence=5)
    d.dispatcher.submit(child["mission_id"], observations=source,
                        authenticated_producer_id=d.store.installation.policy.producer_id)
    assert len(d.port.submitted) == 2
    assert d.port.submitted[-1].action_id != d.port.submitted[0].action_id
    d.clock[0] = NOW + 1_400_000_000
    assert d.dispatcher.refresh(child["mission_id"])["status"] == "ACTION_SUCCEEDED"
    d.clock[0] = NOW + 1_750_000_000
    target = measured(d.store, prepared, offset=1_400_000_000, sequence=7, target=True)
    digest = prepared["grant"]["request_digest"]
    record_transfer_outcome(d.execution, child["mission_id"], digest, target,
                            authenticated_producer_id=d.store.installation.policy.producer_id)
    d.execution.confirm_physical(child["mission_id"], expected_request_digest=digest, observations=target,
        authenticated_producer_id=d.store.installation.policy.producer_id,
        capabilities=d.store.installation.capabilities, capabilities_observed_at_ns=d.clock[0] - 1)
    assert not claims(d.path)
    assert d.store.get(d.job["mission_id"], principal=PROPOSER)["status"] == "HOLD"
    assert PhysicalObservationService(d.dispatcher, None).context() is None
    parent_export = export_transfer_outcomes(d.store, d.job["mission_id"], tmp_path / "parent.json")
    child_export = export_transfer_outcomes(d.store, child["mission_id"], tmp_path / "child.json")
    for document in (parent_export, child_export):
        assert document["recovery_lineage"]["root_mission_id"] == d.job["mission_id"]
        assert document["recovery_lineage"]["child_mission_id"] == child["mission_id"]
        assert document["behavior_training_eligible"] is False
    assert parent_export["recovery_lineage"]["attempt_index"] == 0
    assert child_export["recovery_lineage"]["attempt_index"] == 1
    assert child_export["outcomes"][-1]["task_outcome"] == "succeeded"
    assert recover(failed_driver)["job"]["status"] == "GOAL_CONFIRMED"
    assert len(d.port.submitted) == 2


def test_preparation_failure_preserves_the_reserved_child_and_never_resets_the_budget(failed_driver):
    d, _ = failed_driver
    with connect(d.path) as connection:
        connection.execute("CREATE TRIGGER fail_child_prepare BEFORE INSERT ON fleet_physical_transfer_attempts "
                           "BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        recover(failed_driver)
    child_id = claims(d.path)[0]["owner_id"]
    result = recover(failed_driver)
    assert result["job"]["mission_id"] == child_id and result["job"]["status"] == "HOLD"
    assert result["execution"] is None and len(d.port.submitted) == 1
    with connect(d.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_jobs").fetchone()[0] == 2


def test_relabelled_parent_frames_cannot_authorize_the_child(failed_driver):
    d, _ = failed_driver
    result = recover(failed_driver)
    d.clock[0] = NOW + 1_350_000_000
    reused = measured(d.store, result["execution"], offset=1_000_000_000, sequence=3)
    before = claims(d.path)
    with pytest.raises(MissionConflict):
        d.dispatcher.submit(result["job"]["mission_id"], observations=reused,
                            authenticated_producer_id=d.store.installation.policy.producer_id)
    assert len(d.port.submitted) == 1 and claims(d.path) == before


def test_exact_dispatcher_replay_needs_no_owner_connection(failed_driver, monkeypatch):
    d, _ = failed_driver
    original = recover(failed_driver)
    def unavailable():
        raise LocalActionUnavailable("owner unavailable")
    monkeypatch.setattr(d.dispatcher, "_capabilities", unavailable)
    assert recover(failed_driver) == original
    assert len(d.port.submitted) == 1


def test_dispatcher_replay_after_ttl_change_returns_the_retained_child_grant(failed_driver):
    from fleet.server.physical_transfer_execution import PhysicalTransferExecution
    from fleet.server.physical_transfer_dispatcher import PhysicalTransferDispatcher
    d, _ = failed_driver
    original = recover(failed_driver)
    d.dispatcher = PhysicalTransferDispatcher(PhysicalTransferExecution(d.store, grant_ttl_s=30.),
        d.port, d.tasks, deployment_profile="simulation")
    assert recover(failed_driver) == original
    assert len(d.port.submitted) == 1
