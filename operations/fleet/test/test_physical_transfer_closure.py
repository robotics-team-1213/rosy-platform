"""Only independent post-success physical facts release the original claim set."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3

import pytest

from fleet.server.mission_store import MissionConflict
from test_physical_transfer_evidence import geometry, policy
from test_physical_transfer_store import NOW, PROPOSER, OPERATOR, installation, rig, create, admit, claims, connect
from test_physical_transfer_submission import prepared, observations
from test_physical_transfer_outcomes import submitted, receipt, observe


@pytest.fixture
def succeeded(submitted):
    observe(submitted, receipt(submitted))
    submitted[2]._clock_ns = lambda: NOW + 800_000_000
    return submitted


def post_samples(succeeded):
    store, row = succeeded[2], succeeded[5]
    return tuple(replace(sample, evidence_id="post-" + sample.evidence_id, sequence=sample.sequence + 2,
        object_observed_at_ns=sample.object_observed_at_ns + 450_000_000,
        object_pose=store.installation.policy.target_pose,
        owners=tuple(replace(owner, links_observed_at_ns=owner.links_observed_at_ns + 450_000_000,
            gripper_observed_at_ns=owner.gripper_observed_at_ns + 450_000_000) for owner in sample.owners))
        for sample in observations(store, row))


def confirm(succeeded, **changes):
    _, _, store, executor, job, row = succeeded
    args = dict(expected_request_digest=row["grant"]["request_digest"], observations=post_samples(succeeded),
        authenticated_producer_id=store.installation.policy.producer_id,
        capabilities=store.installation.capabilities, capabilities_observed_at_ns=store._now_ns() - 1)
    method = getattr(executor, "confirm_physical", None)
    assert method is not None, "atomic physical receipt and claim release are missing"
    return method(job["mission_id"], **{**args, **changes})


def test_physical_receipt_and_full_claim_release_are_atomic_and_replay_is_stable(succeeded):
    path, _, store, _, job, row = succeeded
    physical = confirm(succeeded)
    assert physical["mission_id"] == job["mission_id"]
    assert physical["action_id"] == row["grant"]["action_id"] and physical["attempt_id"] == row["grant"]["attempt_id"]
    assert physical["request_digest"] == row["grant"]["request_digest"]
    assert physical["physical_status"] == "AT_TARGET_AND_CLEAR"
    assert physical["object_ref"] == store.installation.policy.object_ref and physical["target"] == store.installation.target
    assert physical["validated_at_ns"] == NOW + 800_000_000 and physical["receipt_id"]
    assert claims(path) == []
    assert store.get(job["mission_id"], principal=PROPOSER)["status"] == "GOAL_CONFIRMED"
    store._clock_ns = lambda: NOW + 3_000_000_000
    assert confirm(succeeded) == physical
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_observations WHERE phase='POST_ACTION'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_events WHERE event_type='PHYSICAL_TRANSFER_CONFIRMED'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_steps").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["single", "source-pose", "producer", "digest", "stale", "before-success",
                                    "participant", "reused-evidence", "capability", "stop"])
def test_incomplete_or_wrong_physical_facts_never_release_any_claim(succeeded, failure):
    path, tasks, store, _, job, _ = succeeded
    measured = post_samples(succeeded)
    changes = {}
    if failure == "single":
        changes["observations"] = measured[:1]
    elif failure == "source-pose":
        changes["observations"] = tuple(replace(s, object_pose=store.installation.policy.source_pose) for s in measured)
    elif failure == "producer":
        changes["authenticated_producer_id"] = "harbor"
    elif failure == "digest":
        changes["expected_request_digest"] = "f" * 64
    elif failure == "stale":
        store._clock_ns = lambda: NOW + 1_100_000_000
    elif failure == "before-success":
        changes["observations"] = tuple(replace(s, object_observed_at_ns=NOW + 400_000_000) for s in measured)
    elif failure == "participant":
        changes["observations"] = tuple(replace(s, owners=s.owners[:1]) for s in measured)
    elif failure == "reused-evidence":
        changes["observations"] = tuple(replace(s, evidence_id="ev-" + str(i), sequence=i) for i, s in enumerate(measured, 1))
    elif failure == "capability":
        changes["capabilities"] = (store.installation.capabilities[0].model_copy(update={"owner_session_id": "changed"}),
                                   *store.installation.capabilities[1:])
    else:
        tasks.trip_stop_latch(actor_id="operator")
    before = claims(path)
    with pytest.raises((ValueError, MissionConflict)):
        confirm(succeeded, **changes)
    assert claims(path) == before
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_observations WHERE phase='POST_ACTION'").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["delete", "event"])
def test_mid_transaction_failure_preserves_receipt_absence_and_all_claims(succeeded, failure):
    path, _, store, _, job, _ = succeeded
    before = claims(path)
    with connect(path) as connection:
        if failure == "delete":
            connection.execute("CREATE TRIGGER fail_physical_release BEFORE DELETE ON fleet_action_claims "
                               "BEGIN SELECT RAISE(ABORT,'injected'); END")
        else:
            connection.execute("CREATE TRIGGER fail_physical_release BEFORE INSERT ON fleet_cell_events "
                "WHEN NEW.event_type='PHYSICAL_TRANSFER_CONFIRMED' BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        confirm(succeeded)
    assert claims(path) == before
    assert store.get(job["mission_id"], principal=PROPOSER)["status"] == "ACTION_SUCCEEDED"
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_observations WHERE phase='POST_ACTION'").fetchone()[0] == 0


def test_next_admission_and_duplicate_closure_never_release_the_new_owner(succeeded):
    path, tasks, store, _, _, _ = succeeded
    next_job = create(store, key="next")
    control = tasks.dispatch_control()
    def next_admit():
        try:
            return admit(store, next_job, control, capabilities_observed_at_ns=store._now_ns() - 1)
        except MissionConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        closed = pool.submit(confirm, succeeded)
        other = pool.submit(next_admit)
        physical, next_ready = closed.result(), other.result()
    if next_ready is None:
        next_ready = next_admit()
    assert next_ready["status"] == "READY"
    assert confirm(succeeded) == physical
    assert {c["owner_id"] for c in claims(path)} == {next_job["mission_id"]}
    assert len(claims(path)) == len(store.installation.policy.resources)


@pytest.mark.parametrize("state", ["RUNNING", "UNKNOWN", "FAILED"])
def test_physical_clearance_without_a_successful_action_is_not_a_release(submitted, state):
    path, _, store, _, job, _ = submitted
    if state != "RUNNING":
        observe(submitted, receipt(submitted, state=state))
    store._clock_ns = lambda: NOW + 800_000_000
    before = claims(path)
    with pytest.raises((ValueError, MissionConflict)):
        confirm(submitted)
    assert claims(path) == before


def test_a_confirmed_physical_receipt_cannot_be_replaced_by_different_evidence(succeeded):
    original = confirm(succeeded)
    changed = tuple(replace(s, evidence_id="changed-" + s.evidence_id) for s in post_samples(succeeded))
    with pytest.raises(MissionConflict):
        confirm(succeeded, observations=changed)
    assert confirm(succeeded) == original


@pytest.mark.parametrize("final_ns", [NOW + 790_000_000, NOW + 1_100_000_000])
def test_physical_release_rechecks_the_final_clock_and_freshness(succeeded, monkeypatch, final_ns):
    from importlib import import_module
    module = import_module("fleet.server.physical_transfer_execution")
    real_validate = module.validate_transfer_observations
    def change_time_after_validation(*args, **kwargs):
        result = real_validate(*args, **kwargs)
        succeeded[2]._clock_ns = lambda: final_ns
        return result
    monkeypatch.setattr(module, "validate_transfer_observations", change_time_after_validation)
    before = claims(succeeded[0])
    with pytest.raises((ValueError, MissionConflict)):
        confirm(succeeded)
    assert claims(succeeded[0]) == before


def test_physical_release_uses_the_same_frozen_sample_snapshot_for_validation_and_record(succeeded, monkeypatch):
    from importlib import import_module
    import json
    module = import_module("fleet.server.physical_transfer_execution")
    real_validate = module.validate_transfer_observations
    caller_samples = list(post_samples(succeeded))
    def replace_after_validation(*args, **kwargs):
        result = real_validate(*args, **kwargs)
        caller_samples[0] = replace(caller_samples[0], object_pose=succeeded[2].installation.policy.source_pose)
        return result
    monkeypatch.setattr(module, "validate_transfer_observations", replace_after_validation)
    confirm(succeeded, observations=caller_samples)
    with connect(succeeded[0]) as connection:
        raw = json.loads(connection.execute("SELECT evidence_json FROM fleet_physical_transfer_observations "
                                          "WHERE phase='POST_ACTION'").fetchone()[0])
        assert raw["samples"][0]["object_pose"]["position_m"] == list(succeeded[2].installation.policy.target_pose.position_m)
