"""C4b G3: the Fleet dispatcher drives the ordered step ledger, one Action per step (D-403 §5, §7)."""

from datetime import datetime, timezone

import pytest

from core_common.protocol.schemas import DeviceActionReceipt, FleetCellTransferGrant
from fleet.server.cell_job_store import CellJobStore
from fleet.server.local_action_transport import LocalActionRejected
from fleet.server.step_action_kinds import dispatch_open, step_grant_digest
from fleet.server.step_dispatcher import StepJobDispatcher

from test_cell_job_store import _create, _goal, _stores

REVISIONS = {"omx_01_control": {"capability_revision": "cell-transfer-v1",
                                "config_revision": "cell-config-v1"}}
PHASES = ("approach", "grasp", "transfer", "release")


def _receipt(grant, state, event_id, *, phases=None):
    phases = PHASES if phases is None and state == "SUCCEEDED" else (phases or ())
    now = datetime.now(timezone.utc).isoformat()
    return DeviceActionReceipt.model_validate({
        "mission_id": grant.mission_id, "step_id": grant.step_id,
        "action_id": grant.action_id, "attempt_id": grant.attempt_id,
        "workcell_id": grant.workcell_id, "instance_id": grant.instance_id,
        "request_digest": grant.request_digest, "authority_epoch": grant.authority_epoch,
        "dispatch_generation": grant.dispatch_generation, "state": state,
        "journal_event_id": event_id, "observed_at": now, "reason": None,
        "phase_summaries": [{"phase_id": phase, "ordinal": ordinal,
                             "state": "SUCCEEDED" if state == "SUCCEEDED" else "RUNNING",
                             "journal_event_id": 1, "observed_at": now}
                            for ordinal, phase in enumerate(phases)],
    })


class Transport:
    def __init__(self):
        self.submissions, self.lookups = [], []
        self.on_submit = lambda grant: _receipt(grant, "ACCEPTED", 2, phases=("approach",))
        self.on_get = lambda grant: _receipt(grant, "RUNNING", 3, phases=("approach",))

    def submit(self, grant):
        self.submissions.append(grant)
        return self.on_submit(grant)

    def get(self, grant):
        self.lookups.append(grant.action_id)
        return self.on_get(grant)

    def cancel(self, grant, *, reason):
        raise AssertionError("the dispatcher never cancels")


def _setup(tmp_path, **kwargs):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = Transport()
    dispatcher = StepJobDispatcher(
        store, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
        deployment_profile="simulation", **kwargs,
    )
    return store, tasks, transport, dispatcher


def _claims(tasks):
    return sorted({claim["phase"] for claim in tasks.resource_claims(
        resource_kind="workcell", resource_id="omx_01")})


def _succeed(store, transport, dispatcher, index):
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 10 + index)
    result = dispatcher.dispatch_next()
    grant = transport.submissions[-1]
    store.confirm_step_goal("cell-mission-1", step_index=index, action_id=grant.action_id,
                            attempt_id=grant.attempt_id,
                            evidence=_goal(grant.action_id, grant.attempt_id, f"goal-{index}"))
    return result


def test_one_typed_grant_per_step_in_order_after_the_previous_goal(tmp_path):
    store, _, transport, dispatcher = _setup(tmp_path)

    first = dispatcher.dispatch_next()
    grant = transport.submissions[0]
    assert first["state"] == "ACCEPTED" and first["step_index"] == 0
    assert isinstance(grant, FleetCellTransferGrant)
    assert grant.step_id == "cell-mission-1:step-1" and grant.cell_transfer.step_index == 0
    assert grant.request_digest == step_grant_digest(grant)
    assert (grant.capability_revision, grant.config_revision) == ("cell-transfer-v1", "cell-config-v1")

    assert dispatcher.dispatch_next()["state"] == "RUNNING"  # reconciled by GetAction only
    assert len(transport.submissions) == 1 and transport.lookups == [grant.action_id]

    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 10)
    assert dispatcher.dispatch_next()["state"] == "ACTION_SUCCEEDED"
    # Step 1 waits for step 0's independent goal evidence.
    assert dispatcher.dispatch_next() is None
    assert len(transport.submissions) == 1

    store.confirm_step_goal("cell-mission-1", step_index=0, action_id=grant.action_id,
                            attempt_id=grant.attempt_id,
                            evidence=_goal(grant.action_id, grant.attempt_id, "goal-0"))
    dispatcher.dispatch_next()
    assert [g.cell_transfer.step_index for g in transport.submissions] == [0, 1]
    assert transport.submissions[1].action_id != grant.action_id


def test_success_callback_names_the_step_for_goal_evidence(tmp_path):
    seen = []
    store, _, transport, dispatcher = _setup(
        tmp_path, on_step_action_succeeded=lambda job, index: seen.append((job["mission_id"], index)))
    dispatcher.dispatch_next()
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 10)
    dispatcher.dispatch_next()
    assert seen == [("cell-mission-1", 0)]


