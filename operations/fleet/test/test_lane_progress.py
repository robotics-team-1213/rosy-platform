"""D-941 2: lane-progress gap, leader choice across the loop seam, follower speed."""
import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest

from fleet.lane_progress import MIN_GAP_M, TARGET_GAP_M, Loop, follower_speed, leaders, main_loop, platoon
from fleet.site_map import SiteMap


def square():
    corners = {"A": (0, 0), "B": (1, 0), "C": (1, 1), "D": (0, 1)}
    order = ["A", "B", "C", "D", "A"]
    return SiteMap.model_validate({
        "schema": "rosy.site_map/1", "map_id": "loop_test",
        "places": [{"id": k, "name": k, "x": x, "y": y} for k, (x, y) in corners.items()],
        "edges": [{"id": f"{a}{b}", "from": a, "to": b, "polyline": [corners[a], corners[b]],
                   "direction": "one_way", "width_m": 0.1, "speed_cap_mps": 0.15}
                  for a, b in zip(order, order[1:])]})


def test_progress_and_gap_wrap_around_the_loop():
    loop = Loop(square(), ["AB", "BC", "CD", "DA"])
    assert loop.perimeter == pytest.approx(4.0)
    s, off = loop.project(0.5, 0.02)
    assert s == pytest.approx(0.5) and off == pytest.approx(0.02)
    assert loop.project(0.0, 0.5)[0] == pytest.approx(3.5)
    assert loop.gap(0.2, 3.8) == pytest.approx(0.4)          # leader just past the seam


def test_each_robot_follows_the_one_directly_ahead():
    loop = Loop(square(), ["AB", "BC", "CD", "DA"])
    got = leaders(loop, {"a": 0.2, "b": 3.8, "c": 2.0})
    assert got["b"] == ("a", pytest.approx(0.4))
    assert got["a"] == ("c", pytest.approx(1.8)) and got["c"][0] == "b"
    assert leaders(loop, {"solo": 1.0}) == {}


def test_follower_speed_adds_the_leader_speed_and_respects_cap_and_min_gap():
    assert follower_speed(0.1, TARGET_GAP_M, 0.15) == pytest.approx(0.1)   # at the target: match
    assert follower_speed(0.1, TARGET_GAP_M + 1.0, 0.15) == 0.15            # far behind: lane cap
    assert follower_speed(0.1, TARGET_GAP_M - 0.3, 0.15) < 0.1              # too close: slower
    assert follower_speed(0.0, MIN_GAP_M - 0.01, 0.15) == 0.0               # inside stop gap
    assert follower_speed(0.0, 0.3, 0.15) == 0.0                            # never reverses


def test_the_main_loop_is_the_shortest_one_way_cycle_not_the_detour():
    site = square().model_dump(by_alias=True)
    site["places"].append({"id": "E", "name": "E", "x": 1.5, "y": 0.5})    # B -> E -> C detour
    site["edges"] += [{"id": f"{a}{b}", "from": a, "to": b, "polyline": [p, q], "direction": "one_way",
                       "width_m": 0.1, "speed_cap_mps": 0.08}
                      for a, b, p, q in (("B", "E", (1, 0), (1.5, 0.5)), ("E", "C", (1.5, 0.5), (1, 1)))]
    loop = main_loop(SiteMap.model_validate(site))
    assert sorted(loop) == ["AB", "BC", "CD", "DA"]
    Loop(SiteMap.model_validate(site), loop)                              # driving order, closes


def test_platoon_rows_say_who_is_ahead_how_far_and_who_is_off_the_loop():
    loop = Loop(square(), ["AB", "BC", "CD", "DA"])
    rows = {r["robot_id"]: r for r in platoon(loop, {"a": (0.5, 0.0), "b": (0.3, 0.0), "c": (0.5, 0.5)})}
    assert rows["b"]["leader"] == "a" and rows["b"]["state"] == "too_close"
    assert rows["a"]["leader"] == "b" and rows["a"]["state"] == "ok"
    assert rows["c"] == {"robot_id": "c", "s_m": None, "off_m": 0.5, "state": "off_loop"}
    assert platoon(loop, {"solo": (0.5, 0.0)})[0]["state"] == "alone"


def test_a_broken_loop_is_refused():
    with pytest.raises(ValueError, match="breaks"):
        Loop(square(), ["AB", "CD"])


def test_the_route_shows_the_active_loop_and_never_dispatches():
    from fastapi.testclient import TestClient
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.site_map_store import SiteMapStore
    from fleet.swarm.robots import RobotEndpoint

    store = SiteMapStore()
    client = TestClient(create_app(FleetConsole([RobotEndpoint("rosy_60", "http://x", "t")], [FakeRobot("rosy_60")]),
                                   console_token="op", site_maps=store))
    auth = {"Authorization": "Bearer op"}
    if store.active() is None:
        assert client.get("/api/fleet/platoon", headers=auth).json()["detail"]["code"] == "NO_ACTIVE_MAP"
    draft = store.save_draft(square(), expected_revision=None, principal_id="op")
    store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)
    body = client.get("/api/fleet/platoon", headers=auth).json()
    assert body["dispatch"] is False and body["robots"] == []      # nobody localized
    assert sorted(body["loop"]["edges"]) == ["AB", "BC", "CD", "DA"] and body["loop"]["perimeter_m"] == 4.0
    assert body["speed"]["rows"][-1][1] > 0 and body["speed"]["curve_caps_measured"] is False   # a loop, no end stop
    assert client.get("/api/fleet/platoon").status_code == 401


