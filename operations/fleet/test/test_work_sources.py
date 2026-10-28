"""D-763 slice 4: trip and Cell Job rows in the work read, the 승인 대기 owner scope and the 새 작업 kinds."""

from types import SimpleNamespace

from test_approval_registry import _app, _generation, _post, _resolved
from test_cell_job_api import _candidate as _cell_candidate
from test_mission_api import _candidate as _er2_candidate

CAPS = {"controls": {"items": [{"kind": "base_velocity", "robot_kind": "pinky", "drive_modes": ["lane"],
                                "trip_max_linear": 0.2}]}}


def _work(client, token):
    response = client.get("/api/fleet/work", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    return response.json()


def _trip(client, trip_id, state, at, wait=None, reason=None):
    view = {"trip_id": trip_id, "plan_id": trip_id, "robot_id": "rosy_01", "started_by": "operator-1",
            "state": state, "reason": reason, "created_at": at, "updated_at": at}
    client.app.state.site_maps.put_trip({**view, **({"wait": wait} if wait else {})})


def _rows(body, source):
    return {row["source_id"]: row for row in body["rows"] if row["source"] == source}


def test_trip_rows_carry_state_robot_reason_and_the_wait_answer(tmp_path):
    client, _ = _app(tmp_path)
    _trip(client, "t-wait", "running", 1_000.0, {"reason": "signal", "since": 3.0, "waiting": True,
                                                  "bound_s": 20.0, "over_bound": False})
    _trip(client, "t-over", "running", 1_001.0, {"reason": "authority", "waiting": False, "bound_s": 8.0,
                                                  "over_bound": True})
    _trip(client, "t-stop", "stopped", 1_002.0, {"reason": "signal", "waiting": False, "bound_s": 20.0,
                                                  "over_bound": True}, reason="stall")  # kept from its last tick
    _trip(client, "t-done", "arrived", 1_003.0)
    body = _work(client, "viewer-secret")
    trips = _rows(body, "trip")
    assert set(trips) == {"t-wait", "t-over", "t-stop", "t-done"}
    assert trips["t-wait"]["wait"] == {"reason": "signal", "waiting": True, "bound_s": 20.0, "over_bound": False}
    assert [trips[key]["visible_state"] for key in ("t-wait", "t-over", "t-stop", "t-done")] == [
        "waiting", "in_progress", "intervention", "ended"]  # past the bound: a warning, not 개입 (rev 2 Q7)
    assert trips["t-stop"]["reason"] == "stall" and trips["t-stop"]["device_id"] == "rosy_01"
    assert trips["t-stop"]["wait"] is None and trips["t-over"]["wait"]["over_bound"] is True  # only an open trip waits
    assert trips["t-done"]["action_kind"] == "trip" and trips["t-done"]["updated_at"].startswith("1970-01-01T00:16:43")
    assert "since" not in str(trips["t-wait"]["wait"]) and "operator-1" not in str(trips)
    assert [row["source_id"] for row in body["rows"]][:2] == ["t-done", "t-stop"]


def test_trip_truncation_is_reported_per_source(tmp_path):
    client, _ = _app(tmp_path)
    for index in range(3):
        _trip(client, f"t{index}", "arrived", 10.0 + index)
    body = client.get("/api/fleet/work?limit=2", headers={"Authorization": "Bearer viewer-secret"}).json()
    assert list(_rows(body, "trip")) == ["t2", "t1"] and body["truncated_sources"] == ["trip"]


def test_pending_cell_job_scope_viewer_operator_proposer_and_other_operator(tmp_path):
    client, tasks = _app(tmp_path)
    job = _resolved(client, "cell-secret", _cell_candidate())
    viewer, proposer = _work(client, "viewer-secret"), _work(client, "cell-secret")
    first, second = _work(client, "op1-secret"), _work(client, "op2-secret")
    assert _rows(viewer, "cell_job") == {} and viewer["cell_jobs_available"] is True
    for body in (proposer, first, second):
        row = _rows(body, "cell_job")[job]
        assert (row["status"], row["visible_state"], row["approval"]) == ("PROPOSED", "approval_pending", "two_person")
        assert (row["action_kind"], row["workcell_id"], row["device_id"]) == ("CELL_TRANSFER", "omx_01", "omx_01_control")
    # rev 2 Q6: the summary row never carries the proposer's identity, plan or candidate
    for body in (first, second):
        text = str(body)
        assert "cell-service" not in text and "candidate" not in text and "recipe" not in text
    rejected = _post(client, f"/api/fleet/missions/{job}/reject", "op1-secret",
                     {"expected_generation": _generation(tasks)})
    assert rejected.status_code == 200, rejected.text
    ended = _rows(_work(client, "op2-secret"), "cell_job")[job]
    assert (ended["status"], ended["visible_state"], ended["approval"]) == ("HOLD", "ended", None)
    assert _rows(_work(client, "viewer-secret"), "cell_job") == {}


def test_unnamed_operator_sees_no_pending_cell_job_but_its_later_rows(tmp_path):
    named, _ = _app(tmp_path)
    job = _resolved(named, "cell-secret", _cell_candidate())
    shared, tasks = _app(tmp_path, named=False, console_token="shared-secret")
    assert _rows(_work(shared, "shared-secret"), "cell_job") == {}
    assert _post(named, f"/api/fleet/missions/{job}/reject", "op1-secret",
                 {"expected_generation": _generation(tasks)}).status_code == 200
    assert _rows(_work(shared, "shared-secret"), "cell_job")[job]["visible_state"] == "ended"


def test_legacy_mission_stays_owner_only_with_its_registry_approval(tmp_path):
    client, _ = _app(tmp_path)
    mission = _resolved(client, "op1-secret", _er2_candidate())
    own = _rows(_work(client, "op1-secret"), "mission")[mission]
    assert (own["visible_state"], own["approval"]) == ("approval_pending", "proposer_only")
    assert _rows(_work(client, "op2-secret"), "mission") == {}


def test_unconfigured_cell_ledger_reads_as_unavailable(tmp_path):
    client, _ = _app(tmp_path)
    client.app.state.cell_job_store = None
    body = _work(client, "op1-secret")
    assert body["cell_jobs_available"] is False and _rows(body, "cell_job") == {}
    assert body["tasks_available"] and body["missions_available"]


def test_kinds_list_only_what_runs_here(tmp_path, monkeypatch):
    client, _ = _app(tmp_path)
    state = client.app.state
    assert _work(client, "viewer-secret")["kinds"] == []  # no active site map

    async def caps(robot_id):
        return answer[robot_id]

    answer = {"rosy_01": None}
    monkeypatch.setattr(state.console, "_shown_capabilities", caps)
    places = SimpleNamespace(places=[{"place_id": "A"}])
    monkeypatch.setattr(state.site_maps, "active", lambda: (4, places, None, None))
    assert _work(client, "viewer-secret")["kinds"] == []  # places, but no robot reports trip caps
    answer["rosy_01"] = CAPS
    assert _work(client, "viewer-secret")["kinds"] == ["trip"]
    monkeypatch.setattr(state.site_maps, "active", lambda: (5, SimpleNamespace(places=[]), None, None))
    assert _work(client, "viewer-secret")["kinds"] == []  # a capable robot, but no place

    # This app is private to the test; pytest 9.2 cannot restore State's dynamic attributes.
    state.cell_job_dispatcher = object()
    state.omx_instances = {"omx_01": "omx_01_control"}
    assert _work(client, "viewer-secret")["kinds"] == []  # production profile: Cell dispatch is closed
    state.deployment_profile = "simulation"
    assert _work(client, "viewer-secret")["kinds"] == ["CELL_TRANSFER"]
    state.omx_instances = {}
    assert _work(client, "viewer-secret")["kinds"] == []  # no capable device


def test_ledger_and_stored_trip_reads_run_off_the_event_loop(tmp_path, monkeypatch):
    """The trip runner's timing, lease renewal and stall clock share the event loop: no SQLite read on it."""
    import asyncio
    from fleet.server import work_routes

    client, _ = _app(tmp_path)
    _resolved(client, "cell-secret", _cell_candidate())
    _trip(client, "t1", "arrived", 10.0)
    on_loop = []

    def watched(read):
        def call(*args, **kwargs):
            try:
                asyncio.get_running_loop()
                on_loop.append(read)
            except RuntimeError:  # a worker thread has no running loop
                pass
            return read(*args, **kwargs)
        return call

    monkeypatch.setattr(work_routes, "work_summaries", watched(work_routes.work_summaries))
    monkeypatch.setattr(client.app.state.site_maps, "trips", watched(client.app.state.site_maps.trips))
    body = _work(client, "op1-secret")
    assert _rows(body, "trip") and _rows(body, "cell_job") and _rows(body, "task") == {}
    assert on_loop == []


def _detail(client, job, token):
    return client.get(f"/api/fleet/cell-jobs/{job}", headers={"Authorization": f"Bearer {token}"})


def test_cell_job_detail_follows_the_list_scope_and_never_shows_the_proposer(tmp_path):
    """Review blocker: the row's detail read may not widen the list's scope or leak the proposer (rev 2 Q6)."""
    named, _ = _app(tmp_path)
    job = _resolved(named, "cell-secret", _cell_candidate())
    shared, tasks = _app(tmp_path, named=False, console_token="shared-secret")
    own = _detail(named, job, "cell-secret")
    assert own.status_code == 200 and own.json()["job"]["proposal_principal_id"] == "cell-service"
    other = _detail(named, job, "op1-secret")
    assert other.status_code == 200, other.text
    assert "proposal_principal_id" not in other.json()["job"] and "cell-service" not in other.text
    assert other.json()["job"]["steps"]  # the plan stays: the detail scope is otherwise unchanged
    assert _detail(named, job, "viewer-secret").status_code == 404
    assert _detail(shared, job, "shared-secret").status_code == 404  # an unnamed operator: not another's PROPOSED job
    assert _post(named, f"/api/fleet/missions/{job}/reject", "op1-secret",
                 {"expected_generation": _generation(tasks)}).status_code == 200
    later = _detail(shared, job, "shared-secret")
    assert later.status_code == 200 and "cell-service" not in later.text
    assert _detail(named, job, "viewer-secret").status_code == 404


def _proposal(client, proposal_id, token):
    return client.get(f"/api/fleet/proposals/{proposal_id}", headers={"Authorization": f"Bearer {token}"})


def test_proposal_read_follows_the_cell_job_detail_scope_and_never_shows_the_proposer(tmp_path):
    """Slice 4 review: the proposal read is a second door to the same Cell Job; same scope, same redaction."""
    named, _ = _app(tmp_path)
    job = _resolved(named, "cell-secret", _cell_candidate())
    unresolved = _post(named, "/api/fleet/proposals", "cell-secret", {
        "request_key": "req-2", "workcell_id": "omx_01", "instance_id": "omx_01_control",
        "candidate": _cell_candidate()}).json()["proposal"]["proposal_id"]
    shared, tasks = _app(tmp_path, named=False, console_token="shared-secret")
    own = _proposal(named, job, "cell-secret")
    assert own.status_code == 200 and own.json()["mission"]["proposal_principal_id"] == "cell-service"
    for proposal_id in (job, unresolved):
        other = _proposal(named, proposal_id, "op1-secret")
        assert other.status_code == 200, other.text
        assert "proposal_principal_id" not in str(other.json()["mission"]) and "cell-service" not in other.text
        assert _proposal(named, proposal_id, "viewer-secret").status_code == 404
        assert _proposal(shared, proposal_id, "shared-secret").status_code == 404  # unnamed: not another's PROPOSED
    assert _proposal(named, job, "op1-secret").json()["mission"]["steps"]
    assert _post(named, f"/api/fleet/missions/{job}/reject", "op1-secret",
                 {"expected_generation": _generation(tasks)}).status_code == 200
    later = _proposal(shared, job, "shared-secret")
    assert later.status_code == 200 and "cell-service" not in later.text
    assert _proposal(named, job, "viewer-secret").status_code == 404
    assert _proposal(shared, unresolved, "shared-secret").status_code == 404
    mission = _resolved(named, "op1-secret", _er2_candidate(), key="req-3")
    assert _proposal(named, mission, "op1-secret").status_code == 200
    assert _proposal(named, mission, "op2-secret").status_code == 404  # a legacy Mission stays owner-only


def test_forbidden_reads_look_like_missing_and_a_proposer_event_reads_as_proposer(tmp_path):
    """Security review: a hidden id answers as a missing one; the proposer's own event never names it."""
    named, tasks = _app(tmp_path)
    job = _resolved(named, "cell-secret", _cell_candidate())
    missing = "00000000-0000-4000-8000-000000000000"
    for read in (_proposal, _detail):
        hidden, absent = read(named, job, "viewer-secret"), read(named, missing, "viewer-secret")
        assert (hidden.status_code, hidden.json()) == (absent.status_code, absent.json())
    named.app.state.cell_job_store.cancel(job, actor_id="cell-service", decision="WITHDRAWN_BY_PROPOSER",
                                           expected_generation=_generation(tasks))
    for body in (_proposal(named, job, "op1-secret").json()["mission"], _detail(named, job, "op1-secret").json()["job"]):
        assert "proposer" in {event["actor_id"] for event in body["events"]} and "cell-service" not in str(body)
