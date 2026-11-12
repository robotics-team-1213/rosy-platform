from __future__ import annotations

from test_trip_runner import (
    logging, time, pytest, FakeRobot, HubError, FleetConsole, SiteMapStore, HttpLaneJunction,
    TripError, RobotEndpoint, OPERATOR, VIEWER, BOTH, Ports, _free_map, _setup,
    _plan, _arc, run, _code, _ticks, _app,
)


class _TripOf:
    """A runner stand-in for the guard: ``robot`` is on a trip."""

    def __init__(self, robot):
        self.robot, self.canceled = robot, []

    def robot_busy(self, robot_id):
        return robot_id == self.robot

    def open_trips(self):
        return [{"robot_id": self.robot}] if self.robot else []

    async def cancel_robot(self, robot_id, reason):
        self.canceled.append((robot_id, reason))


def _guarded(*ids, trip="b"):
    from fleet.server.trip_guard import install_trip_guard

    robots = [FakeRobot(robot_id) for robot_id in ids]
    console = FleetConsole([RobotEndpoint(r.robot_id, "http://x", "t") for r in robots], robots)
    runner = _TripOf(trip)
    install_trip_guard(console, runner)
    return console, runner, robots


def test_formation_refuses_a_robot_on_a_trip():
    console, _runner, _robots = _guarded("a", "b")
    with pytest.raises(HubError) as err:
        run(console.formation_start("a"))
    assert err.value.code == "TRIP_ROBOT_BUSY"


@pytest.mark.parametrize("owner", ["trip", "formation"])
def test_goal_rechecks_owner_after_localization_await(owner):
    console, runner, robots = _guarded("a", trip=None)
    robot = robots[0]
    state = robot.state

    async def changed_state():
        result = await state()
        if owner == "trip":
            runner.robot = "a"
        else:
            console._formation_members = lambda: {"a"}
        return result

    robot.state = changed_state
    with pytest.raises(HubError) as error:
        run(console.goal("a", 1.0, 0.0))
    assert error.value.code == ("TRIP_ROBOT_BUSY" if owner == "trip" else "FORMATION_ACTIVE")
    assert not [call for call in robot.calls if call[0] == "navigation_goal"]


def test_bay_rechecks_trip_owner_after_capability_await():
    console, runner, robots = _guarded("a", trip=None)
    robot = robots[0]
    capabilities = robot.capabilities

    async def changed_capabilities():
        result = await capabilities()
        runner.robot = "a"
        return result

    robot.capabilities = changed_capabilities
    with pytest.raises(HubError, match="running trip"):
        run(console._send_to_bay("a", (1.0, 1.0), "b"))
    assert not [call for call in robot.calls if call[0] == "navigation_goal"]


def test_trip_rechecks_existing_motion_after_start_pose_await():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    engaged = [None]
    runner._engaged = lambda robot_id: engaged[0]
    start_pose = runner._start_pose

    async def changed_pose(*args, **kwargs):
        result = await start_pose(*args, **kwargs)
        engaged[0] = "goal"
        return result

    runner._start_pose = changed_pose
    assert _code(runner.start("p1", "bob")) == "TRIP_ROBOT_BUSY"
    assert runner.view("p1") is None


def test_goal_in_flight_counts_as_engaged_until_its_receipt_arrives():
    from fleet.server.trip_guard import engaged

    console, _, robots = _guarded("a", trip=None)
    robot = robots[0]
    observations = []

    async def accept(*args, **kwargs):
        observations.append(engaged(console, "a"))
        return {"accepted": True}

    robot.navigation_goal = accept
    run(console.goal("a", 1.0, 0.0))
    assert observations == ["goal_pending"]


@pytest.mark.parametrize("stop", ["estop", "cancel"])
def test_stop_during_trip_start_prevents_opening_a_late_trip(stop):
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    start_pose = runner._start_pose

    async def stopped_pose(*args, **kwargs):
        result = await start_pose(*args, **kwargs)
        if stop == "estop":
            runner.close_all("operator_estop")
        else:
            await runner.cancel_robot("rosy_60", "operator_cancel")
        return result

    runner._start_pose = stopped_pose
    with pytest.raises(TripError):
        run(runner.start("p1", "bob"))
    assert runner.view("p1") is None


