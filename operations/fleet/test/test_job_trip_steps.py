"""D-763 7: a job's 운행 step is a trip in the step ledger (``job_trip_steps``), no separate motion record."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from fleet.routing.execute import plan_body
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.cell_job_store import CellJobStore
from fleet.server.dispatch_admission import reserve as reserve_claims
from fleet.server.job_trip_steps import KIND, JobTripSteps
from fleet.server.mission_store import MissionConflict
from fleet.server.step_action_kinds import dispatch_open, open_kinds, required_approval
from fleet.server.step_dispatcher import StepJobDispatcher
from fleet.server.trip_guard import install_trip_guard
from fleet.server.trip_ports import TripError
from fleet.traffic import rule_m
from test_approval_registry import _app, _post
from test_cell_job_store import _claim_phases, _stores
from test_step_dispatcher import REVISIONS, Transport
from test_trip_job_lease import CAPS, _Console
from test_trip_lease import LEASED_BOTH, _settle, _setup
from test_trip_runner import _arc, _free_map

R = "rosy_60"
TWO = [{"to": "B", "via": []}, {"to": "C", "via": []}]


class Rig:
    """A step ledger, the trip loop with a job lease and the adapter on one free map A -> B -> C."""

    def __init__(self, tmp_path, store=None, **lease):
        self.path, self.tasks, _, self.enabled = _stores(tmp_path) if store is None else store
        self.store = CellJobStore(self.path)
        self.runner, self.maps, self.ports = _setup(_free_map(), caps=LEASED_BOTH,
                                                    lease={"required": True, "holder": "site-a", **lease})
        self.runner.authority.enabled = True
        self.ports.at(_arc(self.maps, "ab:fwd"), 0.1)
        self.incidents, self.plans = [], []
        self.jobs = JobTripSteps(self.store, self.runner, plan=self.plan, caps=self.caps, incident=self.incident)

    async def caps(self, robot_id):
        return CAPS

    async def plan(self, robot_id, step, principal_id):
        graph, pose = self.maps.active()[2], self.ports.pose
        plan = plan_trip(graph, PlanRequest(map_version=self.maps.active()[0], start_pose=(pose.x, pose.y, pose.yaw),
                                            goal=step["to"]), self.maps.routing_config)
        plan_id = f"p{len(self.plans) + 1}"
        self.maps.record_plan(plan_id=plan_id, robot_id=robot_id, principal_id=principal_id,
                              map_version=plan.map_version, request={"to": step["to"], "via": []},
                              result={"plan": plan_body(plan)})
        self.plans.append(plan_id)
        return plan_id

    async def incident(self, robot_id, job_id, reason, detail):
        self.incidents.append((job_id, reason))

    def do(self, coro):
        async def go():
            result = await coro
            await _settle(self.runner)
            return result
        return asyncio.run(go())

    def ticks(self, n=1, dt=0.5, jobs=True):
        async def go():
            for _ in range(n):
                self.ports.now += dt
                await self.runner.tick()
                await _settle(self.runner)
                if jobs:
                    await self.jobs.tick()
                    await _settle(self.runner)
        asyncio.run(go())

    def create(self, steps=TWO, principal="kim"):
        return self.do(self.jobs.create(R, steps, principal))["mission_id"]

    def job(self, mission_id):
        return self.store.get(mission_id)

    def arrive(self, arc_id, s=0.97):
        self.ports.at(_arc(self.maps, arc_id), s)
        self.ticks()


# ---- the ledger takes the registered kinds (사용자 결정 2026-10-15) ------------------------------

def _step_row(connection, kind, mission_id="m-1", index=0):
    connection.execute("INSERT INTO fleet_cell_steps (mission_id, step_index, step_id, action_kind, step_json, status, "
                       "updated_at) VALUES (?, ?, ?, ?, '{}', 'WAITING', 'now')",
                       (mission_id, index, f"{mission_id}:{kind}:{index}", kind))


def _job_row(connection, mission_id="m-1"):
    connection.execute(
        "INSERT INTO fleet_cell_jobs (mission_id, proposal_principal_id, request_key, request_digest, job_id, "
        "workcell_id, instance_id, recipe_digest, cell_digest, process_artifact_digest, job_json, resources_json, "
        "ledger_markers_json, status, created_at, updated_at) VALUES (?, 'p', 'k', 'd', 'j', 'w', 'i', 'r', 'c', 'a', "
        "'{}', '[]', '[]', 'PROPOSED', 'now', 'now')", (mission_id,))


def test_the_step_ledger_accepts_exactly_the_registered_kinds(tmp_path):
    store = CellJobStore(tmp_path / "fleet.sqlite3")
    with store._connect() as connection:
        _job_row(connection)
        _step_row(connection, "CELL_TRANSFER")
        _step_row(connection, KIND, index=1)
        with pytest.raises(sqlite3.IntegrityError):
            _step_row(connection, "FETCH", index=2)


def test_an_existing_ledger_is_migrated_in_place_and_keeps_its_rows(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    CellJobStore(path)
    with sqlite3.connect(path) as connection:   # the schema before slice 7, with one step row
        connection.executescript(
            "DROP TABLE fleet_cell_steps; CREATE TABLE fleet_cell_steps (mission_id TEXT NOT NULL REFERENCES "
            "fleet_cell_jobs(mission_id), step_index INTEGER NOT NULL CHECK(step_index >= 0), step_id TEXT NOT NULL "
            "UNIQUE, action_kind TEXT NOT NULL CHECK(action_kind='CELL_TRANSFER'), step_json TEXT NOT NULL, status "
            "TEXT NOT NULL CHECK(status IN ('WAITING', 'READY', 'RUNNING', 'ACTION_SUCCEEDED', 'GOAL_CONFIRMED', "
            "'HOLD')), action_id TEXT, attempt_id TEXT, request_digest TEXT, grant_json TEXT, result_json TEXT, "
            "goal_evidence_json TEXT, reason TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(mission_id, step_index));")
        _job_row(connection)
        _step_row(connection, "CELL_TRANSFER")
        with pytest.raises(sqlite3.IntegrityError):
            _step_row(connection, KIND, index=1)
    store = CellJobStore(path)
    assert [s["action_kind"] for s in store.get("m-1")["steps"]] == ["CELL_TRANSFER"]
    with store._connect() as connection:
        _step_row(connection, KIND, index=1)
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "fleet_cell_steps_status" in indexes
    CellJobStore(path)  # a second open finds nothing to migrate


def test_the_kind_is_one_person_and_open_only_in_simulation():
    assert required_approval([KIND, KIND]) == "one_person"
    assert KIND in open_kinds("simulation") and not dispatch_open("production", KIND)


# ---- a job of trip steps -------------------------------------------------------------------------

def test_each_step_is_a_trip_under_the_jobs_one_lease_and_claim(tmp_path):
    rig = Rig(tmp_path)
    console = _Console()
    install_trip_guard(console, rig.runner, claims=rig.tasks.resource_claims)
    mid = rig.create()
    assert _claim_phases(rig.path) == [(mid, f"robot:{R}", "CLAIMED")]
    rig.ticks()
    step = rig.job(mid)["steps"][0]
    assert rig.job(mid)["status"] == step["status"] == "RUNNING" and step["action_id"] == "p1"
    trip = rig.runner.view("p1")
    assert trip["state"] in ("started", "running") and trip["started_by"] == "kim"
    lease_id = trip["lease"]["lease_id"]
    rig.arrive("ab:fwd")                                 # step 1 arrived: step 2 is READY, the robot is held
    assert rig.job(mid)["steps"][0]["status"] == "GOAL_CONFIRMED" and rig.job(mid)["current_step_index"] == 1
    assert console.trip_busy(R) and rig.runner.lease.job_of(R) == mid
    rig.ticks()
    assert rig.runner.view("p2")["lease"]["lease_id"] == lease_id     # the same lease, a new trip
    rig.arrive("bc:fwd")
    job = rig.job(mid)
    assert job["status"] == "GOAL_CONFIRMED" and [s["status"] for s in job["steps"]] == ["GOAL_CONFIRMED"] * 2
    assert _claim_phases(rig.path) == [] and rig.runner.lease.job_of(R) is None
    assert {p["lease_id"] for p in rig.ports.lease.puts} == {lease_id}
    assert [d[0] for d in rig.ports.lease.deletes] == [lease_id] and rig.incidents == []


def test_rule_m_sees_a_jobs_step_through_the_trip_view(tmp_path):
    rig = Rig(tmp_path)
    rig.create()
    rig.ticks()
    trips = {view["robot_id"]: view for view in rig.runner.open_trips()}
    verdict = rule_m.verdict(trip=trips.get(R), leg=rig.runner.leg_mode(R))
    assert verdict == {"state": "bounded", "motion": "goal", "reason": None}   # not idle


class _GoalConsole(_Console):
    async def goal(self, robot_id, *args, **kwargs):
        self.calls.append(("goal", robot_id, kwargs.get("lease_source")))


def test_a_jobs_motion_goes_out_as_trip_goals_never_operator_ones(tmp_path):
    rig = Rig(tmp_path)
    console = _GoalConsole()
    install_trip_guard(console, rig.runner)
    rig.runner._goal = lambda *args, **kwargs: console.goal(*args, trip=True, **kwargs)  # as app.py wires it
    rig.create()
    rig.ticks(3)
    goals = [call for call in console.calls if call[0] == "goal"]
    assert goals and {call[2] for call in goals} == {"trip"}


@pytest.mark.parametrize("end,reason", [
    (lambda rig: rig.runner.cancel("p1", "lee", "operator_cancel"), "operator_cancel"),
    (lambda rig: rig.runner._stop(rig.runner._live[R], "failed", "TRIP_GOAL_REFUSED"), "TRIP_GOAL_REFUSED"),
    (lambda rig: rig.runner._stop(rig.runner._live[R], "stopped", "stall"), "stall"),
])
def test_only_arrived_confirms_a_step_any_other_end_holds_with_the_trips_reason(tmp_path, end, reason):
    rig = Rig(tmp_path)
    mid = rig.create()
    rig.ticks()
    lease = rig.runner.view("p1")["lease"]
    rig.do(end(rig))
    rig.ticks()
    job = rig.job(mid)
    assert job["status"] == job["steps"][0]["status"] == "HOLD" and job["reason"] == reason
    assert rig.incidents == [(mid, reason)]                          # one case reaches a person
    assert _claim_phases(rig.path) == [(mid, f"robot:{R}", "HELD")] and rig.runner.lease.job_of(R) == mid
    assert lease["state"] == "lost" and [d[0] for d in rig.ports.lease.deletes] == [lease["lease_id"]]
    rig.ticks(10)                                                    # no retry, no reopen
    assert rig.plans == ["p1"] and rig.job(mid)["status"] == "HOLD"


def test_a_lease_lost_between_steps_holds_the_job_with_one_incident_and_never_drives_on(tmp_path):
    rig = Rig(tmp_path)
    mid = rig.create()
    rig.ticks()
    rig.arrive("ab:fwd")
    rig.ports.lease.down = True                          # Fleet loses the robot before step 2 is planned
    rig.ticks(18, jobs=False)
    job = rig.job(mid)
    assert job["status"] == "HOLD" and job["reason"] == "JOB_LEASE_LOST"
    rig.ticks()                                          # the case opens on the job loop's next pass
    assert rig.incidents == [(mid, "JOB_LEASE_LOST")]
    held = [e for e in job["events"] if e["event_type"] == "CELL_JOB_HELD"][-1]["detail"]
    assert held["lease_reason"] == "renew_timeout" and held["robot_state"] == "unconfirmed"   # never assumed IDLE
    rig.ports.lease.down = False                         # the link is back: nothing starts by itself
    puts = len(rig.ports.lease.puts)
    rig.ticks(6)
    assert rig.plans == ["p1"] and len(rig.ports.lease.puts) == puts and rig.job(mid)["status"] == "HOLD"


def test_resume_is_a_named_operators_new_lease_and_a_new_trip_after_its_start_checks(tmp_path):
    rig = Rig(tmp_path)
    mid = rig.create()
    rig.ticks()
    old = rig.runner.view("p1")["lease"]["lease_id"]
    rig.do(rig.runner.cancel("p1", "kim", "operator_cancel"))
    rig.ticks()
    rig.ports.at(_arc(rig.maps, "ab:fwd"), 0.2, state="DEGRADED")   # the robot as it is read back now
    rig.store.resume(mid, actor_id="lee", expected_generation=rig.enabled["generation"])
    rig.ticks()
    job = rig.job(mid)
    assert job["status"] == "HOLD" and job["reason"] == "TRIP_POSE_UNTRUSTED"   # the start check refused it
    assert rig.runner.open_trips() == [] and rig.incidents[-1] == (mid, "TRIP_POSE_UNTRUSTED")
    rig.ports.at(_arc(rig.maps, "ab:fwd"), 0.2)
    rig.store.resume(mid, actor_id="lee", expected_generation=rig.enabled["generation"])
    rig.ticks()
    trip = rig.runner.view(rig.plans[-1])
    assert trip["state"] in ("started", "running") and trip["started_by"] == "lee"
    assert trip["lease"]["lease_id"] != old and trip["lease"]["state"] == "held"


def test_after_a_fleet_restart_no_step_drives_by_itself(tmp_path):
    rig = Rig(tmp_path)
    mid = rig.create()
    rig.ticks()
    assert rig.job(mid)["status"] == "RUNNING"
    again = Rig(tmp_path, store=(rig.path, rig.tasks, None, rig.enabled))   # a new Fleet process on the same DB
    assert again.jobs.recover() == 1
    assert again.job(mid)["status"] == "HOLD" and again.job(mid)["reason"] == "FLEET_RESTARTED"
    again.ticks(6)
    assert again.plans == [] and again.ports.lease.puts == [] and again.runner.open_trips() == []
    assert again.incidents == [(mid, "FLEET_RESTARTED")]             # a restart HOLD reaches a person too
    assert _claim_phases(rig.path) == [(mid, f"robot:{R}", "HELD")]   # the job still holds the robot


def test_create_refuses_an_unbounded_robot_and_leaves_no_job(tmp_path):
    rig = Rig(tmp_path, required=False)
    with pytest.raises(TripError) as err:
        rig.create()
    assert (err.value.status, err.value.code) == (422, "LINK_UNBOUNDED_MOTION")
    with rig.store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_jobs").fetchone()[0] == 0


def test_create_refuses_a_robot_another_owner_claims_and_gives_the_lease_back(tmp_path):
    rig = Rig(tmp_path)
    with rig.store._connect() as connection:            # a navigate Task holds the robot
        assert reserve_claims(connection, owner_kind="task", owner_id="t-1", resources=[("robot", R)],
                              generation=rig.enabled["generation"], phase="CLAIMED")
    with pytest.raises(MissionConflict):
        rig.create()
    assert rig.runner.lease.job_of(R) is None and len(rig.ports.lease.deletes) == 1
    with rig.store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM fleet_cell_jobs").fetchone()[0] == 0


def test_the_device_dispatcher_leaves_trip_steps_to_the_trip_loop(tmp_path):
    rig = Rig(tmp_path)
    mid = rig.create()
    rig.ticks()
    dispatcher = StepJobDispatcher(rig.store, rig.tasks, Transport(), {"omx_01": "omx_01_control"}, REVISIONS,
                                   deployment_profile="simulation")
    assert dispatcher.dispatch_next() is None and rig.job(mid)["status"] == "RUNNING"


# ---- the route ------------------------------------------------------------------------------------

def _routes(app) -> set:
    return {getattr(route, "path", None) for route in app.routes}


def test_the_route_exists_only_in_the_simulation_profile(tmp_path, monkeypatch):
    for name in ("production", "simulation"):
        (tmp_path / name).mkdir()
    client, _ = _app(tmp_path / "production")
    assert "/api/fleet/trip-jobs" not in _routes(client.app) and getattr(client.app.state, "job_trips", None) is None
    import test_approval_registry
    original = test_approval_registry.create_app
    monkeypatch.setattr(test_approval_registry, "create_app",
                        lambda *a, **k: original(*a, deployment_profile="simulation", **k))
    client, _ = _app(tmp_path / "simulation")
    assert "/api/fleet/trip-jobs" in _routes(client.app) and client.app.state.job_trips is not None
    body = {"robot_id": "rosy_01", "steps": [{"to": "B"}]}
    assert _post(client, "/api/fleet/trip-jobs", "viewer-secret", body).status_code == 403
    refused = _post(client, "/api/fleet/trip-jobs", "op1-secret", body)      # no active site map here
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "TRIP_UNKNOWN_PLACE"
    assert _post(client, "/api/fleet/trip-jobs", "op1-secret", {**body, "robot_id": "rosy_99"}).status_code == 404


# ---- safety review 2026-10-15 ---------------------------------------------------------------------

def test_a_lost_job_lease_never_comes_back_without_a_new_approval(tmp_path):
    """Review 1: the loss is marked before the ledger HOLD lands; a tick in that gap must not re-take a lease."""
    rig = Rig(tmp_path)
    mid = rig.create()
    rig.ticks()
    rig.arrive("ab:fwd")
    hold = rig.runner.lease.jobs[R]
    hold.view["lease"].update(state="lost", reason="renew_timeout")  # lost, and the hook's HOLD has not landed
    puts = len(rig.ports.lease.puts)
    rig.ticks(3)
    job = rig.job(mid)
    assert job["status"] == "HOLD" and job["reason"] == "JOB_LEASE_LOST" and len(rig.ports.lease.puts) == puts
    assert rig.plans == ["p1"] and rig.incidents == [(mid, "JOB_LEASE_LOST")]


def test_a_lease_lost_while_steps_run_on_holds_once_and_never_drives_on(tmp_path):
    """Review 8: the job loop runs between the trip loop's ticks while the link is gone."""
    rig = Rig(tmp_path)
    mid = rig.create()
    rig.ticks()
    rig.arrive("ab:fwd")
    rig.ports.lease.down = True
    rig.ticks(18)
    job = rig.job(mid)
    assert job["status"] == "HOLD" and rig.incidents == [(mid, job["reason"])] and rig.runner.open_trips() == []
    plans = list(rig.plans)
    rig.ports.lease.down = False
    rig.ticks(6)
    assert rig.plans == plans and rig.job(mid)["status"] == "HOLD"


