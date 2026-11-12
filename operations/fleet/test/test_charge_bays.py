"""D-941 5/7: charge bay plan - who goes to which bay, USB connection by voltage rise, leaving by estimate."""
from fleet.charge_bays import AT_BAY_M, LEAVE_CONFIRM_S, SETTLE_S, Bay, ChargeBays, RobotView

BAYS = [Bay("C1", -0.414, 0.47), Bay("C2", -0.190, 0.47), Bay("C3", 0.032, 0.47)]


OUT = (0.5, -0.2)   # localized, outside every bay


def robot(rid, percent, pose=OUT, *, volts=None, online=True, on_trip=False):
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
    bays.observe(1.0, [robot("a", 70.0, OUT)], BAYS)
    assert bays.plan([robot("a", 70.0, OUT)], BAYS)["bays"][0]["state"] == "arrived"   # one reading is not leaving
    bays.observe(1.0 + LEAVE_CONFIRM_S, [robot("a", 70.0, OUT)], BAYS)
    assert bays.plan([robot("a", 70.0, OUT)], BAYS)["bays"][0]["state"] == "free"


def test_losing_pose_or_link_never_frees_the_bay_it_shows_unknown_and_offers_it_to_nobody():
    at_c1 = (BAYS[0].x, BAYS[0].y)
    for lost in (robot("a", 14.0, None), robot("a", 14.0, at_c1, online=False), None):   # None: left the roster
        bays = ChargeBays()
        bays.observe(0.0, [robot("a", 14.0, at_c1, volts=7.40)], BAYS)
        fleet = [lost] if lost else []
        bays.observe(5.0, fleet, BAYS)
        low = robot("low", 9.0)
        plan = bays.plan([*fleet, low], BAYS)
        assert (plan["bays"][0]["state"], plan["bays"][0]["robot_id"]) == ("unknown", "a")
        assert actions(plan)["low"]["bay"] == "C2"                       # never the unknown bay
        if lost:
            assert actions(plan)["a"] == {"robot_id": "a", "bay": "C1", "arrived_percent": 14.0, "in_bay_s": 5.0,
                                          "action": "stay", "reason": "pose_unknown"}


def test_a_trusted_pose_elsewhere_frees_the_bay_and_the_same_bay_again_keeps_the_visit_without_blind_time():
    at_c1 = (BAYS[0].x, BAYS[0].y)
    bays = ChargeBays(rate_pct_per_min=2.0)
    bays.observe(0.0, [robot("a", 14.0, at_c1, volts=7.40)], BAYS)
    bays.observe(10.0, [robot("a", 14.0, at_c1, volts=7.50)], BAYS)          # connected at 10 s
    bays.observe(20.0, [robot("a", 14.0, None)], BAYS)                        # pose lost: unknown, still connected
    assert bays._visits["a"].connected_at == 10.0
    bays.observe(620.0, [robot("a", 14.0, at_c1, volts=7.50)], BAYS)          # seen again after 600 s blind
    row = actions(bays.plan([robot("a", 14.0, at_c1)], BAYS))["a"]
    assert row["connected_s"] == 10.0 and row["estimated_percent"] == round(14.0 + 2.0 * 10.0 / 60.0, 1)
    bays.observe(621.0, [robot("a", 70.0, OUT)], BAYS)
    bays.observe(621.0 + LEAVE_CONFIRM_S, [robot("a", 70.0, OUT)], BAYS)
    assert bays.plan([robot("a", 70.0, OUT)], BAYS)["bays"][0]["state"] == "free"


def test_a_single_stray_pose_beyond_the_bay_does_not_end_the_visit_or_the_connection():
    at_c1 = (BAYS[0].x, BAYS[0].y)
    bays = ChargeBays()
    bays.observe(0.0, [robot("a", 14.0, at_c1, volts=7.40)], BAYS)
    bays.observe(10.0, [robot("a", 14.0, at_c1, volts=7.50)], BAYS)
    bays.observe(11.0, [robot("a", 14.0, OUT)], BAYS)                 # one glitch
    bays.observe(12.0, [robot("a", 14.0, at_c1, volts=7.50)], BAYS)   # back: the dwell restarts
    bays.observe(12.0 + LEAVE_CONFIRM_S - 1, [robot("a", 14.0, OUT)], BAYS)
    assert bays._visits["a"].connected_at == 10.0
    assert bays.plan([robot("a", 14.0, at_c1)], BAYS)["bays"][0]["state"] == "charging"


