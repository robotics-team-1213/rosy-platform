from datetime import datetime, timedelta, timezone

from fleet.server.mission_model_turn_store import MissionModelTurnStore


def _scope():
    return {
        "principal_id": "operator-1", "workcell_id": "omx_01",
        "mission_id": "mission-1", "action_id": "action-1",
        "attempt_id": "attempt-1", "dispatch_generation": 4,
        "event_watermark": 19, "model_policy_revision": "policy-v1",
        "outcome_policy": "STATUS_ONLY",
    }


def test_outbox_insert_is_idempotent_and_never_persists_provider_transcript(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    first = store.enqueue(scope=_scope(), trigger_event_id=19)
    duplicate = store.enqueue(scope=_scope(), trigger_event_id=19)

    assert first["created"] is True
    assert duplicate["created"] is False
    assert duplicate["turn"]["turn_id"] == first["turn"]["turn_id"]
    assert duplicate["turn"]["state"] == "PENDING"
    assert set(duplicate["turn"]) == {
        "turn_id", "principal_id", "workcell_id", "mission_id", "action_id",
        "attempt_id", "dispatch_generation", "event_watermark",
        "model_policy_revision", "outcome_policy", "trigger_event_id",
        "state", "attempt_count", "claimed_by", "lease_until",
        "created_at", "updated_at", "reason_code",
    }


def test_outbox_capacity_is_hard_bounded_and_records_dropped_turns(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3", max_rows=1)
    first = store.enqueue(scope=_scope(), trigger_event_id=19)
    second_scope = {**_scope(), "event_watermark": 20}
    dropped = store.enqueue(scope=second_scope, trigger_event_id=20)

    assert first["created"] is True
    assert dropped["turn"] is None
    assert dropped["reason_code"] == "OUTBOX_CAPACITY"
    assert store.capacity_dropped_count() == 1


def test_outbox_trigger_identity_is_distinct_from_later_snapshot_watermark(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    scope = {**_scope(), "event_watermark": 23}

    result = store.enqueue(scope=scope, trigger_event_id=19)

    assert result["turn"]["trigger_event_id"] == 19
    assert result["turn"]["event_watermark"] == 23


def test_submission_attempt_is_durable_and_ambiguous_turn_is_not_reclaimable(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    turn_id = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]["turn_id"]

    claimed = store.claim(turn_id, worker_id="worker-1")
    assert claimed["state"] == "CLAIMED"
    submitting = store.mark_submitting(turn_id, worker_id="worker-1")
    assert submitting["state"] == "SUBMITTING"
    unknown = store.mark_unknown(turn_id, reason_code="PROVIDER_OUTCOME_UNKNOWN")

    assert unknown["state"] == "UNKNOWN"
    assert store.claim(turn_id, worker_id="worker-2") is None
    assert store.get(turn_id)["attempt_count"] == 1


def test_preflight_can_release_claim_but_invoked_attempt_cannot_return_to_pending(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    turn_id = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]["turn_id"]
    store.claim(turn_id, worker_id="worker-1")

    pending = store.release_preflight(turn_id, worker_id="worker-1",
                                      reason_code="EGRESS_POLICY_MISSING")
    assert pending["state"] == "PENDING"
    assert pending["attempt_count"] == 0

    store.claim(turn_id, worker_id="worker-2")
    store.mark_submitting(turn_id, worker_id="worker-2")
    assert store.release_preflight(turn_id, worker_id="worker-2",
                                   reason_code="LOCAL_ERROR") is None
    assert store.get(turn_id)["state"] == "SUBMITTING"


def test_stop_generation_suppresses_unsubmitted_turn(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    turn_id = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]["turn_id"]

    suppressed = store.suppress(turn_id, reason_code="STOP_GENERATION_CHANGED")

    assert suppressed["state"] == "SUPPRESSED"
    assert store.claim(turn_id, worker_id="worker-1") is None


def test_expired_claim_is_reclaimable_but_expired_submission_is_unknown(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3", claim_lease_seconds=10)
    claimed_id = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]["turn_id"]
    store.claim(claimed_id, worker_id="worker-1")

    now = datetime.now(timezone.utc) + timedelta(seconds=11)
    assert store.expire_claims(now=now) == 1
    reclaimed = store.claim(claimed_id, worker_id="worker-2")
    assert reclaimed["state"] == "CLAIMED"

    store.mark_submitting(claimed_id, worker_id="worker-2")
    later = now + timedelta(seconds=11)
    assert store.expire_claims(now=later) == 0
    assert store.get(claimed_id)["state"] == "UNKNOWN"


def test_claim_next_atomically_assigns_oldest_pending_turn_to_one_worker(tmp_path):
    store = MissionModelTurnStore(tmp_path / "fleet.sqlite3")
    first = store.enqueue(scope=_scope(), trigger_event_id=19)["turn"]
    second = store.enqueue(
        scope={**_scope(), "event_watermark": 20}, trigger_event_id=20,
    )["turn"]

    claimed_first = store.claim_next(worker_id="worker-1")
    claimed_second = store.claim_next(worker_id="worker-2")
    no_more = store.claim_next(worker_id="worker-3")

    assert claimed_first["turn_id"] == first["turn_id"]
    assert claimed_first["state"] == "CLAIMED"
    assert claimed_second["turn_id"] == second["turn_id"]
    assert claimed_second["state"] == "CLAIMED"
    assert no_more is None
