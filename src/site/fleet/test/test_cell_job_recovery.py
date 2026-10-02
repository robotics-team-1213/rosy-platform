"""C4b 1b A3 (review M2, D-403 §7(h)): a held Cell Job has a way out.

Readback: the dispatcher keeps reading back a HOLD Job whose claims are UNKNOWN, with backoff for
transient GetAction failures. Operator: reconcile, resume (named operator, new generation) and
cancel (terminal, releases the claims in the same transaction).
"""


import pytest

from fleet.server.cell_job_store import CellJobStore
from fleet.server.mission_store import MissionConflict
from fleet.server.step_dispatcher import READBACK_FAILURE_LIMIT, StepJobDispatcher

from test_cell_job_store import _claim_phases, _create, _goal, _second_job, _stores
from test_step_dispatcher import REVISIONS, Transport, _receipt


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _unknown_job(tmp_path, clock=None):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = Transport()
    dispatcher = StepJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                                   deployment_profile="simulation", monotonic=clock or Clock())

    def lost(grant):
        transport.submissions.append(grant)
        raise TimeoutError("response lost")

    transport.submit = lost
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert {phase for _, _, phase in _claim_phases(path)} == {"UNKNOWN"}
    return path, tasks, store, transport, dispatcher


def test_held_unknown_job_is_read_back_to_action_succeeded(tmp_path):
    path, _, store, transport, dispatcher = _unknown_job(tmp_path)
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 20)
    dispatcher.dispatch_next()
    job = store.get("cell-mission-1")
    assert job["status"] == job["steps"][0]["status"] == "ACTION_SUCCEEDED"
    assert {phase for _, _, phase in _claim_phases(path)} == {"CLAIMED"}
    assert len(transport.submissions) == 1  # read back, never resubmitted


@pytest.mark.parametrize("outcome, reason", [("FAILED", "LOCAL_ACTION_FAILED"),
                                             ("NOT_FOUND", "LOCAL_ACTION_NOT_FOUND_AFTER_SUBMIT")])
def test_confirmed_failure_or_not_found_keeps_hold_but_parks_claims(tmp_path, outcome, reason):
    path, tasks, store, transport, dispatcher = _unknown_job(tmp_path)
    transport.on_get = (lambda grant: None) if outcome == "NOT_FOUND" else (
        lambda grant: _receipt(grant, "FAILED", 20))
    dispatcher.now = _later(60)  # past grant expiry + skew (1c item 3)
    dispatcher.dispatch_next()
    job = store.get("cell-mission-1")
    assert job["status"] == "HOLD" and job["reason"] == reason
    assert {phase for _, _, phase in _claim_phases(path)} == {"HELD"}
    stopped = tasks.trip_stop_latch(actor_id="operator-1")
    assert stopped["rearm_available"] is True


def test_transient_readback_failures_back_off_before_unknown(tmp_path):
    clock = Clock()
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = Transport()
    dispatcher = StepJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                                   deployment_profile="simulation", monotonic=clock)
    dispatcher.dispatch_next()

    def timeout(grant):
        transport.lookups.append(grant.action_id)
        raise TimeoutError("busy owner")

    transport.on_get = timeout
    transport.get = timeout
    for attempt in range(READBACK_FAILURE_LIMIT - 1):
        dispatcher.dispatch_next()
        assert store.get("cell-mission-1")["status"] == "RUNNING"
        before = len(transport.lookups)
        dispatcher.dispatch_next()  # still inside the backoff window: no read
        assert len(transport.lookups) == before
        clock.t += 60
    dispatcher.dispatch_next()
    job = store.get("cell-mission-1")
    assert job["status"] == "HOLD" and job["reason"] == "LOCAL_ACTION_READBACK_UNKNOWN"
    assert len(transport.lookups) == READBACK_FAILURE_LIMIT