def test_a_trip_robot_never_yields_and_is_not_a_reassignment_candidate(monkeypatch):
    import fleet.server.console as console_module

    console, _runner, robots = _guarded("a", "b", "c")
    monkeypatch.setattr(console_module.bays, "best_bay", lambda *args, **kwargs: (2.0, 2.0))

    async def no_map():
        return {}

    console.map = no_map
    console._pose_of = lambda robot_id: (0.5, 0.0)
    run(console.snapshot())  # the frames must be known (state read) before room is made
    result = run(console._make_room("a", 1.0, 0.0, 0.0, [(0.0, 0.0), (1.0, 0.0)], ["b", "c"]))
    assert result["no_space"] == ["b"] and result["yielding"] == ["c"]
    assert not [c for c in robots[1].calls if c[0] == "navigation_goal"]
    rows = [{"robot_id": rid, "online": True, "state": {"capabilities_degraded": rid == "a"}} for rid in "abc"]
    console._goals["a"] = {"x": 1.0, "y": 0.0, "yaw": 0.0}
    console._queued.pop("c", None)
    console._goals.pop("c", None)
    console._yielding.clear()
    run(console._run_traffic(rows))
    assert "b" not in console._queued and "b" not in console._goals
    assert (console._queued.get("c") or console._goals.get("c"))["x"] == 1.0  # c took the mission


def test_line_follow_off_stops_and_cancels_the_trip_other_modes_are_refused():
    console, runner, robots = _guarded("a", "b")
    with pytest.raises(HubError) as err:
        run(console.line_follow_mode("b", "IR_LINE"))
    assert err.value.code == "TRIP_ROBOT_BUSY"
    run(console.line_follow_mode("b", "OFF"))
    assert ("line_follow_mode", "OFF") in robots[1].calls and runner.canceled == [("b", "operator_line_follow_off")]
    run(console.line_follow_mode("a", "IR_LINE"))  # another robot is not affected
    assert runner.canceled == [("b", "operator_line_follow_off")]


def test_cancel_robot_ends_the_trip_with_the_reason():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    run(runner.cancel_robot("rosy_60", "operator_line_follow_off"))
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["canceled_by"]) == (
        "canceled", "operator_line_follow_off", None)


def test_default_wiring_refuses_start_until_the_providers_land(tmp_path):
    from test_site_map_trip import _app as plain_app, _on_ring_s

    client, _tasks, store, robot = plain_app(tmp_path)
    robot._state = _on_ring_s(store)
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    refused = client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "TRIP_ROBOT_CAPS_UNKNOWN"


# ---- re-review R1-R8 ----------------------------------------------------------------------

@pytest.mark.parametrize("reply", [{"accepted": False, "queued": True, "reason": "ROUTE_CONFLICT"},
                                   {"accepted": False, "queued": False, "reason": "YIELDED"}])
def test_a_goal_the_console_did_not_send_fails_the_trip_and_clears_its_queue(reply):
    released = []
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    runner._release_queue = released.append
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))

    async def refused(robot_id, x, y, yaw):
        return reply

    ports.goal = refused
    runner._goal = refused
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["goal_reason"]) == (
        "failed", "TRIP_GOAL_REFUSED", reply["reason"])
    assert ports.canceled == ["rosy_60"] and released == ["rosy_60"]


def test_a_free_arrival_clears_the_robots_console_queue():
    released = []
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    runner._release_queue = released.append
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.at(_arc(store, "bc:fwd"), 0.97)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "arrived" and released == ["rosy_60"]


def test_start_refuses_a_robot_that_already_moves_for_the_console():
    runner, store, ports = _setup()
    runner._engaged = lambda robot_id: "yielding"
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert (err.value.status, err.value.code, err.value.detail) == (409, "TRIP_ROBOT_BUSY", {"reason": "yielding"})


