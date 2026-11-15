"""D-1029: an approved station recovery request starts a charge return trip (``fleet.station_recovery.dispatch``).

Fakes only: the trip planner, the runner (its lease, start and view) and the robot's person request client.
"""
import asyncio
from types import SimpleNamespace

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from fleet.charge_bays import ChargeBays, RobotView
from fleet.server.auth.site_auth import build_role_guards
from fleet.server.station_recovery_routes import install_station_recovery_routes
from fleet.server.trip_ports import TripError
from fleet.traffic.trip_lease import TripLease
from test_station_recovery import BAYS, LOCALIZED, OPERATOR, Recorder, row


class Runner:
    def __init__(self, lease_required=True, refuse=None):
        self.lease, self.refuse, self.started, self.state = SimpleNamespace(required=lease_required), refuse, [], "running"

    async def start(self, plan_id, by, purpose=None):
        if self.refuse:
            raise self.refuse
        self.started.append((plan_id, by, purpose))
        return {"trip_id": plan_id}

    def view(self, trip_id):
        return {"state": self.state, "reason": "lease_lost" if self.state == "stopped" else None}


class Client:
    def __init__(self):
        self.put = []

    async def person_request_put(self, body):
        self.put.append(body)


def make(rows, *, dispatch=True, runner=None, plan_error=None, now=None):
    app = FastAPI()
    app.state.site_maps = recorder = Recorder()
    app.state.charge_bays = ChargeBays()
    app.state.map_pose = SimpleNamespace(arbitrated_pose=lambda robot_id: LOCALIZED)
    client = Client()
    app.state.console = SimpleNamespace(clients={"r1": client})
    app.state.trip_runner = runner = runner or Runner()
    asked = []

    async def trip_plan(robot_id, body, by):
        asked.append((robot_id, body.to))
        if plan_error:
            raise plan_error
        return {"plan_id": "plan1"}
    app.state.trip_plan = trip_plan
    views = [RobotView(r["robot_id"], r["online"], 18.0, None, (5.0, 5.0), False) for r in rows]

    def authorize(request: Request):
        return OPERATOR
    guards = build_role_guards(authorize, {"t": OPERATOR})

    async def gathered():
        return {"robots": rows}

    async def bay_inputs():
        return (7, {}), views, BAYS
    install_station_recovery_routes(app, {"enabled": True, "dispatch": dispatch},
                                    ([Depends(guards[0])], guards[2], guards[3]), gathered, bay_inputs,
                                    monotonic=(lambda: now[0]) if now else __import__("time").monotonic)
    return TestClient(app), app, SimpleNamespace(recorder=recorder, runner=runner, asked=asked, robot=client)


def step(app):
    asyncio.run(app.state.station_recovery_auto())


def test_dispatch_off_is_todays_approval_that_starts_nothing():
    client, app, w = make([row()], dispatch=False)
    body = client.post("/api/fleet/station-recovery/r1/approve").json()
    assert body["started"] is False and body["reason"] == "not_implemented"
    assert w.runner.started == [] and client.get("/api/fleet/station-recovery").json()["dispatch"] is False


def test_approval_starts_one_trip_to_the_bay_with_the_charge_return_purpose():
    client, app, w = make([row()])
    body = client.post("/api/fleet/station-recovery/r1/approve").json()
    assert (body["started"], body["reason"]) == (True, None)
    assert w.asked == [("r1", "C1")] and w.runner.started == [("plan1", "alice", "charge_return")]
    listed = client.get("/api/fleet/station-recovery").json()
    assert listed["dispatch"] is True and listed["requests"][0]["return"]["state"] == "returning"
    client.post("/api/fleet/station-recovery/r1/approve")   # busy trip: never a second one
    assert len(w.runner.started) == 1


def test_arrival_asks_a_person_to_plug_in_and_the_trip_end_is_final():
    client, app, w = make([row()])
    client.post("/api/fleet/station-recovery/r1/approve")
    step(app)   # still running: nothing yet
    assert w.robot.put == []
    w.runner.state = "arrived"
    step(app)
    assert [p["text"] for p in w.robot.put] == ["Charge me: plug in at bay C1"] and w.robot.put[0]["kind"] == "plug_charger"
    assert w.recorder.events[-1][2]["state"] == "arrived"