def test_a_successful_read_resets_the_failure_count(tmp_path):
    clock = Clock()
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = Transport()
    dispatcher = StepJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                                   deployment_profile="simulation", monotonic=clock)
    dispatcher.dispatch_next()
    healthy = transport.get
    for _ in range(3):
        transport.get = lambda grant: (_ for _ in ()).throw(TimeoutError("busy"))
        for _ in range(READBACK_FAILURE_LIMIT - 1):
            dispatcher.dispatch_next()
            clock.t += 60
        transport.get = healthy
        dispatcher.dispatch_next()
        clock.t += 60
    assert store.get("cell-mission-1")["status"] == "RUNNING"


def test_resume_requires_resolved_claims_and_reclaims_under_the_new_generation(tmp_path):
    path, tasks, store, transport, dispatcher = _unknown_job(tmp_path)
    control = tasks.dispatch_control()
    with pytest.raises(MissionConflict, match="UNKNOWN"):
        store.resume("cell-mission-1", actor_id="operator-2", expected_generation=control["generation"])
    transport.on_get = lambda grant: _receipt(grant, "FAILED", 20)
    dispatcher.dispatch_next()
    stopped = tasks.trip_stop_latch(actor_id="operator-1")
    rearmed = tasks.rearm_dispatch(expected_generation=stopped["generation"], actor_id="operator-1")

    resumed = store.resume("cell-mission-1", actor_id="operator-2", expected_generation=rearmed["generation"])

    assert resumed["status"] == resumed["steps"][0]["status"] == "READY"
    assert resumed["steps"][0]["action_id"] is None
    assert resumed["dispatch_generation"] == rearmed["generation"]
    assert resumed["authority_epoch"] == rearmed["authority_epoch"]
    assert {(phase, gen) for gen, phase in _claim_generations(path)} == {("CLAIMED", rearmed["generation"])}
    transport.submit = Transport().submit
    transport.submit = lambda grant: transport.submissions.append(grant) or _receipt(
        grant, "ACCEPTED", 30, phases=("approach",))
    assert dispatcher.dispatch_next()["state"] == "ACCEPTED"
    assert len(transport.submissions) == 2


def test_resume_after_a_held_success_waits_for_goal_evidence_and_never_resends(tmp_path):
    path, tasks, store, transport, dispatcher = _unknown_job(tmp_path)
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 20)
    dispatcher.dispatch_next()
    stopped = tasks.trip_stop_latch(actor_id="operator-1")
    rearmed = tasks.rearm_dispatch(expected_generation=stopped["generation"], actor_id="operator-1")
    resumed = store.resume("cell-mission-1", actor_id="operator-2", expected_generation=rearmed["generation"])
    assert resumed["status"] == resumed["steps"][0]["status"] == "ACTION_SUCCEEDED"
    grant = transport.submissions[0]
    store.confirm_step_goal("cell-mission-1", step_index=0, action_id=grant.action_id,
                            attempt_id=grant.attempt_id,
                            evidence=_goal(grant.action_id, grant.attempt_id, "goal-0"))
    assert store.get("cell-mission-1")["steps"][1]["status"] == "READY"


def test_cancel_is_terminal_and_releases_claims_atomically(tmp_path):
    path, tasks, store, transport, dispatcher = _unknown_job(tmp_path)
    with pytest.raises(MissionConflict, match="UNKNOWN"):
        store.cancel("cell-mission-1", actor_id="operator-2")
    transport.on_get = lambda grant: _receipt(grant, "FAILED", 20)
    dispatcher.dispatch_next()
    cancelled = store.cancel("cell-mission-1", actor_id="operator-2")
    assert cancelled["status"] == "HOLD" and cancelled["reason"] == "CANCELLED_BY_OPERATOR"
    assert _claim_phases(path) == []
    assert any(event["event_type"] == "CELL_JOB_CANCELLED" for event in cancelled["events"])
    with pytest.raises(MissionConflict):
        store.resume("cell-mission-1", actor_id="operator-2",
                     expected_generation=tasks.dispatch_control()["generation"])
    _second_job(store, tasks.dispatch_control()["generation"])  # the resources are free again