def test_blind_time_before_the_connection_is_not_subtracted_from_the_charge_time():
    at_c1 = (BAYS[0].x, BAYS[0].y)
    bays = ChargeBays(rate_pct_per_min=2.0)
    bays.observe(0.0, [robot("a", 14.0, at_c1, volts=7.40)], BAYS)
    bays.observe(10.0, [robot("a", 14.0, None)], BAYS)                 # blind 10..100 s, before any connection
    bays.observe(100.0, [robot("a", 14.0, at_c1, volts=7.40)], BAYS)
    bays.observe(101.0, [robot("a", 14.0, at_c1, volts=7.50)], BAYS)   # connected at 101 s
    bays.observe(161.0, [robot("a", 14.0, at_c1, volts=7.50)], BAYS)
    assert actions(bays.plan([robot("a", 14.0, at_c1)], BAYS))["a"]["connected_s"] == 60.0


def test_a_bay_nobody_is_known_to_hold_reads_unknown_while_any_robot_is_offline_or_unlocated():
    """After a Fleet restart the visits are gone: an offline robot may still sit in a bay."""
    bays = ChargeBays()
    fleet = [robot("ok", 60.0), robot("dead", 50.0, None, online=False), robot("low", 9.0)]
    bays.observe(0.0, fleet, BAYS)
    plan = bays.plan(fleet, BAYS)
    assert [r["state"] for r in plan["bays"]] == ["unknown"] * 3
    assert actions(plan)["low"] == {"robot_id": "low", "action": "wait", "reason": "bay_unknown"}
    fleet = [robot("ok", 60.0), robot("low", 9.0)]                     # the dead one left the roster
    plan = bays.plan(fleet, BAYS)
    assert [r["state"] for r in plan["bays"]] == ["planned", "free", "free"]
    assert actions(plan)["low"]["action"] == "go"


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
    assert body["dispatch"] is False and [(b["bay"], b["state"]) for b in body["bays"]] == [("C1", "unknown")]
    assert client.get("/api/fleet/charge-bays").status_code == 401

    import asyncio
    app = client.app
    seen = []
    app.state.charge_bays.observe = lambda now, robots, bays: seen.append(([r.robot_id for r in robots], bays))
    asyncio.run(app.state.charge_bays_tick())    # the background loop's step, no page open
    assert seen == [(["rosy_60"], [Bay("C1", -0.414, 0.47)])]


def test_centerline_evaluation_flags_misaligned_dock_for_immediate_reseat():
    import math
    from fleet.routing.graph import build_graph
    from fleet.site_map import SiteMap

    site = SiteMap.model_validate({
        "schema": "rosy.site_map/1", "map_id": "bays_eval",
        "places": [{"id": "P1", "name": "칸 앞", "x": -0.414, "y": 0.022},
                   {"id": "C1", "name": "충전 칸", "x": -0.414, "y": 0.470, "kind": "charge", "yaw": -1.5708}],
        "edges": [{"id": "bay_1", "from": "P1", "to": "C1", "polyline": [[-0.414, 0.022], [-0.414, 0.470]],
                   "direction": "two_way", "width_m": 0.18, "speed_cap_mps": 0.05}]})
    graph = build_graph(site)
    bays = ChargeBays()

    # Arrived at C1 but skewed by 12 deg -> immediate reseat (misaligned_on_bay), no 30s wait
    skewed = RobotView("a", True, 14.0, 7.40, (-0.414, 0.460), False, -math.pi / 2 + math.radians(12.0))
    bays.observe(0.0, [skewed], BAYS[:1])
    plan = bays.plan([skewed], BAYS[:1], graph=graph)
    act = actions(plan)["a"]
    assert act["action"] == "reseat" and act["reason"] == "misaligned_on_bay"
    assert act["docking"]["verdict"] == "RETRY_FROM_P"

    # Re-aligned at C1 within tolerance -> connecting (CONTACT_STOP)
    aligned = RobotView("a", True, 14.0, 7.40, (-0.414, 0.460), False, -math.pi / 2 + math.radians(1.0))
    bays.observe(2.0, [aligned], BAYS[:1])
    plan_ok = bays.plan([aligned], BAYS[:1], graph=graph)
    act_ok = actions(plan_ok)["a"]
    assert act_ok["action"] == "stay" and act_ok["reason"] == "connecting"
    assert act_ok["docking"]["verdict"] == "CONTACT_STOP"


