"""Fleet berth-park mode core_line: never a plain Nav2 goal at the bay (D-1042 safety review F3)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.ledger.berth_parking_routes import install_berth_parking_routes
from fleet.server.site_auth import SitePrincipal


def test_core_line_never_falls_back_to_a_plain_nav2_goal():
    sent = []

    async def plan(*args):
        return {"target_nav2": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "waypoints_site": []}

    async def dispatch_nav(**kw):
        sent.append(kw)
        return {"accepted": True}
    app = FastAPI()
    op = lambda: SitePrincipal(principal_id="op", role="operator")  # noqa: E731
    install_berth_parking_routes(app, console=SimpleNamespace(trip_refusal=lambda ids: None, _clients={}),
                                 task_service=None, read_guard=[], operator_guard=[], require_operator=op,
                                 require_named_operator=op, compute_road_plan=plan, dispatch_nav=dispatch_nav)
    client = TestClient(app)
    res = client.post("/api/fleet/robots/rosy_45/berth-park", json={"bay_id": "C3", "mode": "core_line"})
    assert res.status_code == 502 and sent == []
    res = client.post("/api/fleet/robots/rosy_45/berth-park",
                      json={"bay_id": "C3", "mode": "core_line", "execute_physical": False})
    assert res.status_code == 400 and sent == []



def test_selected_bay_preview_uses_its_own_spine_and_owner():
    import asyncio
    import pytest
    from fleet.server.rear_bay_return import rear_bay, RearBayPort
    from fleet.routing.trip import PlanRequest, RoutingConfig, plan_trip
    from fleet.server.trip_ports import TripError
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    _, graph, _ = build_world_261026_site_map()
    start = graph.places["S2"]
    for n in (1, 2, 3):
        info = rear_bay(graph, f"C{n}")
        staging = info["staging_place_id"]
        assert (staging, info["bay_id"], info["dock_id"]) == (f"P{n}", f"C{n}", f"bay_c{n}")
        path = plan_trip(graph, PlanRequest(map_version=graph.version, start_pose=(start.x, start.y, 0.),
                                           goal=staging, ignore_start_heading=True), RoutingConfig())
        assert path.places[-1] == staging and info["bay_id"] not in path.places
    class NoC2:
        async def _get(self, path):
            return {"docks": [{"id": "bay_c3", "type": "line", "x": 0., "y": 0., "yaw": 0.}]}
    owner = RearBayPort(SimpleNamespace(clients=lambda: {"rosy_42": NoC2()}))
    with pytest.raises(TripError) as err:
        asyncio.run(owner.target("rosy_42", rear_bay(graph, "C2")))
    assert err.value.code == "CHARGE_BAY_TARGET_NOT_TAUGHT"

@pytest.mark.parametrize(("staging", "bay", "dock", "seen"), [("P2", "C2", "bay_c2", False), ("P3", "C3", "bay_c3", True)])
def test_stationary_staging_starts_only_its_taught_bay_and_waits_for_exact_docked_run(monkeypatch, staging, bay, dock, seen):
    import asyncio
    from uuid import uuid4
    from datetime import datetime, timezone
    from fleet.server.rear_bay_return import RearBayPort, rear_bay
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    _, graph, _ = build_world_261026_site_map()
    sx, sy = graph.place_xy(staging)
    boot, run = str(uuid4()), str(uuid4())
    scoped = False
    blocked = True
    clock = [10.]
    owner = {"boot_id": boot, "owner_generation": 8, "owner_run_id": None}
    calls = []
    op = {"kind": "dock", "boot_id": boot, "run_id": run, "phase": "RUNNING", "correlation_id": "plan-id"}
    class Core:
        async def _get(self, path):
            if path.endswith("/types"):
                return {"types": [{"name": "pink", "approach": "line", "staging_offset_m": .32}]}
            return {"docks": [{"id": dock, "type": "pink", "map_id": "map42", "x": 1., "y": 2., "yaw": 0.}]}
        async def state(self):
            return {"map_id": "map42", "map_grid_id": "grid42", "velocity": {"linear": 0., "angular": 0.},
                    "navigation": "ARRIVED", "line_follow": {"mode": "OFF"}}
        async def _post(self, path, body):
            calls.append((path, body))
            return {"operation": op}
        async def docking_status(self, run_id=None):
            if run_id is None:
                return {"owner": owner, "operation_cancel_supported": scoped}
            assert run_id == run
            return {"lookup": "FOUND", "owner": owner, "state": "DOCKED", "dock_id": dock,
                    "operation": dict(op, phase="TERMINAL", result="SUCCEEDED"),
                    "quiescence": {**owner, "requested_run_id": run, "admitting": False, "pending_submission": False,
                        "actuating_callback": False, "lease_active": False, "transport_generation": 1,
                        "quiescent": True, "observed_at": datetime.now(timezone.utc).isoformat()}}
    async def pose(*args):
        return SimpleNamespace(x=sx, y=sy, state="LOCALIZED", map_id="site")
    async def map_pose(_):
        return SimpleNamespace(x=sx, y=sy, state="LOCALIZED", map_id="site", anchor_source="track", anchor_age_s=.4,
                               camera_residual_m=.02) if seen else None
    runner = SimpleNamespace(_progress_pose=pose, map_pose=map_pose, config=SimpleNamespace(arrive_free_m=.15),
                             _check_human_hold=lambda: None, _graph_for=lambda _: graph, _save=lambda _: None,
                             _clock=lambda: clock[0])
    park = dict(rear_bay(graph, bay), phase="staging_confirmed")
    live = SimpleNamespace(open=True, graph=graph, view={"robot_id":"rosy_42", "state":"running", "trip_id":"plan-id",
                           "map_version":394, "detail":{"parking_handoff": park}})
    client = Core()
    runner.bay_cable_inhibited = lambda _: False
    port = RearBayPort(SimpleNamespace(clients=lambda: {"rosy_42": client}, goal_leases=SimpleNamespace(stop_token=lambda _: 1)))
    async def clear(*args):
        if blocked:
            from fleet.hub.hub import HubError
            raise HubError("COMMAND_REJECTED", "LINE_HANDOFF_PEER_STATE_UNVERIFIED")
        return await Core().state(), ("map42", [(sx, sy), graph.place_xy(bay)]), lambda: None
    async def approved(*args):
        return await pose(), "binding"
    monkeypatch.setattr("fleet.server.rear_bay_return.read_precision_pose", approved)
    port.clearance = clear
    asyncio.run(port.step(runner, live))
    assert (park["phase"], park["reason"]) == ("waiting_for_commission", "CHARGE_BAY_SCOPED_CANCEL_UNSUPPORTED")
    scoped = True
    clock[0] += 4
    asyncio.run(port.step(runner, live))
    assert park["phase"] == "waiting_for_clearance" and calls == [] and live.view["state"] == "running"
    blocked = False
    clock[0] += 2
    asyncio.run(port.step(runner, live))
    body = {"dock": dock, "correlation_id": "plan-id", "expected_boot_id": boot, "expected_owner_generation": 8}
    if seen:   # the ceiling camera's fresh track reaches CORE as evidence, with CORE's own map id
        body["site_pose_evidence"] = {"anchor_source": "track", "anchor_age_s": .4, "camera_residual_m": .02, "map_id": "map42",
                                      "at": calls[0][1]["site_pose_evidence"]["at"]}
    assert calls == [("/api/v1/docking/dock", body)]
    assert park["phase"] == "docking" and live.view["state"] == "running"
    asyncio.run(port.step(runner, live))
    assert live.view["state"] == "arrived" and park["phase"] == "docked" and len(calls) == 1

def test_site_pose_evidence_only_from_a_fresh_independent_camera_anchor():
    from fleet.server.rear_bay_return import site_pose_evidence
    bound = SimpleNamespace(x=1., y=2., map_id="site")
    cam = dict(x=1.03, y=2., state="LOCALIZED", map_id="site", anchor_source="sighting", anchor_age_s=3., camera_residual_m=.05)
    ok = site_pose_evidence(SimpleNamespace(**cam), bound, "grid")
    assert ok["anchor_source"] == "sighting" and ok["map_id"] == "grid" and ok["anchor_age_s"] == 3.
    for bad in (dict(anchor_source="operator_pin"), dict(anchor_source="auto_locate"), dict(anchor_source=None),
                dict(anchor_age_s=10.1), dict(anchor_age_s=None), dict(camera_residual_m=None), dict(camera_residual_m=.081),
                dict(state="DEGRADED"), dict(map_id="other"), dict(x=1.2)):   # x=1.2: camera and SLAM disagree
        assert site_pose_evidence(SimpleNamespace(**{**cam, **bad}), bound, "grid") is None, bad
    assert site_pose_evidence(None, bound, "grid") is None and site_pose_evidence(SimpleNamespace(**cam), bound, None) is None


def test_rear_bay_checks_traffic_again_at_the_transport():
    import asyncio
    import math
    import pytest
    from core_common.protocol.evidence import STALE_POSE_S
    from fleet.hub.hub import HubError
    from fleet.localization.map_binding import Fit
    from fleet.server.goal_lease import GoalLeases
    from fleet.server.trip_ports import TripError
    from fleet.server.rear_bay_return import RearBayPort, rear_bay
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    _, graph, _ = build_world_261026_site_map()
    start, goal = graph.place_xy("P2"), graph.place_xy("C2")
    async def state(xy):
        return dict(pose=dict(zip(("x", "y"), xy)), velocity={"linear": 0., "angular": 0.},
                    mode="IDLE", navigation="ARRIVED", line_follow={"mode": "OFF"},
                    evidence={key: {"evidence": "fresh"} for key in ("pose", "velocity")})
    for change in ("claim", "peer_wire", "disconnected", "expiry"):
        clock = [0.]
        clients = {"42": SimpleNamespace(state=lambda: state(start)), "45": SimpleNamespace(state=lambda: state((9., 9.)))}
        leases = GoalLeases(0., clients)
        fit = Fit(0., 0., 0., (.001,))
        store = SimpleNamespace(map_bindings=SimpleNamespace(matching_fit=lambda *_: (fit, None),
                                active=lambda _: {"binding_id": "binding"}),
                                active=lambda: (graph.version, SimpleNamespace(map_id="site"), graph))
        blocked = []
        console = SimpleNamespace(robot_ids=("42", "45"), clients=lambda: clients, goal_leases=leases,
                                 _named_stop_site_maps=store, _goal_busy=set(), _clearance_m=.15,
                                 _claim_blocker=lambda *args, **kw: (next(iter(blocked), None), None))
        runner = SimpleNamespace(_clock=lambda: clock[0], _store=store, bay_cable_inhibited=lambda _: False)
        live = SimpleNamespace(graph=graph, view=dict(robot_id="42", map_version=graph.version,
                                             detail={"nav2_binding_id": "binding"}))
        target = dict(x=goal[0], y=goal[1], yaw=math.atan2(goal[1]-start[1], goal[0]-start[0]))
        _, _, verify = asyncio.run(RearBayPort(console).clearance(runner, live, clients["42"], rear_bay(graph, "C2"),
                                                                  target, math.dist(start, goal)))
        verify()
        if change == "claim":
            blocked.append("45")
        elif change == "disconnected":
            del clients["45"]
        elif change == "peer_wire":
            with leases.motion_wire("45", "POST", "/api/v1/navigation/goal", {}):
                with pytest.raises(TripError, match="CHARGE_BAY_PEER_CHANGED"):
                    verify()
        else:
            clock[0] += STALE_POSE_S + .01
        with pytest.raises((TripError, HubError)):
            verify()


def test_read_only_dock_prerequisites_report_target_and_cancel_while_peer_held():
    import asyncio
    from fleet.server.rear_bay_return import RearBayPort

    calls = []
    class ReadOnlyCore:
        async def _get(self, path):
            calls.append(path)
            return {"docks": [{"id": "bay_c2"}]}
        async def docking_status(self):
            calls.append("dock status")
            return {"operation_cancel_supported": False, "owner": {"owner_run_id": None, "owner_generation": 3}}
    core = ReadOnlyCore()
    port = RearBayPort(SimpleNamespace(clients=lambda: {"rosy_42": core}))
    result = asyncio.run(port.prerequisites("rosy_42", {"bay_id": "C1", "dock_id": "bay_c1"}))
    assert set(calls) == {"/api/v1/docking/docks", "dock status"}
    assert result["checks"] == {"target": "CHARGE_BAY_TARGET_NOT_TAUGHT",
                                "scoped_cancel": "CHARGE_BAY_SCOPED_CANCEL_UNSUPPORTED", "owner": None}
    assert result["reasons"] == ["CHARGE_BAY_TARGET_NOT_TAUGHT", "CHARGE_BAY_SCOPED_CANCEL_UNSUPPORTED"]
    assert result["robot_id"] == "rosy_42" and result["bay_id"] == "C1" and result["checked_at"] > 0


def _reframe_world(site, *, fit_yaw=0., tx=0., ty=0., stale=True):
    import asyncio
    from fleet.localization.map_binding import Fit
    from fleet.server.rear_bay_return import RearBayPort
    posts = []
    class Core:
        async def _post(self, path, body):
            posts.append((path, body))
            return {}
    fit = Fit(fit_yaw, tx, ty, (.001,))
    maps = SimpleNamespace(matching_fit=lambda *_: (fit, ""), active=lambda _: {"binding_id": "b2"})
    runner = SimpleNamespace(_store=SimpleNamespace(map_bindings=maps, active=lambda: (1, SimpleNamespace(map_id="site"))))
    live = SimpleNamespace(view={"robot_id": "rosy_42", "map_version": 1})
    snapshot = {"robot_id": "rosy_42", "map_id": "map", "map_grid_id": "grid_new", "map_generation": 4}
    meta = {"map_epoch": "grid_old", "binding_id": "b1", "commissioned_grid_id": "g_old", **({"site_pose": site} if site else {})}
    target = {"id": "bay_c2", "x": -.19, "y": .47, "yaw": -1.5708, "map_id": "grid_old", "metadata": meta}
    done = asyncio.run(RearBayPort(SimpleNamespace()).reframe(runner, live, Core(), snapshot, target))
    return done, posts


def test_same_frame_map_swap_retags_the_bay_dock_without_moving_it():
    done, posts = _reframe_world({"x": -.19, "y": .47, "yaw": -1.5708})
    assert done and posts == [("/api/v1/docking/docks/bay_c2/reframe", {
        "robot_id": "rosy_42", "map_id": "map", "map_grid_id": "grid_new", "map_generation": 4,
        "expected_map_id": "grid_old", "expected_grid_id": "g_old", "binding_id": "b1", "new_binding_id": "b2"})]


@pytest.mark.parametrize("site, kw", [
    ({"x": -.19, "y": .47, "yaw": -1.5708}, {"tx": .05}),                   # shifted binding: another frame
    ({"x": -.19, "y": .47, "yaw": -1.5708}, {"fit_yaw": .3}),               # rotated binding
    ({"x": -.19, "y": .55, "yaw": -1.5708}, {}),                            # dock not where the site says
    ({"x": -.19, "y": .47, "yaw": 0.}, {}),                                 # heading differs
    (None, {}),                                                             # no site pose recorded
])
def test_a_dock_in_another_frame_is_never_retagged(site, kw):
    done, posts = _reframe_world(site, **kw)
    assert not done and posts == []


@pytest.mark.parametrize("route_missing", [False, True])
def test_step_retags_a_stale_bay_dock_then_docks_or_stays_unverified(monkeypatch, route_missing):
    import asyncio
    from uuid import uuid4
    from fleet.localization.map_binding import Fit
    from fleet.swarm.transport import RobotApiError
    from fleet.server.rear_bay_return import RearBayPort, rear_bay
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    _, graph, _ = build_world_261026_site_map()
    sx, sy = graph.place_xy("P2")
    boot = str(uuid4())
    owner = {"boot_id": boot, "owner_generation": 8, "owner_run_id": None}
    dock = {"id": "bay_c2", "type": "pink", "map_id": "grid_old", "x": -.19, "y": .47, "yaw": -1.5708,
            "metadata": {"map_epoch": "grid_old", "binding_id": "b1", "site_pose": {"x": -.19, "y": .47, "yaw": -1.5708}}}
    posts = []
    op = {"kind": "dock", "boot_id": boot, "run_id": str(uuid4()), "phase": "RUNNING", "correlation_id": "plan-id"}
    class Core:
        async def _get(self, path):
            if path.endswith("/types"):
                return {"types": [{"name": "pink", "approach": "line", "staging_offset_m": .2}]}
            return {"docks": [dock]}
        async def state(self):
            return {"map_id": "map", "map_grid_id": "grid_new", "map_generation": 4, "robot_id": "rosy_42",
                    "velocity": {"linear": 0., "angular": 0.}, "navigation": "ARRIVED", "line_follow": {"mode": "OFF"}}
        async def docking_status(self, run_id=None):
            return {"owner": owner, "operation_cancel_supported": True}
        async def _post(self, path, body):
            posts.append(path)
            if path.endswith("/reframe"):
                if route_missing:
                    raise RobotApiError("rosy_42", 404, "HTTP_404", "not found")
                dock.update(map_id="map", metadata={**dock["metadata"], "map_epoch": "map", "binding_id": body["new_binding_id"]})
                return {}
            return {"operation": op}
    maps = SimpleNamespace(matching_fit=lambda *_: (Fit(0., 0., 0., (.001,)), ""), active=lambda _: {"binding_id": "b2"})
    clock = [10.]
    async def pose(*args):
        return SimpleNamespace(x=sx, y=sy, state="LOCALIZED", map_id="site")
    async def map_pose(_):
        return None
    runner = SimpleNamespace(_progress_pose=pose, map_pose=map_pose, config=SimpleNamespace(arrive_free_m=.15),
                             _check_human_hold=lambda: None, _graph_for=lambda _: graph, _save=lambda _: None,
                             _clock=lambda: clock[0], bay_cable_inhibited=lambda _: False,
                             _store=SimpleNamespace(map_bindings=maps, active=lambda: (1, SimpleNamespace(map_id="site"))))
    park = dict(rear_bay(graph, "C2"), phase="staging_confirmed")
    live = SimpleNamespace(open=True, graph=graph, view={"robot_id": "rosy_42", "state": "running", "trip_id": "plan-id",
                           "map_version": 1, "detail": {"parking_handoff": park}})
    client = Core()
    port = RearBayPort(SimpleNamespace(clients=lambda: {"rosy_42": client}, goal_leases=SimpleNamespace(stop_token=lambda _: 1)))
    async def clear(*args):
        return await client.state(), ("map", [(sx, sy), graph.place_xy("C2")]), lambda: None
    async def approved(*args):
        return await pose(), "b2"
    monkeypatch.setattr("fleet.server.rear_bay_return.read_precision_pose", approved)
    port.clearance = clear
    asyncio.run(port.step(runner, live))
    if route_missing:   # the robot has no reframe route: refused as before, no exception
        assert (park["phase"], park["reason"]) == ("waiting_for_commission", "CHARGE_BAY_TARGET_FRAME_UNVERIFIED")
        assert posts == ["/api/v1/docking/docks/bay_c2/reframe"]
        return
    assert (park["phase"], park["reason"]) == ("waiting_for_commission", "CHARGE_BAY_DOCK_REFRAMED")
    clock[0] += 2
    asyncio.run(port.step(runner, live))
    assert posts == ["/api/v1/docking/docks/bay_c2/reframe", "/api/v1/docking/dock"] and park["phase"] == "docking"