def test_engaged_reads_queue_goal_yield_and_formation():
    from fleet.server.trip_guard import engaged

    console, _runner, _robots = _guarded("a", "b")
    assert engaged(console, "a") is None
    console._goals["a"] = {"x": 0, "y": 0, "yaw": 0}
    assert engaged(console, "a") is None  # a finished goal is still shown; it does not count
    console._seen["a"] = {"navigation": "NAVIGATING"}
    assert engaged(console, "a") == "goal"
    console._goals.clear()
    console._queued["a"] = {"x": 0}
    assert engaged(console, "a") == "queued"
    console._queued.clear()
    console._yielding["a"] = {"for": "b"}
    assert engaged(console, "a") == "yielding"


def test_a_carried_out_instruction_is_never_sent_again():
    runner, store, ports = _setup(junction_expires_s=2.0)
    ring_s = _arc(store, "ring_s:fwd")
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    ports.core.see_junction()  # CORE executes our straight through SE
    _ticks(runner, ports)
    assert runner._live["rosy_60"].sent["carried"]
    ports.core.j = None  # CORE went idle without our seeing it finish; SE is 0.32 m ahead
    ports.at(ring_s, 0.05)
    _ticks(runner, ports, 3, dt=3.0)
    assert len(ports.sent) == 1


def test_a_carried_out_place_short_of_the_next_lane_keeps_the_pose_on_this_lane():
    """lap SIM 2 lap_12: CORE went idle on our straight while the robot backed off 0.26 m before
    SE; the pose is judged against ring_s, not ring_e (0.276 m away), so no false 'pose' stop."""
    runner, store, ports = _setup()
    ring_s = _arc(store, "ring_s:fwd")
    _plan(store, ports, "ring_s:fwd", 0.05, "NW")
    run(runner.start("p1", "bob"))
    ports.at(ring_s, ring_s.length_m - 0.2)
    _ticks(runner, ports)
    ports.core.see_junction()  # CORE executes our straight through SE
    _ticks(runner, ports)
    assert runner._live["rosy_60"].sent["carried"]
    ports.core.j = None  # CORE closed it (the keeper lost the junction while backing off)
    ports.at(ring_s, ring_s.length_m - 0.26)
    sent = len(ports.sent)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "running" and runner.view("p1")["segment_index"] == 0
    assert len(ports.sent) == sent                         # the carried-out straight is not sent again
    ports.at(_arc(store, "ring_e:fwd"), 0.03)               # on the next lane: it moves on
    _ticks(runner, ports)
    assert runner.view("p1")["segment_index"] == 1


def test_already_done_from_core_counts_as_carried_out():
    runner, store, ports = _setup()
    ring_s = _arc(store, "ring_s:fwd")
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.core.done_place = ("SE", "straight")  # it ran between two ticks
    ports.at(ring_s, ring_s.length_m - 0.02)
    _ticks(runner, ports)
    assert runner.running() is not None and runner._live["rosy_60"].sent["done"]
    _ticks(runner, ports)
    assert runner.running()["segment_index"] == 1 and ports.sent[-1] == ("straight", "NE", None)


def test_lane_arrival_requires_an_accepted_stop_even_within_the_arrival_window():
    runner, store, ports = _setup()
    arc = _arc(store, "east:fwd")
    _plan(store, ports, "east:fwd", 0.5, "SE")
    run(runner.start("p1", "bob"))
    ports.core.manual_released = False  # the stop is refused: no arrival on distance alone
    ports.at(arc, arc.length_m - 0.05)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "failed" and runner.view("p1")["reason"] == "MODE_CONFLICT"


def test_confirm_replan_forgets_the_last_instruction():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.blocked = frozenset({"ring_e"})
    _ticks(runner, ports)
    held = runner._live["rosy_60"].sent["seq"]
    run(runner.confirm_replan("p1", "bob"))
    assert runner._live["rosy_60"].sent is None and runner._live["rosy_60"].replaceable == held


