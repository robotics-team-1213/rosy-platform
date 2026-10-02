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

    def owner_identity(self, instance_id):
        return {"workcell_id": instance_id.removesuffix("_control"), "instance_id": instance_id,
                "simulation": True, "profile": "omx-cell-sim"}


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
    assert _claims(tasks) == ["HELD"]  # the held Job keeps its claims until it is terminal
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
    restarted.dispatch_next()  # 1b A3: the held Job is read back, never resubmitted
    assert len(transport.submissions) == 1 and transport.lookups


def test_success_without_every_phase_is_not_success(tmp_path):
    store, tasks, transport, dispatcher = _setup(tmp_path)
    dispatcher.dispatch_next()
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 10, phases=PHASES[:3])
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert store.get("cell-mission-1")["reason"] == "LOCAL_ACTION_RECEIPT_INVALID"
    assert _claims(tasks) == ["UNKNOWN"]


@pytest.mark.parametrize("state, reason, claims", [
    ("FAILED", "LOCAL_ACTION_FAILED", ["HELD"]),
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


def test_a_stop_after_start_keeps_the_claims_and_relies_on_the_owner_fence(tmp_path):
    # 1c P1: once start_step committed, the step's claims are never released by the dispatcher.
    # The grant still carries the old generation, which the owner's stop fence refuses.
    store, tasks, transport, dispatcher = _setup(tmp_path)
    start_step = store.start_step

    def start_then_stop(*args, **kwargs):
        result = start_step(*args, **kwargs)
        tasks.trip_stop_latch(actor_id="operator-1")
        return result

    store.start_step = start_then_stop
    dispatcher.dispatch_next()
    assert transport.submissions[0].dispatch_generation < tasks.dispatch_control()["generation"]
    assert _claims(tasks) == ["DISPATCHING"]
    assert tasks.dispatch_control()["rearm_available"] is False


def test_a_stop_before_start_holds_the_job_and_keeps_its_claims(tmp_path):
    store, tasks, transport, dispatcher = _setup(tmp_path)
    tasks.trip_stop_latch(actor_id="operator-1")
    assert dispatcher.dispatch_next() is None
    assert transport.submissions == []
    assert store.get("cell-mission-1")["reason"] == "site_stop"
    assert _claims(tasks) == ["HELD"]


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


def _job_on(store, generation, mission_id, workcell, instance, pallet):
    from test_cell_job_store import _submission
    submission = _submission()
    submission.update(workcell_id=workcell, instance_id=instance,
                      resources=[["workcell", workcell], ["pallet", pallet]])
    for step in submission["steps"]:
        step["inputs"]["pallet_id"] = pallet
    submission["ledger_markers"] = [{"after_step_ordinal": 2, "pallet_id": pallet}]
    store.create(mission_id=mission_id, proposal_principal_id="cell-service",
                 request_key=f"req-{mission_id}", request_digest="d" * 64, submission=submission)
    return store.admit(mission_id, actor_id="operator-1", expected_generation=generation)


def _two_workcells(tmp_path, *, configured=("omx_01", "omx_02")):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    instances = {"omx_00": "omx_00_control", "omx_01": "omx_01_control", "omx_02": "omx_02_control"}
    for mission_id, workcell in (("job-head", "omx_00"), ("job-b", "omx_01"), ("job-c", "omx_02")):
        _job_on(store, enabled["generation"], mission_id, workcell, instances[workcell], f"pallet-{workcell}")
    transport = Transport()
    configured_instances = {wc: instances[wc] for wc in configured}
    revisions = {instance: REVISIONS["omx_01_control"] for instance in configured_instances.values()}
    dispatcher = StepJobDispatcher(store, tasks, transport, configured_instances, revisions,
                                   deployment_profile="simulation")
    return store, transport, dispatcher


def test_an_unconfigured_head_does_not_starve_other_ready_jobs(tmp_path):
    # 1b B1: the oldest READY Job is on an unconfigured instance; the others still go.
    store, transport, dispatcher = _two_workcells(tmp_path)
    result = dispatcher.dispatch_next()
    assert result["state"] == "ACCEPTED"
    assert sorted(grant.mission_id for grant in transport.submissions) == ["job-b", "job-c"]
    assert store.get("job-head")["status"] == "READY"


def test_an_in_flight_job_does_not_block_a_ready_job(tmp_path):
    store, transport, dispatcher = _two_workcells(tmp_path, configured=("omx_01",))
    dispatcher.dispatch_next()  # job-b RUNNING
    dispatcher.omx_instances["omx_02"] = "omx_02_control"
    dispatcher.grant_revisions["omx_02_control"] = REVISIONS["omx_01_control"]
    dispatcher.dispatch_next()  # reads job-b back and submits job-c in the same cycle
    assert [grant.mission_id for grant in transport.submissions] == ["job-b", "job-c"]
    assert transport.lookups == [transport.submissions[0].action_id]


def test_a_start_step_value_error_holds_with_grant_invalid_and_sends_nothing(tmp_path, monkeypatch):
    # 1b B3.
    store, tasks, transport, dispatcher = _setup(tmp_path)

    def broken(*args, **kwargs):
        raise ValueError("CELL_TRANSFER payload does not match the persisted PlanBundle step")

    monkeypatch.setattr(store, "start_step", broken)
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    job = store.get("cell-mission-1")
    assert job["reason"] == "ACTION_GRANT_INVALID" and transport.submissions == []
    assert _claims(tasks) == []


def test_the_store_judges_grant_currency_with_the_dispatcher_clock(tmp_path):
    # 1b B4: one clock. A dispatcher clock an hour ahead makes a grant the store must accept.
    from datetime import timedelta
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    store, _, transport, dispatcher = _setup(tmp_path, now=lambda: later)
    assert dispatcher.dispatch_next()["state"] == "ACCEPTED"
    assert transport.submissions[0].issued_at == later


def test_a_result_conflict_is_reported_once_and_not_retried(tmp_path, monkeypatch, caplog):
    # 1b B6.
    from fleet.server.mission_store import MissionConflict
    store, _, transport, dispatcher = _setup(tmp_path)
    dispatcher.dispatch_next()
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 10)

    def conflict(*args, **kwargs):
        raise MissionConflict("Cell Job event identity was reused with different evidence")

    monkeypatch.setattr(store, "record_action_result", conflict)
    assert dispatcher.dispatch_next()["state"] == "RESULT_CONFLICT"
    assert "could not be recorded" in caplog.text


@pytest.mark.parametrize("identity", [
    {"workcell_id": "omx_01", "instance_id": "omx_01_control", "simulation": False},
    {"workcell_id": "omx_01", "instance_id": "other", "simulation": True},
    None,
])
def test_a_target_that_is_not_a_simulation_identity_is_not_dispatched(tmp_path, identity):
    # 1b C3 (D-403 §7, D-390 §5): the owner's own report gates dispatch, not just the profile.
    store, _, transport, dispatcher = _setup(tmp_path)

    def report(instance_id):
        if identity is None:
            raise LocalActionRejected("UNKNOWN_OPERATION: operation is not supported")
        return identity

    transport.owner_identity = report
    assert dispatcher.dispatch_next()["state"] == "NOT_SIMULATION"
    assert transport.submissions == [] and store.get("cell-mission-1")["status"] == "READY"
