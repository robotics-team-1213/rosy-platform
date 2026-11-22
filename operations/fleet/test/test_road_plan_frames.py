"""road-nav2 converts a site goal into the robot's own SLAM frame, or refuses (2026-11-13)."""
import asyncio
import math
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from fleet.server.task_dispatch_helpers import compute_road_plan
from fleet.server import named_stop_frame


def plan(site_pose, robot_state):
    async def map_pose(_robot_id):
        return site_pose

    console = SimpleNamespace(snapshot=lambda: _snap(robot_state))
    app = SimpleNamespace(state=SimpleNamespace(site_maps=None, trip_runner=SimpleNamespace(map_pose=map_pose)))
    return asyncio.run(compute_road_plan(console, SimpleNamespace(app=app), "rosy_46", 0.0, 0.0, None, None, ""))


async def _snap(robot_state):
    return {"robots": [{"robot_id": "rosy_46", "state": robot_state}]}


def site(x, y, yaw, state="LOCALIZED"):
    return SimpleNamespace(x=x, y=y, yaw=yaw, state=state)


SLAM_ORIGIN = {"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
               "localization": {"state": "LOCALIZED", "pose_frame": "map"}}


def test_a_site_goal_is_rotated_and_shifted_into_the_slam_frame():
    # Robot booted at site (-0.42, 0.38) facing -90 deg, so its SLAM origin is there.
    out = plan(site(-0.42, 0.38, -math.pi / 2), SLAM_ORIGIN)["target_nav2"]
    # Site goal (0, 0): 0.42 east and 0.38 south of the robot; in the robot frame that is +0.38 ahead, +0.42 left.
    assert (out["x"], out["y"]) == pytest.approx((0.38, 0.42), abs=1e-3)


@pytest.mark.parametrize("pose", [None, site(-0.42, 0.38, -math.pi / 2, state="UNKNOWN")])
def test_no_measured_site_pose_refuses_instead_of_assuming_identity(pose):
    with pytest.raises(HTTPException) as err:
        plan(pose, SLAM_ORIGIN)
    assert err.value.detail["code"] == "SITE_POSE_UNKNOWN"


@pytest.mark.parametrize("state", [
    {"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "localization": {"state": "LOST", "pose_frame": "map"}},
    {"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "localization": {"state": "LOCALIZED", "pose_frame": "odom"}},
    {"localization": {"state": "LOCALIZED", "pose_frame": "map"}},
])
def test_no_localized_robot_map_pose_refuses(state):
    with pytest.raises(HTTPException) as err:
        plan(site(-0.42, 0.38, -math.pi / 2), state)
    assert err.value.detail["code"] == "ROBOT_POSE_UNTRUSTED"


def test_the_refusal_names_why_auto_locate_has_no_fit():
    # 2026-11-14 rosy_45: battery caution, so the robot refused the identify blink and no fit came.
    auto = SimpleNamespace(snapshot=lambda: {"robots": [
        {"robot_id": "rosy_46", "reason": "lamp_refused", "lamp_reason": "CAUTION_ACTIVE"}]})

    async def map_pose(_robot_id):
        return None

    console = SimpleNamespace(snapshot=lambda: _snap(SLAM_ORIGIN))
    app = SimpleNamespace(state=SimpleNamespace(site_maps=None, auto_locate=auto,
                                                trip_runner=SimpleNamespace(map_pose=map_pose)))
    with pytest.raises(HTTPException) as err:
        asyncio.run(compute_road_plan(console, SimpleNamespace(app=app), "rosy_46", 0.0, 0.0, None, None, ""))
    assert err.value.detail["auto_locate"] == "lamp_refused (CAUTION_ACTIVE)"
    assert "lamp_refused (CAUTION_ACTIVE)" in err.value.detail["message"]


def test_named_stop_with_an_approved_binding_refuses_a_missing_road(monkeypatch):
    from fleet.localization.map_binding import Fit

    def unavailable(*args, **kwargs):
        raise ValueError("no road")

    monkeypatch.setattr("fleet.routing.road_path.plan_road_path", unavailable)
    stop = SimpleNamespace(kind="stop", yaw=math.pi)
    graph = SimpleNamespace(places={"S3": stop}, place_xy=lambda _: (0.745, -0.207))
    store = SimpleNamespace(
        active=lambda _: {"binding_id": "fit-1"},
        matching_fit=lambda *_: (Fit(0.2, 0.3, 0.4, (0.0,)), ""),
    )
    maps = SimpleNamespace(active=lambda: (261, SimpleNamespace(map_id="workcell"), graph),
                           map_bindings=store)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(site_maps=maps, named_stop_frame=named_stop_frame)))
    console = SimpleNamespace(snapshot=lambda: _snap({**SLAM_ORIGIN, "map_grid_id": "grid-A"}))

    with pytest.raises(HTTPException) as err:
        asyncio.run(compute_road_plan(console, request, "rosy_46", 0.0, 0.0, None, "S3", ""))

    assert err.value.detail == {"code": "STOP_ROUTE_UNAVAILABLE", "place_id": "S3"}