def _world_261026_charge_graph():
    from fleet.routing.graph import build_graph
    from fleet.site_map import SiteMap

    site = SiteMap.model_validate({
        "schema": "rosy.site_map/1",
        "map_id": "world_261026",
        "places": [
            {"id": "C1", "name": "충전 1", "x": -0.414, "y": 0.47, "kind": "charge", "yaw": -1.5708},
            {"id": "C2", "name": "충전 2", "x": -0.190, "y": 0.47, "kind": "charge", "yaw": -1.5708},
            {"id": "C3", "name": "충전 3", "x": 0.032, "y": 0.47, "kind": "charge", "yaw": -1.5708},
            {"id": "P1", "name": "칸 1 앞", "x": -0.414, "y": 0.022},
            {"id": "P2", "name": "칸 2 앞", "x": -0.190, "y": 0.022},
            {"id": "P3", "name": "칸 3 앞", "x": 0.032, "y": 0.022},
            {"id": "S1", "name": "충전 출구 정지선", "x": -0.687, "y": -0.126},
            {"id": "S2", "name": "충전 입구 정지선", "x": 0.18, "y": -0.126},
            {"id": "J_in", "name": "충전 입구 분기", "x": 0.18, "y": -0.312},
            {"id": "J_out", "name": "충전 출구 합류", "x": -0.687, "y": -0.266},
        ],
        "edges": [
            {"id": "bay_1", "from": "P1", "to": "C1", "polyline": [[-0.414, 0.022], [-0.414, 0.47]],
             "direction": "two_way", "width_m": 0.18, "speed_cap_mps": 0.05},
            {"id": "bay_2", "from": "P2", "to": "C2", "polyline": [[-0.190, 0.022], [-0.190, 0.47]],
             "direction": "two_way", "width_m": 0.18, "speed_cap_mps": 0.05},
            {"id": "bay_3", "from": "P3", "to": "C3", "polyline": [[0.032, 0.022], [0.032, 0.47]],
             "direction": "two_way", "width_m": 0.18, "speed_cap_mps": 0.05},
            {"id": "bar_32", "from": "P3", "to": "P2", "polyline": [[0.032, 0.022], [-0.190, 0.022]],
             "direction": "one_way", "width_m": 0.18, "speed_cap_mps": 0.06},
            {"id": "bar_21", "from": "P2", "to": "P1", "polyline": [[-0.190, 0.022], [-0.414, 0.022]],
             "direction": "one_way", "width_m": 0.18, "speed_cap_mps": 0.06},
            {"id": "park_in", "from": "J_in", "to": "P3",
             "polyline": [[0.18, -0.312], [0.18, -0.126], [0.11, 0.022], [0.032, 0.022]],
             "direction": "one_way", "width_m": 0.18, "speed_cap_mps": 0.08},
            {"id": "park_out", "from": "P1", "to": "S1",
             "polyline": [[-0.414, 0.022], [-0.60, 0.022], [-0.687, -0.126]],
             "direction": "one_way", "width_m": 0.18, "speed_cap_mps": 0.08},
            {"id": "exit_merge", "from": "S1", "to": "J_out",
             "polyline": [[-0.687, -0.126], [-0.687, -0.266]],
             "direction": "one_way", "width_m": 0.18, "speed_cap_mps": 0.08},
        ],
    })
    return site, build_graph(site, version=16)


