"""Physical preconditions and first-send intent share the claim transaction."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from fleet.server.mission_store import MissionConflict
from test_physical_transfer_evidence import geometry, policy, samples
from test_physical_transfer_store import NOW, PROPOSER, installation, rig, create, admit, claims, connect
from test_physical_transfer_preparation import execution, prepare


def observations(store, prepared):
    grant = prepared["grant"]
    return tuple(replace(sample, action_id=grant["action_id"], attempt_id=grant["attempt_id"],
        object_observed_at_ns=sample.object_observed_at_ns + 1_000_000_000,
        owners=tuple(replace(owner, links_observed_at_ns=owner.links_observed_at_ns + 1_000_000_000,
            gripper_observed_at_ns=owner.gripper_observed_at_ns + 1_000_000_000) for owner in sample.owners))
        for sample in samples(store.installation.policy))


@pytest.fixture
def prepared(rig):
    path, tasks, control, store = rig
    job = admit(store, create(store), control)
    executor = execution(store)
    row = prepare(executor, job["mission_id"], store)
    store._clock_ns = lambda: NOW + 350_000_000
    return path, tasks, store, executor, job, row


def authorize(prepared, **changes):
    _, _, store, executor, job, row = prepared
    arguments = dict(expected_request_digest=row["grant"]["request_digest"],
        observations=observations(store, row), authenticated_producer_id=store.installation.policy.producer_id,
        capabilities=store.installation.capabilities, capabilities_observed_at_ns=store._now_ns() - 1)
    method = getattr(executor, "authorize_submission", None)
    assert method is not None, "physical first-send transaction is missing"
    return method(job["mission_id"], **{**arguments, **changes})


def test_two_post_preparation_source_samples_and_first_send_intent_commit_atomically(prepared):
    path, _, store, _, job, row = prepared
    intent = authorize(prepared)
    assert intent["status"] == "SUBMITTING" and intent["grant"] == row["grant"]
    assert store.get(job["mission_id"], principal=PROPOSER)["status"] == "RUNNING"
    assert {c["phase"] for c in claims(path)} == {"DISPATCHING"}
    assert len(claims(path)) == len(store.installation.policy.resources)
    with connect(path) as connection:
        proof = connection.execute("SELECT * FROM fleet_physical_transfer_observations").fetchone()
        assert proof["phase"] == "PRE_DISPATCH" and proof["request_digest"] == row["grant"]["request_digest"]
        assert proof["validated_at_ns"] == NOW + 350_000_000
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_events WHERE event_type='PHYSICAL_TRANSFER_SUBMITTING'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_steps").fetchone()[0] == 0
    with pytest.raises(MissionConflict):
        authorize(prepared)


@pytest.mark.parametrize("failure", ["producer", "digest", "single", "before-preparation", "stale", "held", "capability", "stop"])
def test_incomplete_wrong_or_stale_preconditions_never_authorize_send(prepared, failure):
    path, tasks, store, _, job, row = prepared
    changes = {}
    measured = observations(store, row)
    if failure == "producer":
        changes["authenticated_producer_id"] = "harbor"
    elif failure == "digest":
        changes["expected_request_digest"] = "f" * 64
    elif failure == "single":
        changes["observations"] = measured[:1]
    elif failure == "before-preparation":
        changes["observations"] = tuple(replace(s, object_observed_at_ns=NOW) for s in measured)
    elif failure == "stale":
        store._clock_ns = lambda: NOW + 1_000_000_000
    elif failure == "held":
        changes["observations"] = tuple(replace(s, owners=(replace(s.owners[0], held_state="HELD",
            held_object_ref=store.installation.policy.object_ref), *s.owners[1:])) for s in measured)
    elif failure == "capability":
        changes["capabilities"] = (store.installation.capabilities[0].model_copy(update={"owner_session_id": "changed"}),
                                   *store.installation.capabilities[1:])
    else:
        tasks.trip_stop_latch(actor_id="operator")
    before = claims(path)
    with pytest.raises((ValueError, MissionConflict)):
        authorize(prepared, **changes)
    assert claims(path) == before
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_observations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_events WHERE event_type='PHYSICAL_TRANSFER_SUBMITTING'").fetchone()[0] == 0


def test_concurrent_authorizers_issue_only_one_first_send_intent(prepared):
    def attempt(_):
        try:
            return authorize(prepared)["status"]
        except MissionConflict:
            return "CONFLICT"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["CONFLICT", "SUBMITTING"]


def test_observation_or_event_sql_failure_rolls_back_proof_parent_attempt_and_claims(prepared):
    path, _, store, _, job, _ = prepared
    before = claims(path)
    with connect(path) as connection:
        connection.execute("CREATE TRIGGER fail_submit_intent BEFORE INSERT ON fleet_cell_events "
            "WHEN NEW.event_type='PHYSICAL_TRANSFER_SUBMITTING' BEGIN SELECT RAISE(ABORT,'injected'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        authorize(prepared)
    assert claims(path) == before
    assert store.get(job["mission_id"], principal=PROPOSER)["status"] == "READY"
    with connect(path) as connection:
        assert connection.execute("SELECT status FROM fleet_physical_transfer_attempts").fetchone()[0] == "PREPARED"
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_observations").fetchone()[0] == 0


@pytest.mark.parametrize("final_ns", [NOW + 340_000_000, NOW + 1_100_000_000, NOW + 20_000_000_000])
def test_final_send_check_rejects_clock_regression_stale_facts_and_expiry(prepared, monkeypatch, final_ns):
    path, _, store, _, job, _ = prepared
    original = store._document
    def advance_during_snapshot_check(request):
        store._clock_ns = lambda: final_ns
        return original(request)
    monkeypatch.setattr(store, "_document", advance_during_snapshot_check)
    before = claims(path)
    with pytest.raises((MissionConflict, ValueError)):
        authorize(prepared)
    assert claims(path) == before
    assert store.get(job["mission_id"], principal=PROPOSER)["status"] == "READY"
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_observations").fetchone()[0] == 0


def test_caller_list_mutation_cannot_replace_the_facts_validated_and_persisted(prepared, monkeypatch):
    from importlib import import_module
    import json
    path, _, store, _, _, row = prepared
    caller_samples = list(observations(store, row))
    module = import_module("fleet.server.physical_transfer_execution")
    real_validate = module.validate_transfer_observations
    def mutate_after_validation(*args, **kwargs):
        result = real_validate(*args, **kwargs)
        caller_samples[0] = replace(caller_samples[0], object_pose=store.installation.policy.target_pose)
        return result
    monkeypatch.setattr(module, "validate_transfer_observations", mutate_after_validation)
    assert authorize(prepared, observations=caller_samples)["status"] == "SUBMITTING"
    with connect(path) as connection:
        proof = json.loads(connection.execute("SELECT evidence_json FROM fleet_physical_transfer_observations").fetchone()[0])
        assert proof["samples"][0]["object_pose"]["position_m"] == list(store.installation.policy.source_pose.position_m)
