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