def _claim_generations(path):
    import sqlite3
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT generation, phase FROM fleet_action_claims").fetchall()
    finally:
        connection.close()


def test_operator_routes_need_a_named_operator(tmp_path):
    from test_cell_job_api import _setup, _post, _candidate

    client, tasks, _ = _setup(tmp_path)
    request = {"request_key": "cell-job-1", "workcell_id": "omx_01",
               "instance_id": "omx_01_control", "candidate": _candidate()}
    proposal_id = _post(client, "/api/fleet/proposals", "cell-secret", request).json()["proposal"]["proposal_id"]
    _post(client, f"/api/fleet/proposals/{proposal_id}/resolve", "cell-secret")
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(expected_generation=control["generation"],
                                            actor_id="operator-1")["generation"]
    _post(client, f"/api/fleet/missions/{proposal_id}/admit", "operator-secret",
          {"expected_generation": generation})
    store = client.app.state.cell_job_store
    store.hold(proposal_id, reason="OPERATOR_HOLD", claim_phase="HELD", actor_id="operator-1",
               event_key="h")
    base = f"/api/fleet/cell-jobs/{proposal_id}"
    assert _post(client, f"{base}/resume", "cell-secret", {"expected_generation": generation}).status_code == 403
    assert _post(client, f"{base}/cancel", "viewer-secret").status_code == 403
    assert _post(client, f"{base}/reconcile", "operator-secret").status_code == 503  # no dispatcher
    resumed = _post(client, f"{base}/resume", "operator-secret", {"expected_generation": generation})
    assert resumed.status_code == 200 and resumed.json()["job"]["status"] == "READY"
    cancelled = _post(client, f"{base}/cancel", "operator-secret")
    assert cancelled.status_code == 200 and cancelled.json()["job"]["reason"] == "CANCELLED_BY_OPERATOR"
    assert tasks.store.resource_claims(resource_kind="workcell", resource_id="omx_01") == []


def test_claims_read_api_names_the_owning_job_status_and_phase(tmp_path):
    """C4b 1b (rosy-a9 condition 3): each claimed resource shows its owning Cell Job."""
    from test_cell_job_api import _setup, _post, _candidate

    client, tasks, _ = _setup(tmp_path)
    request = {"request_key": "cell-job-1", "workcell_id": "omx_01",
               "instance_id": "omx_01_control", "candidate": _candidate()}
    proposal_id = _post(client, "/api/fleet/proposals", "cell-secret", request).json()["proposal"]["proposal_id"]
    _post(client, f"/api/fleet/proposals/{proposal_id}/resolve", "cell-secret")
    control = tasks.store.dispatch_control()
    generation = tasks.store.rearm_dispatch(expected_generation=control["generation"],
                                            actor_id="operator-1")["generation"]
    _post(client, f"/api/fleet/missions/{proposal_id}/admit", "operator-secret",
          {"expected_generation": generation})
    tasks.store.trip_stop_latch(actor_id="operator-1")

    response = client.get("/api/fleet/resource-claims", headers={"Authorization": "Bearer viewer-secret"})

    assert response.status_code == 200
    claims = {claim["resource_key"]: claim for claim in response.json()["claims"]}
    assert set(claims) == {"workcell:omx_01", "pallet:pallet-1"}
    for claim in claims.values():
        assert claim["owner_kind"] == "mission" and claim["mission_id"] == proposal_id
        assert (claim["job_status"], claim["job_reason"], claim["phase"]) == ("HOLD", "site_stop", "HELD")
    assert client.get("/api/fleet/resource-claims").status_code in {401, 403}