def test_road_path_follows_road_polylines_and_sequential_exit_nearest_departure():
    import math
    from fleet.routing.road_path import plan_road_path

    _site, graph = _world_261026_charge_graph()
    # 1. Road-constrained Nav2 path from J_in to C1 follows park_in -> bar_32 -> bar_21 -> bay_1
    approach = plan_road_path(graph, (0.18, -0.312, math.pi / 2), "C1")
    assert approach.edges == ("park_in", "bar_32", "bar_21", "bay_1")
    assert approach.places == ("P3", "P2", "P1", "C1")
    assert len(approach.waypoints_site) >= 8

    # 2. Sequential departure: 3 robots in C1, C2, C3 finish charging simultaneously.
    # Even if C3 connected earliest, exit_nearest releases C1 (0.783 m to S1) first,
    # then C2 (1.007 m), then C3 (1.229 m).
    bays = ChargeBays(rate_pct_per_min=10.0)
    r1 = RobotView("rosy_01", True, 50.0, 7.40, (-0.414, 0.47), False, -math.pi / 2)
    r2 = RobotView("rosy_02", True, 50.0, 7.40, (-0.190, 0.47), False, -math.pi / 2)
    r3 = RobotView("rosy_03", True, 50.0, 7.40, (0.032, 0.47), False, -math.pi / 2)
    bays.observe(0.0, [r1, r2, r3], BAYS)
    # Connect r3 first (t=1), r2 second (t=2), r1 third (t=3)
    bays.observe(1.0, [r1, r2, RobotView("rosy_03", True, 50.0, 7.50, r3.pose, False, r3.yaw)], BAYS)
    bays.observe(2.0, [r1, RobotView("rosy_02", True, 50.0, 7.50, r2.pose, False, r2.yaw),
                       RobotView("rosy_03", True, 50.0, 7.50, r3.pose, False, r3.yaw)], BAYS)
    bays.observe(3.0, [RobotView("rosy_01", True, 50.0, 7.50, r1.pose, False, r1.yaw),
                       RobotView("rosy_02", True, 50.0, 7.50, r2.pose, False, r2.yaw),
                       RobotView("rosy_03", True, 50.0, 7.50, r3.pose, False, r3.yaw)], BAYS)
    # At t=300s, all 3 are at 100% (>= 80% leave_percent)
    charged_views = [
        RobotView("rosy_01", True, 50.0, 7.50, r1.pose, False, r1.yaw),
        RobotView("rosy_02", True, 50.0, 7.50, r2.pose, False, r2.yaw),
        RobotView("rosy_03", True, 50.0, 7.50, r3.pose, False, r3.yaw),
    ]
    bays.observe(300.0, charged_views, BAYS)
    plan1 = bays.plan(charged_views, BAYS, graph=graph)
    act1 = actions(plan1)
    assert act1["rosy_01"]["action"] == "leave" and act1["rosy_01"]["exit_rank"] == 1, (
        [(k, v.get("action"), v.get("reason"), v.get("exit_rank")) for k, v in act1.items()],
        plan1.get("corridor"),
    )
    assert act1["rosy_02"]["action"] == "stay" and act1["rosy_02"]["reason"] == "queued_for_exit"
    assert act1["rosy_02"]["ahead"] == ["rosy_01"] and act1["rosy_02"]["exit_rank"] == 2
    assert act1["rosy_03"]["action"] == "stay" and act1["rosy_03"]["reason"] == "queued_for_exit"
    assert act1["rosy_03"]["ahead"] == ["rosy_01", "rosy_02"] and act1["rosy_03"]["exit_rank"] == 3
    assert plan1["corridor"]["granted_robot_ids"] == ["rosy_01"]
    assert [s["bay"] for s in plan1["corridor"]["station_order"]] == ["C1", "C2", "C3"]

    # Step 2: rosy_01 leaves C1 and is moving on park_out (-0.50, 0.022) toward S1.
    # Even after LEAVE_CONFIRM_S (t=305s), while rosy_01 is still in the corridor, rosy_02 and rosy_03 wait (corridor_busy).
    moving_r1 = [
        RobotView("rosy_01", True, 85.0, 7.45, (-0.50, 0.022), False, math.pi),
        charged_views[1],
        charged_views[2],
    ]
    bays.observe(301.0, moving_r1, BAYS)
    bays.observe(305.0, moving_r1, BAYS)
    plan2 = bays.plan(moving_r1, BAYS, graph=graph)
    act2 = actions(plan2)
    assert plan2["corridor"]["active_departing"] == ["rosy_01"]
    assert act2["rosy_02"]["action"] == "stay" and act2["rosy_02"]["reason"] == "corridor_busy"
    assert act2["rosy_03"]["action"] == "stay" and act2["rosy_03"]["reason"] == "corridor_busy"

    # Step 3: rosy_01 clears S1 onto J_out (-0.687, -0.266). Now rosy_02 (C2) is granted leave, rosy_03 waits!
    cleared_r1 = [
        RobotView("rosy_01", True, 85.0, 7.45, (-0.687, -0.266), False, -math.pi / 2),
        charged_views[1],
        charged_views[2],
    ]
    bays.observe(306.0, cleared_r1, BAYS)
    plan3 = bays.plan(cleared_r1, BAYS, graph=graph)
    act3 = actions(plan3)
    assert plan3["corridor"]["active_departing"] == []
    assert act3["rosy_02"]["action"] == "leave" and act3["rosy_02"]["ahead"] == []
    assert act3["rosy_03"]["action"] == "stay" and act3["rosy_03"]["reason"] == "queued_for_exit"
    assert act3["rosy_03"]["ahead"] == ["rosy_02"]

    # Step 4: rosy_02 leaves C2 and clears S1 -> rosy_03 (C3) is granted leave!
    cleared_r2 = [
        cleared_r1[0],
        RobotView("rosy_02", True, 85.0, 7.45, (-0.687, -0.266), False, -math.pi / 2),
        charged_views[2],
    ]
    bays.observe(307.0, cleared_r2, BAYS)
    bays.observe(311.0, cleared_r2, BAYS)
    plan4 = bays.plan(cleared_r2, BAYS, graph=graph)
    act4 = actions(plan4)
    assert act4["rosy_03"]["action"] == "leave" and act4["rosy_03"]["ahead"] == []
    assert act4["rosy_03"]["departure_route"]["edges"] == ["bay_3", "bar_32", "bar_21", "park_out"]


