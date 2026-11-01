"""D-941 2: lane-progress gap, leader choice across the loop seam, follower speed."""
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