def test_the_restart_halt_is_retried_until_it_takes_or_the_robot_leaves(tmp_path):
    store = SiteMapStore(tmp_path / "fleet.sqlite3")
    for trip_id, robot_id in (("t1", "rosy_60"), ("t2", "gone")):
        store.put_trip({"trip_id": trip_id, "robot_id": robot_id, "state": "running", "drive_mode": "lane",
                        "next_place": None, "detail": {}})
    store.close()
    runner, store, ports = _setup(path=tmp_path / "fleet.sqlite3")
    runner.halts.roster = lambda: ["rosy_60"]
    hold = ports.hold
    calls = []

    async def flaky(robot_id):
        calls.append(robot_id)
        if len(calls) == 1:
            raise OSError("robot unreachable")
        return await hold(robot_id)

    ports.hold = flaky
    run(runner.halts.halt_restarted())
    assert [t["robot_id"] for t in runner.halts.restarted] == ["rosy_60"]  # "gone" left the roster
    run(runner.halts.halt_restarted())
    assert runner.halts.restarted == [] and calls == ["rosy_60", "rosy_60"]
    assert store.trip("t1")["detail"]["stop_sent"] is True


def test_robot_routes_refuse_a_trip_robot(tmp_path):
    ports = Ports()
    client, _tasks, _store, robot, _console = _app(tmp_path, ports)
    ports.now = time.time()
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    assert client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR).status_code == 200
    stuck = client.post("/api/fleet/robots/rosy_60/line-stuck/decision",
                        json={"stuck_id": "s1", "decision": "RESUME"}, headers=OPERATOR)
    assert stuck.status_code == 409 and stuck.json()["detail"]["code"] == "TRIP_ROBOT_BUSY"
    ir = client.post("/api/fleet/robots/rosy_60/line-follow", json={"mode": "IR_LINE"}, headers=OPERATOR)
    assert ir.status_code == 409 and ir.json()["detail"]["code"] == "TRIP_ROBOT_BUSY"
    off = client.post("/api/fleet/robots/rosy_60/line-follow", json={"mode": "OFF"}, headers=OPERATOR)
    assert off.status_code == 200 and ("line_follow_mode", "OFF") in robot.calls
    view = client.get(f"/api/fleet/trips/{plan['plan_id']}", headers=VIEWER).json()
    assert (view["state"], view["reason"]) == ("canceled", "operator_line_follow_off")


def test_every_route_holder_refusal_keeps_its_exact_body(tmp_path):
    """D-763 slice 1: one holder check behind every route; each route's 409 body stays as it was."""
    ports = Ports()
    client, _tasks, _store, _robot, _console = _app(tmp_path, ports)
    ports.now = time.time()
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    assert client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR).status_code == 200
    long = {"code": "TRIP_ROBOT_BUSY", "message": "rosy_60 is on a running trip; cancel the trip first"}
    busy = {**OPERATOR, "Idempotency-Key": "k1"}
    for path, body, detail in (
            ("goal", {"x": 0.1, "y": 0.0, "yaw": 0.0}, long),
            ("route", {"edges": ["ring_s"]}, {"code": "TRIP_ROBOT_BUSY", "message": "rosy_60 is on a running trip"}),
            ("line-stuck/decision", {"stuck_id": "s1", "decision": "BACK_AND_RETRY"}, long)):
        response = client.post(f"/api/fleet/robots/rosy_60/{path}", json=body, headers=busy)
        assert (response.status_code, response.json()) == (409, {"detail": detail}), path


def test_start_through_the_api_refuses_a_robot_with_a_queued_console_mission(tmp_path):
    ports = Ports()
    client, _tasks, _store, _robot, console = _app(tmp_path, ports)
    ports.now = time.time()
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    console._queued["rosy_60"] = {"x": 0.0, "y": 0.0, "yaw": 0.0, "reason": "ROUTE_CONFLICT"}
    refused = client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR)
    assert refused.status_code == 409 and refused.json()["detail"] == {
        "code": "TRIP_ROBOT_BUSY", "detail": {"reason": "queued"}}


def test_an_aborted_place_is_never_sent_again_even_back_in_camera_line():
    runner, store, ports = _setup(_free_map("lane"))
    _plan(store, ports, "ab:fwd", 0.5, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    ports.core.see_junction()  # turning at B
    ports.core.off()  # e.g. the driver released: CORE aborts the turn
    ports.core.mode = "CAMERA_LINE"  # back in camera line follow, 'aborted' still shown
    _ticks(runner, ports, 3)
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["junction_state"]) == ("stopped", "junction", "aborted")
    assert ports.sent == [("left", "B", None), ("stop", "B", 0.0)]  # only the halt's stop after it