def test_road_nav2_http_route_dispatches_along_road_polyline(tmp_path):
    from hashlib import sha256
    from fastapi.testclient import TestClient
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.site_map_store import SiteMapStore
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import RobotEndpoint

    site, _graph = _world_261026_charge_graph()
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    draft = store.save_draft(site, expected_revision=None, principal_id="op")
    store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)

    bot = FakeRobot(
        "rosy_60",
        state={
            "robot_id": "rosy_60",
            "pose": {"x": 0.18, "y": -0.312, "yaw": 1.5708},
            "localization": {"state": "LOCALIZED", "pose_frame": "map"},
        },
    )
    users = {sha256(b"op").hexdigest(): {"principal_id": "bob", "role": "operator"}}
    console = FleetConsole([RobotEndpoint("rosy_60", "http://x", "t")], [bot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    client = TestClient(create_app(console, task_service=tasks, site_users=users, site_maps=store))
    auth = {"Authorization": "Bearer op", "Idempotency-Key": "road-nav2-test-1"}

    res = client.post(
        "/api/fleet/robots/rosy_60/road-nav2",
        headers=auth,
        json={"x": -0.414, "y": 0.47, "yaw": -1.5708, "place_id": "C1", "label": "충전 1"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["dispatched"] is True and (body["accepted"] or body["queued"])
    assert body["edges"] == ["park_in", "bar_32", "bar_21", "bay_1"]
    assert body["places"] == ["P3", "P2", "P1", "C1"]
    assert len(body["waypoints_site"]) >= 8
