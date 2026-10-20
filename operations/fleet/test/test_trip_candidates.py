"""D-836: candidate allocation stays behind existing trip lease and step claims."""
import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core_common.protocol.schemas import TripJobRequest
from fleet.server.trip_candidates import create_candidate_trip_job
from fleet.server.trip_ports import TripError
from test_job_trip_steps import Rig, R, TWO
from test_approval_registry import _app, _post


@pytest.mark.parametrize("body", [
    {"steps": [{"to": "B"}]},
    {"robot_id": R, "candidate_robot_ids": [R], "request_key": "k", "steps": [{"to": "B"}]},
    {"candidate_robot_ids": [], "request_key": "k", "steps": [{"to": "B"}]},
    {"candidate_robot_ids": [R, R], "request_key": "k", "steps": [{"to": "B"}]},
    {"candidate_robot_ids": ["bad id"], "request_key": "k", "steps": [{"to": "B"}]},
    {"candidate_robot_ids": [R], "steps": [{"to": "B"}]},
    {"candidate_robot_ids": [R], "request_key": " ", "steps": [{"to": "B"}]},
    {"robot_id": R, "request_key": "k", "steps": [{"to": "B"}]},
])
def test_invalid_candidate_envelopes_are_rejected(body):
    with pytest.raises(ValidationError):
        TripJobRequest(**body)


def test_existing_single_robot_request_is_unchanged():
    body = TripJobRequest(robot_id=R, steps=[{"to": "B"}])
    assert body.robot_id == R and body.candidate_robot_ids is None


def test_candidate_count_is_bounded():
    with pytest.raises(ValidationError):
        TripJobRequest(candidate_robot_ids=[f"r{i}" for i in range(9)], request_key="k", steps=[{"to": "B"}])


def allocate(rig, *, key="k", steps=TWO, principal="kim"):
    return rig.do(create_candidate_trip_job(rig.jobs, [R], steps, principal, key))


def test_pool_uses_existing_lease_claim_and_idempotent_ledger(tmp_path):
    rig = Rig(tmp_path)
    first = allocate(rig)
    second = allocate(rig)
    assert first["mission_id"] == second["mission_id"]
    assert first["workcell_id"] == R
    assert rig.runner.lease.jobs[R].view["job_id"] == first["mission_id"]
    assert len(rig.jobs.rows.ids(("READY",))) == 1
    with pytest.raises(TripError) as error:
        allocate(rig, steps=[{"to": "C", "via": []}])
    assert error.value.code == "TRIP_REQUEST_CONFLICT"


def test_same_key_after_restart_returns_hold_without_opening_new_lease(tmp_path):
    rig = Rig(tmp_path)
    first = allocate(rig)
    rig.jobs.recover()
    original = rig.runner.hold_job
    async def unexpected(*args, **kwargs):
        pytest.fail("a replay must not take a new lease")
    rig.runner.hold_job = unexpected
    assert allocate(rig)["status"] == "HOLD"
    assert allocate(rig)["mission_id"] == first["mission_id"]
    rig.runner.hold_job = original


def test_concurrent_same_request_creates_one_job(tmp_path):
    rig = Rig(tmp_path)
    async def go():
        return await asyncio.gather(*(create_candidate_trip_job(rig.jobs, [R], TWO, "kim", "k") for _ in range(2)))
    results = rig.do(go())
    assert results[0]["mission_id"] == results[1]["mission_id"]
    assert len(rig.jobs.rows.ids(("READY",))) == 1


def test_other_principal_does_not_receive_another_principals_job(tmp_path):
    rig = Rig(tmp_path)
    allocate(rig)
    with pytest.raises(TripError) as error:
        allocate(rig, principal="lee")
    assert error.value.code == "TRIP_CANDIDATES_BUSY"


def test_only_known_busy_refusal_can_try_next_candidate(monkeypatch):
    from fleet.server import trip_candidates
    calls = []
    jobs = SimpleNamespace(candidate_lock=asyncio.Lock())
    jobs.rows = SimpleNamespace(find_request=lambda *args: None)
    async def create(jobs, robot, steps, principal, **kwargs):
        calls.append(robot)
        if robot == "busy":
            raise TripError(409, "TRIP_ROBOT_BUSY")
        return {"mission_id": "m", "workcell_id": robot}
    monkeypatch.setattr(trip_candidates, "create_trip_job", create)
    result = asyncio.run(create_candidate_trip_job(jobs, ["busy", "free"], TWO, "kim", "k"))
    assert calls == ["busy", "free"] and result["workcell_id"] == "free"


@pytest.mark.parametrize("code", ["JOB_ESTOP", "LINK_UNBOUNDED_MOTION", "TRIP_LEASE_LOST"])
def test_unknown_or_unsafe_refusal_never_fails_over(monkeypatch, code):
    from fleet.server import trip_candidates
    calls = []
    jobs = SimpleNamespace(candidate_lock=asyncio.Lock(), rows=SimpleNamespace(find_request=lambda *args: None))
    async def create(jobs, robot, *args, **kwargs):
        calls.append(robot)
        raise TripError(409, code)
    monkeypatch.setattr(trip_candidates, "create_trip_job", create)
    with pytest.raises(TripError) as error:
        asyncio.run(create_candidate_trip_job(jobs, ["first", "second"], TWO, "kim", "k"))
    assert error.value.code == code and calls == ["first"]


def test_database_failure_releases_acquired_lease(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(rig.jobs.rows, "create", fail)
    with pytest.raises(RuntimeError):
        allocate(rig)
    assert R not in rig.runner.lease.jobs


def test_stop_latch_is_not_bypassed(tmp_path):
    rig = Rig(tmp_path)
    rig.tasks.trip_stop_latch(actor_id="kim", reason="test")
    from fleet.server.mission_store import MissionConflict
    with pytest.raises(MissionConflict):
        allocate(rig)
    assert R not in rig.runner.lease.jobs


def test_route_preserves_identity_profile_and_known_candidate_checks(tmp_path, monkeypatch):
    import test_approval_registry
    original = test_approval_registry.create_app
    monkeypatch.setattr(test_approval_registry, "create_app",
                        lambda *a, **k: original(*a, deployment_profile="simulation", **k))
    client, _ = _app(tmp_path)
    body = {"candidate_robot_ids": ["rosy_01"], "request_key": "k", "steps": [{"to": "B"}]}
    assert _post(client, "/api/fleet/trip-jobs", "viewer-secret", body).status_code == 403
    assert _post(client, "/api/fleet/trip-jobs", "op1-secret", {**body, "candidate_robot_ids": ["unknown"]}).status_code == 404
    assert _post(client, "/api/fleet/trip-jobs", "op1-secret", body).json()["detail"]["code"] == "TRIP_UNKNOWN_PLACE"