def test_an_instruction_that_aborts_a_manoeuvre_stops_the_trip():
    runner, store, ports = _setup(_free_map("lane"))
    _plan(store, ports, "ab:fwd", 0.5, "C")
    run(runner.start("p1", "bob"))
    ports.core.send("left", "Z", None, 15, 45.0)  # someone else's turn, already running
    ports.core.see_junction()
    ports.state_none = True  # Fleet cannot see it, sends ours, and CORE aborts its turn instead
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["junction_state"]) == ("stopped", "junction", "aborted")


# ---- safety review H1, M1-M3, L1, N2-N4 ---------------------------------------------------

def _trip_app(tmp_path):
    ports = Ports()
    client, tasks, store, robot, console = _app(tmp_path, ports)
    ports.now = time.time()
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    assert client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR).status_code == 200
    return client, robot, console, plan["plan_id"], ports


@pytest.mark.parametrize(("path", "call", "reason"), [
    ("/api/fleet/robots/rosy_60/cancel", "navigation_cancel", "operator_cancel"),
    ("/api/fleet/cancel-all", "navigation_cancel", "operator_cancel"),
    ("/api/fleet/estop", "estop", "operator_estop"),
])
def test_every_operator_stop_reaches_the_robot_and_ends_the_trip(tmp_path, path, call, reason):
    client, robot, _console, trip_id, ports = _trip_app(tmp_path)
    response = client.post(path, headers=OPERATOR)
    assert response.status_code == 200, response.text
    assert [c for c in robot.calls if c[0] == call]
    view = client.get(f"/api/fleet/trips/{trip_id}", headers=VIEWER).json()
    assert (view["state"], view["reason"]) == ("canceled", reason)
    assert ports.held == ["rosy_60"]  # the trip's own halt (lane) ran too
    run(client.app.state.trip_runner.tick())
    assert ports.sent == [("stop", "SE", 0.0)]  # nothing re-sent after the stop


def test_create_app_wraps_every_console_motion_and_stop_method(tmp_path):
    _client, _robot, console, _trip_id, _ports = _trip_app(tmp_path)
    for name in ("goal", "formation_start", "formation_reform", "formation_resume", "line_follow_mode",
                 "cancel", "estop_all"):
        assert getattr(console, name).__name__ == f"guarded_{name}", name


def test_line_follow_off_ends_the_trip_even_when_the_robot_call_fails():
    console, runner, robots = _guarded("a", "b")
    robots[1].line_follow_mode = None  # the robot call raises

    async def failing(mode):
        raise OSError("robot unreachable")

    robots[1].line_follow_mode = failing
    with pytest.raises(OSError):
        run(console.line_follow_mode("b", "OFF"))
    assert runner.canceled == [("b", "operator_line_follow_off")]


def test_formation_reform_and_resume_refuse_a_trip_robot():
    console, _runner, _robots = _guarded("a", "b")
    console._formation_leader = "b"
    console._formation_members = lambda: {"a"}
    for call in (console.formation_reform("LINE"), console.formation_resume()):
        with pytest.raises(HubError) as err:
            run(call)
        assert err.value.code == "TRIP_ROBOT_BUSY"


def test_the_fleet_stuck_resolver_marks_a_trip_robot():
    """D-517 5 (M4): no longer skipped; the resolver gives a marked trip robot stopping answers only."""
    from fleet.stuck.loop import StuckResolverLoop

    seen = []

    class Resolver:
        ai_verdicts: list = []

        def step(self, now, rows):
            seen.extend((row["robot_id"], row.get("trip", False)) for row in rows)
            return []

    async def snapshot():
        return {"robots": [{"robot_id": "a"}, {"robot_id": "b"}]}

    loop = StuckResolverLoop(snapshot, board=None, resolver=Resolver(), clients=dict)
    loop.trip_busy = lambda robot_id: robot_id == "b"
    run(loop.run_once())
    assert seen == [("a", False), ("b", True)]