def test_restart_with_a_running_step_has_an_exit(tmp_path):
    """C4b 1c N1 (D-403 §7(e)): restart -> HOLD with claims UNKNOWN -> readback resolves it."""
    # After a restart the authority changed, so even a success parks the Job HELD (1c item 2a);
    # the success event is kept and resume returns the step to ACTION_SUCCEEDED.
    for outcome, status, phases in (("SUCCEEDED", "HOLD", {"HELD"}), ("FAILED", "HOLD", {"HELD"})):
        path, tasks, _, enabled = _stores(tmp_path / outcome)
        store = CellJobStore(path)
        _create(store)
        store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
        transport = Transport()
        dispatcher = StepJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                                       deployment_profile="simulation", monotonic=Clock())
        dispatcher.dispatch_next()  # RUNNING, claims DISPATCHING
        tasks.close_dispatch_for_startup()
        restarted = CellJobStore(path)
        restarted.recover_after_startup()
        held = restarted.get("cell-mission-1")
        assert held["status"] == "HOLD" and held["reason"] == "SITE_AUTHORITY_CHANGED"
        assert {phase for _, _, phase in _claim_phases(path)} == {"UNKNOWN"}
        assert tasks.dispatch_control()["rearm_available"] is False
        transport.on_get = lambda grant, outcome=outcome: _receipt(grant, outcome, 20)
        StepJobDispatcher(restarted, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                          deployment_profile="simulation", monotonic=Clock()).dispatch_next()
        job = restarted.get("cell-mission-1")
        assert job["status"] == status
        assert {phase for _, _, phase in _claim_phases(path)} == phases
        assert tasks.dispatch_control()["rearm_available"] is True
        assert len(transport.submissions) == 1


def test_readback_also_accepts_dispatching_claims_on_a_hold_job(tmp_path):
    # 1c N1 defence in depth: a HOLD Job whose claims were left DISPATCHING is still read back.
    path, tasks, store, transport, dispatcher = _unknown_job(tmp_path)
    with store._connect() as connection:
        connection.execute("UPDATE fleet_action_claims SET phase='DISPATCHING'")
        connection.commit()
    assert [job["mission_id"] for job in store.next_unresolved()] == ["cell-mission-1"]
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 20)
    dispatcher.dispatch_next()
    assert store.get("cell-mission-1")["status"] == "ACTION_SUCCEEDED"


def test_a_site_stop_never_fails_on_claim_bookkeeping(tmp_path):
    """C4b 1c N2: one missing claim must not roll the stop latch back."""
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    with store._connect() as connection:
        connection.execute("DELETE FROM fleet_action_claims WHERE resource_key='pallet:pallet-1'")
        connection.commit()
    stopped = tasks.trip_stop_latch(actor_id="operator-1")
    assert stopped["dispatch_enabled"] is False
    job = store.get("cell-mission-1")
    assert job["status"] == "HOLD" and job["reason"] == "site_stop"
    assert any(event["event_type"] == "CLAIM_SET_INCOMPLETE_AT_STOP" for event in job["events"])
    assert {phase for _, _, phase in _claim_phases(path)} == {"HELD"}


def test_release_from_running_is_refused_entirely(tmp_path):
    # 1c P1: hold() never releases; release_before_send refuses a started step.
    from test_cell_job_store import _running
    _, _, store, _ = _running(tmp_path)
    with pytest.raises(ValueError):
        store.hold("cell-mission-1", reason="X", claim_phase=None, actor_id="op", event_key="k")
    with pytest.raises(MissionConflict):
        store.release_before_send("cell-mission-1", reason="X", event_key="k")
    assert store.get("cell-mission-1")["status"] == "RUNNING"