@pytest.mark.parametrize("change", ["none", "grid", "site", "signal", "revoked-before-post",
                                     "handoff", "handoff-lost-before-post", "handoff-occupied",
                                     "handoff-peer-read-lost", "handoff-peer-planning", "handoff-peer-navigating",
                                     "handoff-peer-line-hold", "handoff-staging-changed",
                                     "handoff-detour-occupied", "handoff-bad-plan", "direct-detour-occupied",
                                     "handoff-peer-stale", "mover-stale", "handoff-off-terminal", "handoff-crosswalk",
                                     "direct-overflow", "handoff-legacy-wire-race"])
def test_named_stop_binding_is_checked_at_dispatch_and_before_the_goal_post(monkeypatch, change):
    from fleet.server import console_helpers
    from fleet.server.map_binding_store import MapBindingStore
    from fleet.routing.graph import Arc
    from fleet.swarm.dispatch_guard import check_dispatch

    robot_id = "rosy_46"
    is_handoff = change.startswith("handoff")
    lease = {"lease_id": "lease-a", "trip_id": "trip-a", "job_id": None}
    scope = dict(lease, junction_seq=1, stop_place_id="S3_entry", staging_xy=[0.0, 0.0], staging_radius_m=0.15)
    boot_id = "1ad31f2d-f4ac-41aa-9bc1-37cb77a16664"
    target = (0.745, -0.207)
    length = math.hypot(*target)
    arc = Arc("finish:fwd", "finish", True, "S3_entry", "S3", ((0.0, 0.0), target), (0.0, length),
              0.2 if change == "handoff-off-terminal" else 2.0, 0.1, "free", None)
    scope["terminal"] = {"arc_id": arc.id, "s_from": 0.0, "s_to": length, "robot_kind": "pinky_pro"}
    ready = True
    operation = {"boot_id": boot_id, "run_id": "c17ca896-9ae1-495c-a936-b7c7db3953fc", "kind": "navigate",
                 "phase": "RUNNING", "correlation_id": "attempt"}
    expected = {"site_map_id": "cell", "site_map_version": 261,
                "binding_id": "fit-1", "map_grid_id": "grid-A"}
    approval = {"binding_id": "fit-1", "site_map_id": "cell", "site_map_version": 261,
                "robot_grid_id": "grid-A", "fit": {"yaw": 0, "tx": 0, "ty": 0, "residual_max_m": 0}}
    peer_approval = {**approval, "binding_id": "fit-2", "robot_grid_id": "grid-peer",
                     "fit": {**approval["fit"], "tx": 5.0}}
    store = SimpleNamespace(active=lambda rid: approval if rid == robot_id else peer_approval)
    store.matching_fit = lambda *args: MapBindingStore.matching_fit(store, *args)
    maps = SimpleNamespace(
        active=lambda: (262 if change == "site" else 261, SimpleNamespace(
            map_id="cell", edges=[SimpleNamespace(drive_mode="lane" if is_handoff else "free",
                                                  direction="two_way")],
            turn_bans=[], crosswalks=([SimpleNamespace(
                polygon=[(-0.1, 0.6), (0.1, 0.6), (0.1, 0.8), (-0.1, 0.8)], approach=[])]
                if change == "handoff-crosswalk" else [])), SimpleNamespace(arcs={arc.id: arc})),
        map_bindings=store,
    )

    async def state():
        return {**SLAM_ORIGIN, "map_grid_id": "grid-B" if change == "grid" else "grid-A", "trip_lease": lease, "map_id": "same-name",
                "velocity": {"linear": 0.0, "angular": 0.0},
                "evidence": {"pose": {"evidence": "fresh"},
                             "velocity": {"evidence": "stale" if change == "mover-stale" else "fresh"}},
                **({"pose": {"x": 0.4, "y": 0.0}} if change == "handoff-staging-changed" else {})}

    async def get(path):
        if path == "/api/v1/navigation/state":
            if change == "handoff-legacy-wire-race":
                console.goal_leases.motion_epoch += 1
            return {"owner": {"boot_id": boot_id, "owner_generation": 9}}
        assert path == f"/api/v1/navigation/state?run_id={operation['run_id']}"
        return {"owner": {"boot_id": boot_id, "owner_generation": 10, "owner_run_id": operation["run_id"]},
                "operation": operation}

    async def capability(*_):
        return {}

    requests = []
    plan_id = "acc31f2d-f4ac-41aa-9bc1-37cb77a16664"

    async def send(*_, expected_map_grid_id, **options):
        nonlocal ready
        assert expected_map_grid_id == "grid-A"
        if change == "revoked-before-post":
            store.active = lambda _: None
        if change == "handoff-lost-before-post":
            ready = False
        assert options == {"line_handoff": scope if is_handoff else None, "plan_id": plan_id,
                           "owner_epoch": {"expected_boot_id": boot_id, "expected_owner_generation": 9}}
        check_dispatch(path=f"/api/v1/navigation/{'line-handoff-goal' if is_handoff else 'bound-goal'}")
        requests.append("goal")
        return {"accepted": True, "operation": operation}

    monkeypatch.setattr(console_helpers, "require_capability", capability)
    async def peer_state():
        if change == "handoff-peer-read-lost":
            raise OSError("peer unavailable")
        occupied = change in ("handoff-occupied", "handoff-detour-occupied", "direct-detour-occupied")
        detour = change.endswith("detour-occupied")
        peer_nav = {"handoff-peer-planning": "PLANNING", "handoff-peer-navigating": "NAVIGATING"}
        return {**SLAM_ORIGIN, "pose": {"x": -5.0 if occupied else 0.02, "y": 0.7 if detour else 0.0},
                "mode": "IDLE", "velocity": {"linear": 0.0, "angular": 0.0},
                "evidence": {"pose": {"evidence": "stale" if change == "handoff-peer-stale" else "fresh"},
                             "velocity": {"evidence": "fresh"}},
                "navigation": peer_nav.get(change, "IDLE"),
                "line_follow": {"mode": "CAMERA_LINE" if change == "handoff-peer-line-hold" else "OFF",
                                "state": "HOLD"},
                "map_id": "same-name" if occupied else "different-name", "map_grid_id": "grid-peer"}

    async def navigation_plan(*_, **kwargs):
        assert kwargs == {"correlation_id": "attempt", "expected_map_grid_id": "grid-A",
                          "line_handoff": scope if is_handoff else None}
        return {"plan_id": plan_id, "map_grid_id": "grid-A",
                "frame": "odom" if change == "handoff-bad-plan" else "map",
                "points": [[0, 0], [1e155 if change == "direct-overflow" else 0, 0.7], [0.745, -0.207]]}

    client = SimpleNamespace(state=state, _get=get, navigation_plan=navigation_plan)
    clients = {robot_id: client}
    if is_handoff or change == "direct-detour-occupied":
        clients["peer"] = SimpleNamespace(state=peer_state)
    console = SimpleNamespace(
        _named_stop_site_maps=maps, _client=lambda _: client, _clients=clients,
        clients=lambda: clients, robot_ids=list(clients), _traffic_lock=asyncio.Lock(), _goal_busy=set(), _clearance_m=0.2, _clock=time.monotonic,
        _named_stop_traffic=SimpleNamespace(has_configured_controls=lambda: change == "signal"),
        goal_leases=SimpleNamespace(stop_token=lambda _: 0, send=send, check_stop=lambda *_: None, pending={},
                                    motion_epoch=0),
        _formation_members=lambda: (), _yielding={}, _seen={},
        _goals={}, _queued={}, _claims={},
        _goal_admission=SimpleNamespace(yield_hold=lambda _: None),
        _remember=lambda _: None, _verdict=lambda _: "TRUSTED", trip_refusal=lambda _: None,
    )
    dispatch = console_helpers._goal(console, robot_id, 0.745, -0.207, math.pi,
                                     task_id=None if is_handoff else "task", attempt_id="attempt", attempt_seq=1,
                                     lease_source="trip" if is_handoff else None, stop_binding=expected,
                                     line_handoff=(scope, lambda: ready) if is_handoff else None)
    if change in ("none", "handoff"):
        assert asyncio.run(dispatch)["accepted"] is True
        assert requests == ["goal"]
        assert console._claims[robot_id] == [(0, 0), (0, 0.7), (0.745, -0.207)]
    else:
        with pytest.raises(console_helpers.HubError):
            asyncio.run(dispatch)
        assert requests == []


def test_terminal_corridor_proves_whole_spans_and_reserves_body_margin():
    from fleet.server.handoff_traffic import _inside_corridor

    elbow = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    assert _inside_corridor(elbow, elbow, 0.02)
    assert _inside_corridor([(0.99, 0.0), (1.0, 0.01)], elbow, 0.01)
    assert not _inside_corridor([elbow[0], elbow[-1]], elbow, 0.02)
    assert not _inside_corridor(elbow, elbow, 0)


def test_terminal_corridor_refuses_excessive_geometric_work_before_send():
    from fleet.hub.hub import HubError
    from fleet.server.handoff_traffic import _inside_corridor

    centerline = [(i / 150, 0.0) for i in range(151)]
    with pytest.raises(HubError, match="NAMED_STOP_PATH_TOO_COMPLEX"):
        _inside_corridor(centerline, centerline, 0.01)
