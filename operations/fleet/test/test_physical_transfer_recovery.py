"""A fresh, independently approved recovery preserves the original effect journal."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from importlib import import_module
import sqlite3

import pytest

from fleet.server.mission_store import MissionConflict
from fleet.server.site_auth import SitePrincipal
from test_physical_transfer_evidence import geometry, policy
from test_physical_transfer_store import NOW, PROPOSER, OPERATOR, installation, rig, claims, connect
from test_physical_transfer_preparation import execution
from test_physical_transfer_submission import prepared, observations
from test_physical_transfer_outcomes import submitted, observe, receipt
from test_transfer_execution_review import phase_receipt


def api():
    return import_module("fleet.server.physical_transfer_recovery")


def measured(store, state, *, offset=600_000_000, sequence=3, target=False):
    return tuple(replace(sample, evidence_id=f"recovery-frame-{sequence + i}", sequence=sequence + i,
        object_observed_at_ns=sample.object_observed_at_ns + offset,
        object_pose=store.installation.policy.target_pose if target else sample.object_pose,
        owners=tuple(replace(owner, links_observed_at_ns=owner.links_observed_at_ns + offset,
            gripper_observed_at_ns=owner.gripper_observed_at_ns + offset) for owner in sample.owners))
        for i, sample in enumerate(observations(store, state)))


def arguments(case):
    _, _, store, executor, job, state = case
    view = api().recovery_context(executor, job["mission_id"])
    assert view["execution_authorized"] is False
    return dict(proposer=PROPOSER, principal=OPERATOR,
        **{key: view[key] for key in ("expected_request_digest", "expected_receipt_event_id",
            "expected_assessment_digest", "expected_generation")},
        observations=measured(store, state), authenticated_producer_id=store.installation.policy.producer_id,
        capabilities=store.installation.capabilities, capabilities_observed_at_ns=store._now_ns() - 1)


def recover(case, **changes):
    return api().recover_transfer(case[3], case[4]["mission_id"], **{**arguments(case), **changes})


def snapshot(path):
    with connect(path) as connection:
        return tuple(connection.iterdump())


@pytest.fixture
def failed_transfer(submitted):
    observe(submitted, phase_receipt(submitted))
    submitted[2]._clock_ns = lambda: NOW + 1_000_000_000
    return submitted


def test_recovery_preserves_parent_and_mints_one_child(failed_transfer):
    path, _, store, executor, parent, _ = failed_transfer
    original = executor.snapshot(parent["mission_id"])
    child = recover(failed_transfer)
    assert child["mission_id"] != parent["mission_id"] and child["status"] == "READY"
    assert child["approved_by"] == OPERATOR.principal_id
    assert child["proposal_principal_id"] == PROPOSER.principal_id
    assert child["request"] == parent["request"]
    assert executor.snapshot(parent["mission_id"]) == original
    assert {row["owner_id"] for row in claims(path)} == {child["mission_id"]}
    assert {row["phase"] for row in claims(path)} == {"CLAIMED"}
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_attempts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_observations").fetchone()[0] == 1
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_concurrent_replay_and_reopen_keep_one_child_even_when_evidence_is_old(failed_transfer):
    path, _, store, executor, parent, _ = failed_transfer
    args = arguments(failed_transfer)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: api().recover_transfer(executor, parent["mission_id"], **args), range(8)))
    assert all(child == results[0] for child in results)
    reopened = type(store)(path, installation=store.installation, deployment_profile="simulation",
                           clock_ns=lambda: NOW + 10_000_000_000)
    assert api().recover_transfer(execution(reopened), parent["mission_id"], **args) == results[0]
    changed = {**args, "observations": measured(store, failed_transfer[5], sequence=9)}
    before = snapshot(path)
    with pytest.raises(MissionConflict):
        api().recover_transfer(executor, parent["mission_id"], **changed)
    assert snapshot(path) == before


def test_child_cannot_recover_again(failed_transfer):
    child = recover(failed_transfer)
    with pytest.raises(MissionConflict):
        api().recovery_context(failed_transfer[3], child["mission_id"])


@pytest.mark.parametrize("state", ["UNKNOWN", "HOLD", "RUNNING", "CANCEL_REQUESTED"])
def test_uncertain_or_active_owner_is_not_a_recovery_candidate(submitted, state):
    observe(submitted, receipt(submitted, state=state))
    before = snapshot(submitted[0])
    with pytest.raises(MissionConflict):
        api().recovery_context(submitted[3], submitted[4]["mission_id"])
    assert snapshot(submitted[0]) == before


@pytest.mark.parametrize("kind", ["held", "moving", "target", "missing", "attempt", "stale", "producer"])
def test_unproven_source_or_clearance_never_releases_parent_claims(failed_transfer, kind):
    args = arguments(failed_transfer)
    values = list(args["observations"])
    if kind == "held":
        owner = replace(values[0].owners[0], held_state="UNKNOWN")
        values[0] = replace(values[0], owners=(owner, *values[0].owners[1:]))
    elif kind == "moving":
        owner = values[0].owners[0]
        links = dict(owner.links)
        name = next(iter(links))
        links[name] = replace(links[name], linear_velocity_m_s=(.05, 0., 0.))
        values[0] = replace(values[0], owners=(replace(owner, links=links), *values[0].owners[1:]))
    elif kind == "target":
        values[0] = replace(values[0], object_pose=failed_transfer[2].installation.policy.target_pose)
    elif kind == "missing":
        values[0] = replace(values[0], object_pose=None)
    elif kind == "attempt":
        values[0] = replace(values[0], attempt_id="other-attempt")
    elif kind == "stale":
        failed_transfer[2]._clock_ns = lambda: NOW + 2_000_000_000
    else:
        args["authenticated_producer_id"] = "application"
    args["observations"] = tuple(values)
    before = snapshot(failed_transfer[0])
    with pytest.raises((ValueError, MissionConflict)):
        api().recover_transfer(failed_transfer[3], failed_transfer[4]["mission_id"], **args)
    assert snapshot(failed_transfer[0]) == before


@pytest.mark.parametrize("kind", ["self-approval", "other-proposer", "receipt", "digest", "fence", "claim"])
def test_permission_binding_and_current_claims_are_required(failed_transfer, kind):
    args = arguments(failed_transfer)
    if kind == "self-approval":
        args["principal"] = PROPOSER
    elif kind == "other-proposer":
        args["proposer"] = SitePrincipal("other-service", "service")
    elif kind == "receipt":
        args["expected_receipt_event_id"] += 1
    elif kind == "digest":
        args["expected_request_digest"] = "f" * 64
    elif kind == "fence":
        with connect(failed_transfer[0]) as connection:
            connection.execute("UPDATE fleet_dispatch_control SET generation=generation+1")
    else:
        with connect(failed_transfer[0]) as connection:
            connection.execute("DELETE FROM fleet_action_claims WHERE resource_key=(SELECT resource_key FROM fleet_action_claims LIMIT 1)")
    before = snapshot(failed_transfer[0])
    with pytest.raises((ValueError, PermissionError, MissionConflict)):
        api().recover_transfer(failed_transfer[3], failed_transfer[4]["mission_id"], **args)
    assert snapshot(failed_transfer[0]) == before


def test_late_lineage_write_failure_rolls_back_child_approval_and_claim_transfer(failed_transfer):
    args = arguments(failed_transfer)
    with connect(failed_transfer[0]) as connection:
        connection.execute("CREATE TRIGGER fail_recovery BEFORE INSERT ON fleet_cell_events "
            "WHEN NEW.event_type='PHYSICAL_TRANSFER_RECOVERY_ORIGIN' BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = snapshot(failed_transfer[0])
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        api().recover_transfer(failed_transfer[3], failed_transfer[4]["mission_id"], **args)
    assert snapshot(failed_transfer[0]) == before