def test_no_measured_pose_means_no_trip_and_a_recorded_reason():
    err = HTTPException(422, detail={"code": "TRIP_POSE_UNTRUSTED", "detail": {}})
    client, app, w = make([row()], plan_error=err)
    body = client.post("/api/fleet/station-recovery/r1/approve").json()
    assert (body["started"], body["reason"]) == (False, "TRIP_POSE_UNTRUSTED")
    assert w.runner.started == [] and w.recorder.events[-1][2]["reason"] == "TRIP_POSE_UNTRUSTED"


def test_a_refused_start_and_a_lease_less_site_do_not_move_the_robot():
    client, _, w = make([row()], runner=Runner(refuse=TripError(409, "TRIP_ROBOT_BUSY")))
    assert client.post("/api/fleet/station-recovery/r1/approve").json()["reason"] == "TRIP_ROBOT_BUSY"
    client, _, w = make([row()], runner=Runner(lease_required=False))
    assert client.post("/api/fleet/station-recovery/r1/approve").json()["reason"] == "trip_lease_off"
    assert w.runner.started == [] and w.asked == []


def test_a_trip_that_ends_otherwise_is_a_failure_that_is_not_retried_at_once():
    now = [0.0]
    client, app, w = make([row()], now=now)
    client.post("/api/fleet/station-recovery/r1/approve")
    w.runner.state = "stopped"
    step(app)
    assert w.recorder.events[-1][2]["reason"] == "lease_lost" and w.robot.put == []
    now[0] += 10
    step(app)   # approved afresh by the cadence, but the failed return holds for RETRY_S
    assert len(w.runner.started) == 1


def test_the_lease_body_carries_the_purpose_only_when_set():
    lease = TripLease(None, lambda: 0.0, 1.0)
    view = {"trip_id": "t", "started_by": "op"}
    assert "purpose" not in lease._body("l", view)
    assert lease._body("l", {**view, "purpose": "charge_return"})["purpose"] == "charge_return"


def test_a_core_that_does_not_echo_the_purpose_is_refused_and_released():
    # Review 2026-11-14: an older CORE ignores ``purpose``; the return would run with no cap and no deferral.
    released, answers = [], {"purpose": None}

    async def put(robot_id, body):
        return {"trip_lease": {"lease_id": body["lease_id"], "purpose": answers["purpose"]}}
    lease = TripLease(SimpleNamespace(trip_lease=put), lambda: 0.0, 1.0, required=True)
    lease._release_later = lambda robot_id, lease_id: released.append(lease_id)
    caps = SimpleNamespace(trip_lease=True)
    view = {"trip_id": "t", "started_by": "op", "purpose": "charge_return"}
    try:
        asyncio.run(lease.open("r1", view, caps))
        raise AssertionError("an un-echoed purpose must refuse")
    except TripError as exc:
        assert exc.code == "TRIP_LEASE_PURPOSE_UNSUPPORTED" and len(released) == 1
    answers["purpose"] = "charge_return"
    assert asyncio.run(lease.open("r1", view, caps))["state"] == "held"


def test_two_approvals_at_once_start_one_return():
    # Review 2026-11-14: the auto tick and a person's approve must not both pass the check before awaiting.
    from fleet.server.station_recovery_dispatch import ChargeReturns
    runner, gate = Runner(), asyncio.Event()

    async def trip_plan(robot_id, body, by):
        await gate.wait()
        return {"plan_id": "plan1"}
    app = SimpleNamespace(state=SimpleNamespace(trip_runner=runner, trip_plan=trip_plan, site_maps=Recorder()))
    returns = ChargeReturns(app, None)
    answer = {"robot_id": "r1", "bay": "bay_1"}

    async def race():
        first = asyncio.create_task(returns.start(answer, "fleet:auto"))
        await asyncio.sleep(0)
        second = await returns.start(answer, "op")
        gate.set()
        return second, await first
    second, first = asyncio.run(race())
    assert second["state"] == first["state"] == "returning"
    assert len(runner.started) == 1
