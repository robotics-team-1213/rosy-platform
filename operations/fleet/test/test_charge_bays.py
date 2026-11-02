"""D-941 5/7: charge bay plan - who goes to which bay, USB connection by voltage rise, leaving by estimate."""
from fleet.charge_bays import AT_BAY_M, SETTLE_S, Bay, ChargeBays, RobotView

BAYS = [Bay("C1", -0.414, 0.47), Bay("C2", -0.190, 0.47), Bay("C3", 0.032, 0.47)]


def robot(rid, percent, pose=None, *, volts=None, online=True, on_trip=False):
    return RobotView(rid, online, percent, volts, pose, on_trip)


def actions(plan):
    return {a["robot_id"]: a for a in plan["actions"]}


def test_low_robots_get_free_bays_lowest_battery_first_and_nothing_is_dispatched():
    bays = ChargeBays()
    fleet = [robot("a", 14.0), robot("b", 9.0), robot("c", 50.0), robot("d", 12.0, on_trip=True)]
    bays.observe(0.0, fleet, BAYS)
    plan = bays.plan(fleet, BAYS)
    got = actions(plan)
    assert plan["dispatch"] is False
    assert (got["b"]["action"], got["b"]["bay"]) == ("go", "C1")
    assert (got["a"]["action"], got["a"]["bay"]) == ("go", "C2")
    assert got["d"]["action"] == "after_trip" and "c" not in got
    assert [r["state"] for r in plan["bays"]] == ["planned", "planned", "free"]


def test_an_occupied_bay_is_not_offered_and_a_full_zone_waits():
    bays = ChargeBays()
    parked = [robot(f"p{i}", 60.0, (b.x, b.y)) for i, b in enumerate(BAYS)]
    fleet = [*parked, robot("low", 10.0)]
    bays.observe(0.0, fleet, BAYS)
    assert actions(bays.plan(fleet, BAYS))["low"] == {"robot_id": "low", "action": "wait", "reason": "no_free_bay"}


def test_a_voltage_rise_means_connected_and_no_rise_asks_to_reseat():
    at_c2 = (BAYS[1].x + AT_BAY_M / 2, BAYS[1].y)
    bays = ChargeBays()
    bays.observe(0.0, [robot("a", 14.0, at_c2, volts=7.40)], BAYS)
    assert actions(bays.plan([robot("a", 14.0, at_c2)], BAYS))["a"]["reason"] == "connecting"
    bays.observe(SETTLE_S, [robot("a", 14.0, at_c2, volts=7.41)], BAYS)
    assert actions(bays.plan([robot("a", 14.0, at_c2)], BAYS))["a"]["action"] == "reseat"
    bays.observe(SETTLE_S + 5, [robot("a", 60.0, at_c2, volts=7.47)], BAYS)
    row = actions(bays.plan([robot("a", 60.0, at_c2)], BAYS))["a"]
    assert (row["action"], row["reason"], row["arrived_percent"]) == ("stay", "charge_rate_not_measured", 14.0)


def test_leaving_uses_the_arrival_percent_and_the_measured_rate_not_the_charger_voltage():
    at_c1 = (BAYS[0].x, BAYS[0].y)
    bays = ChargeBays(rate_pct_per_min=2.0)
    bays.observe(0.0, [robot("a", 14.0, at_c1, volts=7.40)], BAYS)
    bays.observe(10.0, [robot("a", 95.0, at_c1, volts=8.30)], BAYS)   # charger holds the pack high
    assert actions(bays.plan([robot("a", 95.0, at_c1)], BAYS))["a"]["action"] == "stay"
    bays.observe(10.0 + 33 * 60, [robot("a", 95.0, at_c1, volts=8.35)], BAYS)
    row = actions(bays.plan([robot("a", 95.0, at_c1)], BAYS))["a"]
    assert (row["action"], row["estimated_percent"]) == ("leave", 80.0)


def test_leaving_the_bay_forgets_the_visit():
    bays = ChargeBays()
    bays.observe(0.0, [robot("a", 14.0, (BAYS[0].x, BAYS[0].y), volts=7.4)], BAYS)
    bays.observe(1.0, [robot("a", 70.0, (0.5, -0.2))], BAYS)
    assert bays.plan([robot("a", 70.0, (0.5, -0.2))], BAYS)["bays"][0]["state"] == "free"


def test_the_route_shows_the_active_maps_bays_and_never_dispatches():
    from fastapi.testclient import TestClient
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.site_map_store import SiteMapStore
    from fleet.site_map import SiteMap
    from fleet.swarm.robots import RobotEndpoint

    store = SiteMapStore()
    client = TestClient(create_app(FleetConsole([RobotEndpoint("rosy_60", "http://x", "t")], [FakeRobot("rosy_60")]),
                                   console_token="op", site_maps=store))
    auth = {"Authorization": "Bearer op"}
    if store.active() is None:
        assert client.get("/api/fleet/charge-bays", headers=auth).json()["detail"]["code"] == "NO_ACTIVE_MAP"
    site = SiteMap.model_validate({
        "schema": "rosy.site_map/1", "map_id": "bays_test",
        "places": [{"id": "P1", "name": "칸 앞", "x": -0.414, "y": 0.022},
                   {"id": "C1", "name": "충전 칸", "x": -0.414, "y": 0.47, "kind": "charge", "yaw": -1.5708}],
        "edges": [{"id": "bay_1", "from": "P1", "to": "C1", "polyline": [[-0.414, 0.022], [-0.414, 0.47]],
                   "direction": "two_way", "width_m": 0.18, "speed_cap_mps": 0.05}]})
    draft = store.save_draft(site, expected_revision=None, principal_id="op")
    store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)
    body = client.get("/api/fleet/charge-bays", headers=auth).json()
    assert body["dispatch"] is False and [(b["bay"], b["state"]) for b in body["bays"]] == [("C1", "free")]
    assert client.get("/api/fleet/charge-bays").status_code == 401