@pytest.mark.parametrize(("decision", "status", "ends"), [
    ("RESUME", 409, None), ("BACK_AND_RETRY", 409, None), ("WAIT", 200, None),
    ("ABORT", 200, "operator_stuck_abort"), ("MANUAL", 200, "operator_stuck_manual")])
def test_stuck_decisions_on_a_trip_robot(tmp_path, decision, status, ends):
    client, robot, _console, trip_id, _ports = _trip_app(tmp_path)
    response = client.post("/api/fleet/robots/rosy_60/line-stuck/decision",
                           json={"stuck_id": "s1", "decision": decision}, headers=OPERATOR)
    assert response.status_code == status, response.text
    forwarded = ("line_stuck_decision", "s1", decision) in robot.calls
    assert forwarded == (status == 200)
    view = client.get(f"/api/fleet/trips/{trip_id}", headers=VIEWER).json()
    assert (view["reason"] if ends else view["state"]) == (ends or "started")


def test_a_fresh_console_goal_counts_as_engaged():
    from fleet.server.trip_guard import engaged

    console, _runner, _robots = _guarded("a", "b")
    now = [100.0]
    console._goals["a"] = {"x": 0, "y": 0, "yaw": 0}
    console.trip_goal_sent_at["a"] = 99.0
    assert engaged(console, "a", clock=lambda: now[0]) == "goal"
    now[0] = 101.5
    assert engaged(console, "a", clock=lambda: now[0]) is None


def test_restart_halts_run_outside_the_tick_with_a_cap_and_yield_to_a_new_trip(tmp_path):
    store = SiteMapStore(tmp_path / "fleet.sqlite3")
    store.put_trip({"trip_id": "t1", "robot_id": "rosy_60", "state": "running", "drive_mode": "lane",
                    "next_place": None, "detail": {}})
    store.close()
    runner, store, ports = _setup(path=tmp_path / "fleet.sqlite3", restart_retry_s=0.001, restart_attempts=3)

    async def unreachable(robot_id):
        raise OSError("robot unreachable")

    ports.hold = unreachable
    run(runner.halts.run_restart())
    assert runner.halts.restarted == []  # gave up after 3 tries
    runner, store, ports = _setup(path=tmp_path / "fleet2.sqlite3")
    runner.halts.restarted = [{"trip_id": "old", "robot_id": "rosy_60", "drive_mode": "lane", "next_place": None}]
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    assert runner.halts.restarted == []  # the new trip owns the robot now


def test_a_trip_store_failure_never_replaces_the_stop_result(tmp_path, caplog):
    client, robot, _console, _trip_id, _ports = _trip_app(tmp_path)

    async def broken(robot_id, reason):
        raise RuntimeError("trip store unavailable")

    def store_down(_trip):
        raise RuntimeError("trip store unavailable")

    runner = client.app.state.trip_runner
    runner.cancel_robot = broken
    with caplog.at_level(logging.ERROR):
        cancel = client.post("/api/fleet/robots/rosy_60/cancel", headers=OPERATOR)
        off = client.post("/api/fleet/robots/rosy_60/line-follow", json={"mode": "OFF"}, headers=OPERATOR)
        runner._store.put_trip = store_down  # the E-stop closes the trip itself, then records it
        estop = client.post("/api/fleet/estop", headers=OPERATOR)
    assert estop.status_code == 200 and estop.json()["total"] == 1 and ("estop",) in robot.calls
    assert cancel.status_code == 200 and off.status_code == 200
    assert sum("could not end the trip" in r.message for r in caplog.records) == 2
    assert sum("could not record a trip ended by the E-stop" in r.message for r in caplog.records) == 1
    assert runner.open_trips() == []


def test_create_app_wires_the_real_trip_providers(tmp_path):
    from test_site_map_trip import _app as plain_app

    from fleet.server.map_pose_service import MapPoseService
    from fleet.server.trip_ports import HttpLaneJunction

    client, _tasks, _store, _robot = plain_app(tmp_path)
    runner = client.app.state.trip_runner
    assert runner._caps.__name__ == "_trip_caps"  # the planner's capability closure (install_trip_routes)
    assert isinstance(runner._poses, MapPoseService) and runner._poses is client.app.state.map_pose
    assert isinstance(runner._junction, HttpLaneJunction)