def test_an_estop_between_steps_holds_the_job_and_gives_its_lease_up(tmp_path):
    """Review 2: the E-stop closes trips; a job between its steps must not start the next one after it."""
    rig = Rig(tmp_path)
    console = _Console()
    install_trip_guard(console, rig.runner)
    rig.runner.traffic.signals_all_red = lambda: None
    mid = rig.create()
    rig.ticks()
    rig.arrive("ab:fwd")
    lease = rig.runner.lease.jobs[R].view["lease"]
    rig.do(console.estop_all())
    rig.ticks(3)
    assert lease["state"] == "lost" and rig.job(mid)["status"] == "HOLD" and rig.plans == ["p1"]
    assert rig.incidents == [(mid, "JOB_LEASE_LOST")]


def test_stop_job_ends_an_open_step_trip_first(tmp_path):
    """Review 5: giving the job lease up while its step trip runs ends that trip too."""
    rig = Rig(tmp_path)
    mid = rig.create()
    rig.ticks()
    rig.do(rig.runner.stop_job(R, "site_stop"))
    assert rig.runner.view("p1")["state"] == "canceled" and rig.runner.open_trips() == []
    rig.ticks()
    assert rig.job(mid)["status"] == "HOLD"


def test_a_site_stop_hold_between_steps_opens_a_case_and_gives_the_lease_up(tmp_path):
    """Review 4: the stop latch HOLDs a READY job outside this module; a person still hears of it."""
    rig = Rig(tmp_path)
    mid = rig.create()
    rig.ticks()
    rig.arrive("ab:fwd")
    rig.tasks.trip_stop_latch(actor_id="operator-1")
    rig.ticks()
    assert rig.job(mid)["status"] == "HOLD" and rig.runner.lease.jobs[R].view["lease"]["state"] == "lost"
    assert rig.incidents == [(mid, rig.job(mid)["reason"])]
    rig.ticks(3)
    assert len(rig.incidents) == 1 and rig.plans == ["p1"]