@pytest.fixture
def platoon_app():
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.site_map_store import SiteMapStore
    from fleet.swarm.robots import RobotEndpoint

    store = SiteMapStore()
    draft = store.save_draft(square(), expected_revision=None, principal_id="op")
    store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)
    app = create_app(FleetConsole([RobotEndpoint("r1", "http://x", "t")], [FakeRobot("r1")]),
                     console_token="op", site_maps=store)
    yield app, store
    store.close()


@pytest.mark.parametrize("cancel_first", [False, True])
def test_platoon_computation_yields_and_concurrent_readers_share_it(platoon_app, monkeypatch, cancel_first):
    asyncio.run(_check_concurrent_readers(platoon_app, monkeypatch, cancel_first))


async def _check_concurrent_readers(platoon_app, monkeypatch, cancel_first):
    from fleet import lane_progress

    app, _ = platoon_app
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def slow_loop(site):
        calls.append(site)
        started.set()
        try:
            assert release.wait(5), "platoon computation blocked the HTTP event loop"
            return main_loop(site)
        finally:
            finished.set()

    monkeypatch.setattr(lane_progress, "main_loop", slow_loop)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fleet",
                                 headers={"Authorization": "Bearer op"}) as client:
        first = asyncio.create_task(client.get("/api/fleet/platoon"))
        second = None
        try:
            assert await asyncio.to_thread(started.wait, 5)
            # This authenticated request must complete while the geometry worker is still held.
            assert (await client.get("/api/fleet/session")).status_code == 200
            assert not finished.is_set()
            second = asyncio.create_task(client.get("/api/fleet/platoon"))
            await asyncio.sleep(0)
            if cancel_first:
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
        finally:
            release.set()
            results = await asyncio.gather(first, *([second] if second else []), return_exceptions=True)
        if cancel_first:
            assert isinstance(results.pop(0), asyncio.CancelledError)
        assert all(isinstance(result, httpx.Response) and result.status_code == 200 for result in results)
        assert (await client.get("/api/fleet/platoon")).status_code == 200
        assert len(calls) == 1


@pytest.mark.parametrize("no_loop", [False, True])
def test_platoon_caches_geometry_per_version_but_reads_current_pose(platoon_app, monkeypatch, no_loop):
    asyncio.run(_check_cached_geometry(platoon_app, monkeypatch, no_loop))


async def _check_cached_geometry(platoon_app, monkeypatch, no_loop):
    from fleet import lane_progress
    from fleet.server import platoon_geometry

    app, store = platoon_app
    calls, speed_calls = [], []
    real_speed_table = platoon_geometry.speed_table

    def counted_loop(site):
        calls.append(site)
        return None if no_loop else main_loop(site)

    def counted_speed(*args, **kwargs):
        speed_calls.append(args)
        return real_speed_table(*args, **kwargs)

    pose = SimpleNamespace(state="LOCALIZED", x=0.2, y=0.0)
    monkeypatch.setattr(lane_progress, "main_loop", counted_loop)
    monkeypatch.setattr(platoon_geometry, "speed_table", counted_speed)
    monkeypatch.setattr(app.state.map_pose, "arbitrated_pose", lambda _: pose)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fleet",
                                 headers={"Authorization": "Bearer op"}) as client:
        first = await client.get("/api/fleet/platoon")
        pose.x = 0.7
        second = await client.get("/api/fleet/platoon")
        assert first.status_code == second.status_code == (404 if no_loop else 200)
        assert len(calls) == 1 and len(speed_calls) == (0 if no_loop else 1)
        if no_loop:
            assert second.json()["detail"]["code"] == "NO_LOOP"
        else:
            assert first.json()["robots"][0]["s_m"] == pytest.approx(0.2)
            assert second.json()["robots"][0]["s_m"] == pytest.approx(0.7)
            assert second.json()["dispatch"] is False
        changed = square().model_dump(by_alias=True)
        for edge in changed["edges"]:
            edge["speed_cap_mps"] = 0.1
        draft = store.save_draft(SiteMap.model_validate(changed), expected_revision=None, principal_id="op")
        store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)
        updated = await client.get("/api/fleet/platoon")
        assert updated.status_code == second.status_code
        assert len(calls) == 2 and len(speed_calls) == (0 if no_loop else 2)
        if not no_loop:
            assert updated.json()["map_version"] != second.json()["map_version"]
            assert updated.json()["speed"] != second.json()["speed"]


def test_failed_platoon_geometry_is_retried(platoon_app, monkeypatch):
    from fastapi.testclient import TestClient
    from fleet import lane_progress

    app, _ = platoon_app
    calls = []

    def transient_failure(site):
        calls.append(site)
        if len(calls) == 1:
            raise ValueError("transient computation failure")
        return main_loop(site)

    monkeypatch.setattr(lane_progress, "main_loop", transient_failure)
    with TestClient(app, raise_server_exceptions=False) as client:
        auth = {"Authorization": "Bearer op"}
        assert client.get("/api/fleet/platoon", headers=auth).status_code == 500
        assert client.get("/api/fleet/platoon", headers=auth).status_code == 200
        assert client.get("/api/fleet/platoon", headers=auth).status_code == 200
        assert len(calls) == 2