def test_a_late_success_after_a_stop_parks_the_job_and_resume_keeps_the_progress(tmp_path):
    """C4b 1c item 2a (rosy-a9): stop while RUNNING -> late SUCCEEDED -> rearm must not free claims."""
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = Transport()
    dispatcher = StepJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                                   deployment_profile="simulation", monotonic=Clock())
    dispatcher.dispatch_next()
    stopped = tasks.trip_stop_latch(actor_id="operator-1")
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 9)
    dispatcher.dispatch_next()
    job = store.get("cell-mission-1")
    assert (job["status"], job["reason"]) == ("HOLD", "site_stop")
    assert any(event["event_type"] == "CELL_STEP_ACTION_SUCCEEDED" for event in job["events"])
    assert {phase for _, _, phase in _claim_phases(path)} == {"HELD"}
    rearmed = tasks.rearm_dispatch(expected_generation=stopped["generation"], actor_id="operator-1")
    assert {phase for _, _, phase in _claim_phases(path)} == {"HELD"}
    grant = transport.submissions[0]
    with pytest.raises(MissionConflict):
        store.confirm_step_goal("cell-mission-1", step_index=0, action_id=grant.action_id,
                                attempt_id=grant.attempt_id, evidence=_goal(grant.action_id, grant.attempt_id, "g"))
    resumed = store.resume("cell-mission-1", actor_id="operator-2", expected_generation=rearmed["generation"])
    assert resumed["status"] == "ACTION_SUCCEEDED" and resumed["dispatch_generation"] == rearmed["generation"]
    store.confirm_step_goal("cell-mission-1", step_index=0, action_id=grant.action_id,
                            attempt_id=grant.attempt_id, evidence=_goal(grant.action_id, grant.attempt_id, "g"))
    dispatcher.dispatch_next()
    assert transport.submissions[-1].cell_transfer.step_index == 1
    assert transport.submissions[-1].dispatch_generation == rearmed["generation"]


def test_a_fence_change_after_progress_parks_claims_instead_of_releasing(tmp_path):
    """C4b 1c item 2b: the reproduced end state HOLD/step 1/claims [] must not happen."""
    from test_cell_job_store import _grant
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    ready = store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    store.start_step("cell-mission-1", step_index=0, action_id="action-0", attempt_id="attempt-0",
                     grant=_grant(ready, 0))
    store.record_action_result("cell-mission-1", step_index=0, event_id="e0", action_id="action-0",
                               attempt_id="attempt-0", outcome="SUCCEEDED", result={})
    step1 = store.confirm_step_goal("cell-mission-1", step_index=0, action_id="action-0",
                                    attempt_id="attempt-0", evidence=_goal("action-0", "attempt-0", "g0"))
    with store._connect() as connection:  # authority moves without the latch hook (another writer)
        connection.execute("UPDATE fleet_dispatch_control SET generation=generation+1")
        connection.commit()
    held = store.start_step("cell-mission-1", step_index=1, action_id="action-1", attempt_id="attempt-1",
                            grant=_grant(step1, 1))
    assert (held["status"], held["reason"], held["current_step_index"]) == (
        "HOLD", "FLEET_FENCE_CHANGED_BEFORE_SUBMISSION", 1)
    assert {phase for _, _, phase in _claim_phases(path)} == {"HELD"}


def test_release_before_send_frees_claims_only_without_progress(tmp_path):
    # rosy-a9 narrowing: a dedicated method replaces hold(not_submitted=True).
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    released = store.release_before_send("cell-mission-1", reason="ACTION_GRANT_INVALID", event_key="k")
    assert released["status"] == "HOLD" and _claim_phases(path) == []
    from test_cell_job_store import _running
    _, _, running_store, _ = _running(tmp_path / "running")
    with pytest.raises(MissionConflict):
        running_store.release_before_send("cell-mission-1", reason="X", event_key="k")
    with pytest.raises(TypeError):
        store.hold("cell-mission-1", reason="X", claim_phase=None, actor_id="op", event_key="k",
                   not_submitted=True)


def _later(seconds):
    from datetime import datetime, timedelta, timezone
    moment = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return lambda: moment


def test_not_found_needs_grant_expiry_plus_skew_and_no_receipt(tmp_path):
    """C4b 1c item 3 / N3: a 404 is 'never ran' only after expiry + skew and with no receipt."""
    from fleet.server.step_dispatcher import NOT_FOUND_SKEW_S
    path, tasks, store, transport, dispatcher = _unknown_job(tmp_path)  # submit lost: no receipt
    transport.on_get = lambda grant: None
    dispatcher.dispatch_next()  # grant still valid: a 404 may be a not-yet-journaled submit
    assert store.get("cell-mission-1")["reason"] == "LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN"
    assert {phase for _, _, phase in _claim_phases(path)} == {"UNKNOWN"}
    dispatcher.now = _later(15 + NOT_FOUND_SKEW_S + 1)
    dispatcher.reconcile("cell-mission-1")
    job = store.get("cell-mission-1")
    assert job["reason"] == "LOCAL_ACTION_NOT_FOUND_AFTER_SUBMIT"
    assert {phase for _, _, phase in _claim_phases(path)} == {"HELD"}


