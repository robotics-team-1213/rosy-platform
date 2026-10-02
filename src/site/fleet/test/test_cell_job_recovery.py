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
    for outcome, status, phases in (("SUCCEEDED", "ACTION_SUCCEEDED", {"CLAIMED"}),
                                    ("FAILED", "HOLD", {"HELD"})):
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
    # 1c P1: release (claim_phase=None) only from READY, even with not_submitted=True.
    from test_cell_job_store import _running
    _, _, store, _ = _running(tmp_path)
    with pytest.raises(MissionConflict):
        store.hold("cell-mission-1", reason="X", claim_phase=None, actor_id="op", event_key="k",
                   not_submitted=True)
    assert store.get("cell-mission-1")["status"] == "RUNNING"
