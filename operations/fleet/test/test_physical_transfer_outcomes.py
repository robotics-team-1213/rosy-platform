"""Owner receipts report Action facts while physical claims remain occupied."""
from datetime import datetime, timezone
import sqlite3

import pytest

from core_common.protocol.arm_transfer import FleetArmTransferGrant
from fleet.server.mission_store import MissionConflict
from test_physical_transfer_evidence import geometry, policy
from test_physical_transfer_store import NOW, PROPOSER, installation, rig, claims, connect
from test_physical_transfer_submission import prepared, authorize
from test_step_dispatcher import _receipt


@pytest.fixture
def submitted(prepared):
    authorize(prepared)
    prepared[2]._clock_ns = lambda: NOW + 400_000_000
    return prepared


def receipt(submitted, state="SUCCEEDED", event_id=5, **changes):
    grant = FleetArmTransferGrant.model_validate(submitted[5]["grant"])
    now = datetime.fromtimestamp((NOW + 380_000_000) / 1e9, timezone.utc)
    value = _receipt(grant, state, event_id)
    return value.model_copy(update={"journal_id": grant.owner_journal_id, "observed_at": now,
        "phase_summaries": tuple(p.model_copy(update={"observed_at": now}) for p in value.phase_summaries), **changes})


def observe(submitted, value):
    executor, job = submitted[3:5]
    method = getattr(executor, "record_receipt", None)
    assert method is not None, "physical owner receipt projection is missing"
    return method(job["mission_id"], value)


def test_action_success_retains_all_claims_and_stable_success_boundary(submitted):
    path, _, store, _, job, _ = submitted
    result = observe(submitted, receipt(submitted))
    assert result["status"] == "ACTION_SUCCEEDED" and result["action_succeeded_at_ns"] == NOW + 400_000_000
    assert store.get(job["mission_id"], principal=PROPOSER)["status"] == "ACTION_SUCCEEDED"
    assert len(claims(path)) == len(store.installation.policy.resources)
    assert {c["phase"] for c in claims(path)} == {"HELD"}
    store._clock_ns = lambda: NOW + 450_000_000
    assert observe(submitted, receipt(submitted, created=True)) == result
    assert observe(submitted, receipt(submitted, state="RUNNING", event_id=3)) == result
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_events WHERE event_type='PHYSICAL_TRANSFER_RECEIPT'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM fleet_physical_transfer_observations WHERE phase='POST_ACTION'").fetchone()[0] == 0


@pytest.mark.parametrize("changes", [{"journal_id": "other"}, {"attempt_id": "other"},
    {"request_digest": "f" * 64}, {"phase_summaries": ()},
    {"observed_at": datetime.fromtimestamp(50, timezone.utc)}])
def test_wrong_owner_attempt_digest_incomplete_phases_or_future_time_cannot_report_success(submitted, changes):
    before = claims(submitted[0])
    with pytest.raises((ValueError, MissionConflict)):
        observe(submitted, receipt(submitted, **changes))
    assert claims(submitted[0]) == before
    with connect(submitted[0]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_events WHERE event_type='PHYSICAL_TRANSFER_RECEIPT'").fetchone()[0] == 0


def test_same_watermark_with_different_result_is_rejected(submitted):
    observe(submitted, receipt(submitted))
    with pytest.raises(MissionConflict):
        observe(submitted, receipt(submitted, state="FAILED"))
    assert {c["phase"] for c in claims(submitted[0])} == {"HELD"}


@pytest.mark.parametrize("state", ["FAILED", "HOLD", "UNKNOWN", "CANCEL_REQUESTED"])
def test_non_success_never_releases_physical_claims(submitted, state):
    path, _, store, _, job, _ = submitted
    observe(submitted, receipt(submitted, state=state))
    assert store.get(job["mission_id"], principal=PROPOSER)["status"] == "HOLD"
    assert len(claims(path)) == len(store.installation.policy.resources)
    assert {c["phase"] for c in claims(path)} == {"UNKNOWN"}


def test_late_success_after_site_stop_is_recorded_without_reviving_the_job(submitted):
    path, tasks, store, _, job, _ = submitted
    tasks.trip_stop_latch(actor_id="operator")
    observe(submitted, receipt(submitted))
    assert store.get(job["mission_id"], principal=PROPOSER)["status"] == "HOLD"
    assert {c["phase"] for c in claims(path)} == {"UNKNOWN"}


def test_outcome_event_failure_rolls_back_parent_attempt_and_claims(submitted):
    path, _, store, _, job, _ = submitted
    before = claims(path)
    with connect(path) as connection:
        connection.execute("CREATE TRIGGER fail_physical_receipt BEFORE INSERT ON fleet_cell_events "
            "WHEN NEW.event_type='PHYSICAL_TRANSFER_RECEIPT' BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        observe(submitted, receipt(submitted))
    assert claims(path) == before
    assert store.get(job["mission_id"], principal=PROPOSER)["status"] == "RUNNING"


@pytest.mark.parametrize("early", ["receipt", "phase", "equal-boundary"])
def test_receipt_and_every_phase_must_follow_the_final_first_send_intent(submitted, early):
    value = receipt(submitted)
    moment = NOW + (350_000_000 if early == "equal-boundary" else 200_000_000)
    timestamp = datetime.fromtimestamp(moment / 1e9, timezone.utc)
    if early == "phase":
        value = value.model_copy(update={"phase_summaries": (value.phase_summaries[0].model_copy(
            update={"observed_at": timestamp}), *value.phase_summaries[1:])})
    else:
        value = value.model_copy(update={"observed_at": timestamp, "phase_summaries": tuple(
            p.model_copy(update={"observed_at": timestamp}) for p in value.phase_summaries)})
    before = claims(submitted[0])
    with pytest.raises((ValueError, MissionConflict)):
        observe(submitted, value)
    assert claims(submitted[0]) == before


@pytest.mark.parametrize("initial", ["UNKNOWN", "CANCEL_REQUESTED"])
@pytest.mark.parametrize("later", ["RUNNING", "SUCCEEDED"])
def test_later_owner_facts_do_not_automatically_resume_a_held_operation(submitted, initial, later):
    path, _, store, _, job, _ = submitted
    observe(submitted, receipt(submitted, state=initial, event_id=4))
    result = observe(submitted, receipt(submitted, state=later, event_id=5))
    assert result["status"] == "UNKNOWN" and result["action_succeeded_at_ns"] is None
    assert store.get(job["mission_id"], principal=PROPOSER)["status"] == "HOLD"
    assert {c["phase"] for c in claims(path)} == {"UNKNOWN"}