def test_a_full_job_completes_and_releases_its_claims(tmp_path):
    store, tasks, transport, dispatcher = _setup(tmp_path)
    for index in range(2):
        dispatcher.dispatch_next()
        _succeed(store, transport, dispatcher, index)
    assert store.get("cell-mission-1")["status"] == "GOAL_CONFIRMED"
    assert _claims(tasks) == []
    assert dispatcher.dispatch_next() is None


def test_rejected_action_holds_the_job_with_a_reason_and_returns_claims(tmp_path):
    store, tasks, transport, dispatcher = _setup(tmp_path)

    def reject(grant):
        transport.submissions.append(grant)
        raise LocalActionRejected("GRANT_REJECTED: workcell capability or configuration is stale")

    transport.submit = reject
    result = dispatcher.dispatch_next()

    job = store.get("cell-mission-1")
    assert result["state"] == "HOLD"
    assert job["status"] == job["steps"][0]["status"] == "HOLD"
    assert job["reason"] == "LOCAL_ACTION_REJECTED"
    assert job["steps"][0]["result"]["detail"].startswith("GRANT_REJECTED")
    assert _claims(tasks) == ["CLAIMED"]
    assert dispatcher.dispatch_next() is None and len(transport.submissions) == 1


def test_unknown_submit_outcome_holds_pins_claims_and_never_resubmits(tmp_path):
    store, tasks, transport, dispatcher = _setup(tmp_path)

    def lost(grant):
        transport.submissions.append(grant)
        raise TimeoutError("response lost")

    transport.submit = lost
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    job = store.get("cell-mission-1")
    assert job["reason"] == "LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN"
    assert _claims(tasks) == ["UNKNOWN"]
    restarted = StepJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                                  deployment_profile="simulation")
    assert restarted.dispatch_next() is None and len(transport.submissions) == 1


def test_success_without_every_phase_is_not_success(tmp_path):
    store, tasks, transport, dispatcher = _setup(tmp_path)
    dispatcher.dispatch_next()
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 10, phases=PHASES[:3])
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert store.get("cell-mission-1")["reason"] == "LOCAL_ACTION_RECEIPT_INVALID"
    assert _claims(tasks) == ["UNKNOWN"]


@pytest.mark.parametrize("state, reason, claims", [
    ("FAILED", "LOCAL_ACTION_FAILED", ["CLAIMED"]),
    ("HOLD", "LOCAL_ACTION_HOLD", ["UNKNOWN"]),
    ("UNKNOWN", "LOCAL_ACTION_UNKNOWN", ["UNKNOWN"]),
])
def test_device_terminal_states_hold_the_job(tmp_path, state, reason, claims):
    store, tasks, transport, dispatcher = _setup(tmp_path)
    dispatcher.dispatch_next()
    transport.on_get = lambda grant: _receipt(grant, state, 10)
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert store.get("cell-mission-1")["reason"] == reason
    assert _claims(tasks) == claims


def test_a_stop_between_start_and_submit_holds_without_sending(tmp_path):
    store, tasks, transport, dispatcher = _setup(tmp_path)
    start_step = store.start_step

    def start_then_stop(*args, **kwargs):
        result = start_step(*args, **kwargs)
        tasks.trip_stop_latch(actor_id="operator-1")
        return result

    store.start_step = start_then_stop
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert transport.submissions == []
    assert store.get("cell-mission-1")["reason"] == "FLEET_FENCE_CHANGED_BEFORE_LOCAL_SUBMIT"


def test_a_stop_before_start_holds_the_job_with_the_fence_reason(tmp_path):
    store, tasks, transport, dispatcher = _setup(tmp_path)
    tasks.trip_stop_latch(actor_id="operator-1")
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert transport.submissions == []
    assert store.get("cell-mission-1")["reason"] == "FLEET_FENCE_CHANGED_BEFORE_SUBMISSION"


def test_unconfigured_instance_is_left_untouched(tmp_path):
    store, tasks, transport, _ = _setup(tmp_path)
    other = StepJobDispatcher(store, tasks, transport, {"omx_02": "omx_02_control"},
                              {"omx_02_control": REVISIONS["omx_01_control"]},
                              deployment_profile="simulation")
    assert other.dispatch_next()["state"] == "NOT_CONFIGURED"
    assert store.get("cell-mission-1")["status"] == "READY" and transport.submissions == []


@pytest.mark.parametrize("profile", ["production", "device", "field", ""])
def test_only_simulation_opens_cell_transfer_dispatch(profile):
    assert dispatch_open(profile, "CELL_TRANSFER") is False
    with pytest.raises(ValueError, match="closed"):
        StepJobDispatcher(None, None, Transport(), {"omx_01": "omx_01_control"}, REVISIONS,
                          deployment_profile=profile)


def test_other_kinds_stay_closed_even_in_simulation():
    assert dispatch_open("simulation", "CELL_TRANSFER") is True
    for kind in ("PICK_PLACE", "PICK", "NAVIGATE", ""):
        assert dispatch_open("simulation", kind) is False


def test_every_configured_instance_needs_simulation_grant_revisions(tmp_path):
    with pytest.raises(ValueError, match="revisions"):
        StepJobDispatcher(None, None, Transport(), {"omx_01": "omx_01_control"}, {},
                          deployment_profile="simulation")