def test_a_404_after_a_device_receipt_never_reads_as_not_found(tmp_path):
    from fleet.server.step_dispatcher import NOT_FOUND_SKEW_S
    clock = Clock()
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = Transport()
    dispatcher = StepJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                                   deployment_profile="simulation", monotonic=clock)
    dispatcher.dispatch_next()  # ACCEPTED receipt recorded
    dispatcher.now = _later(15 + NOT_FOUND_SKEW_S + 1)
    transport.on_get = lambda grant: None  # e.g. the owner restarted on a new journal
    for _ in range(READBACK_FAILURE_LIMIT):
        dispatcher.dispatch_next()
        clock.t += 60
    job = store.get("cell-mission-1")
    assert job["status"] == "HOLD" and job["reason"] == "LOCAL_ACTION_READBACK_UNKNOWN"
    assert {phase for _, _, phase in _claim_phases(path)} == {"UNKNOWN"}


@pytest.mark.parametrize("receipt_seen, phases", [(False, {"HELD"}), (True, {"UNKNOWN"})])
def test_restart_then_404_resolves_only_without_a_receipt(tmp_path, receipt_seen, phases):
    # rosy-a9 1c item 1/3: restart while RUNNING, then the owner answers ACTION_NOT_FOUND. Without a
    # receipt (submit never reached the owner) it resolves HELD after expiry; with one it stays
    # UNKNOWN (an owner on a new journal; operator-attested resolve is wave 2).
    from fleet.server.step_dispatcher import NOT_FOUND_SKEW_S
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = Transport()
    if not receipt_seen:
        transport.submit = lambda grant: transport.submissions.append(grant) or (_ for _ in ()).throw(
            TimeoutError("lost"))
    clock = Clock()
    StepJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                      deployment_profile="simulation", monotonic=clock).dispatch_next()
    tasks.close_dispatch_for_startup()
    restarted = CellJobStore(path)
    restarted.recover_after_startup()
    transport.on_get = lambda grant: None
    dispatcher = StepJobDispatcher(restarted, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS,
                                   deployment_profile="simulation", monotonic=clock,
                                   now=_later(15 + NOT_FOUND_SKEW_S + 1))
    for _ in range(READBACK_FAILURE_LIMIT + 1):
        dispatcher.dispatch_next()
        clock.t += 60
    assert restarted.get("cell-mission-1")["status"] == "HOLD"
    assert {phase for _, _, phase in _claim_phases(path)} == phases


@pytest.mark.parametrize("journal_now, phases", [("journal-1", {"HELD"}), ("journal-2", {"UNKNOWN"}),
                                                 (None, {"UNKNOWN"})])
def test_not_found_also_needs_the_same_owner_journal(tmp_path, journal_now, phases):
    """C4b 1d item 3: a 404 from a fresh (or unknown) journal proves nothing; it stays UNKNOWN."""
    from fleet.server.step_dispatcher import NOT_FOUND_SKEW_S
    clock = Clock()
    path, tasks, store, transport, dispatcher = _unknown_job(tmp_path, clock=clock)  # submit lost
    transport.journal_id = journal_now
    transport.on_get = lambda grant: None
    dispatcher.now = _later(15 + NOT_FOUND_SKEW_S + 1)
    for _ in range(READBACK_FAILURE_LIMIT + 1):
        dispatcher.reconcile("cell-mission-1")
        clock.t += 60
    assert {phase for _, _, phase in _claim_phases(path)} == phases
