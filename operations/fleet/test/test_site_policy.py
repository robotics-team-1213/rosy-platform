from fleet.routing.graph import build_graph
from fleet.site_map import SiteMap
from fleet.pipeline.site_policy import plan_site_road_trip, resolve_site_policy


def _world_261026():
    places = [
        ("C1", -0.414, 0.47, "charge"), ("C2", -0.190, 0.47, "charge"),
        ("C3", 0.032, 0.47, "charge"), ("P1", -0.414, 0.022, "park"),
        ("P2", -0.190, 0.022, "park"), ("P3", 0.032, 0.022, "park"),
        ("S1", -0.687, -0.126, "stop"), ("S2", 0.18, -0.126, "stop"),
        ("J_in", 0.18, -0.312, "junction"), ("J_out", -0.687, -0.266, "junction"),
    ]
    pairs = [
        ("bay_1", "P1", "C1", "two_way"), ("bay_2", "P2", "C2", "two_way"),
        ("bay_3", "P3", "C3", "two_way"), ("bar_32", "P3", "P2", "one_way"),
        ("bar_21", "P2", "P1", "one_way"), ("park_in", "J_in", "P3", "one_way"),
        ("park_out", "P1", "S1", "one_way"), ("exit_merge", "S1", "J_out", "one_way"),
    ]
    coords = {p[0]: p[1:3] for p in places}
    site = SiteMap.model_validate({
        "schema": "rosy.site_map/1", "map_id": "world_261026",
        "places": [{"id": i, "name": i, "x": x, "y": y, "kind": kind} for i, x, y, kind in places],
        "edges": [{"id": i, "from": a, "to": b,
                   "polyline": [coords[a], coords[b]], "direction": direction,
                   "width_m": 0.18, "speed_cap_mps": 0.08} for i, a, b, direction in pairs],
    })
    return site, build_graph(site, version=16)


def test_resolve_world_policy_topology_zones_and_exit_order():
    site, graph = _world_261026()
    policy = resolve_site_policy(site, graph)
    assert policy.bay_staging_places == {"C1": "P1", "C2": "P2", "C3": "P3"}
    assert policy.exit_gate_place == "S1"
    assert [row["bay"] for row in policy.to_dict(graph)["corridor"]["station_order"]] == ["C1", "C2", "C3"]
    assert policy.classify_edge_zone("bay_2") == "charge_bay"
    assert policy.classify_edge_zone("park_out") == "charge_corridor"
    assert policy.classify_edge_zone("exit_merge") == "charge_corridor"
    assert policy.classify_edge_zone("ordinary") == "main_loop"


def test_plan_site_road_trip_annotates_waypoints():
    site, graph = _world_261026()
    policy = resolve_site_policy(site, graph)
    trip = plan_site_road_trip(policy, graph, (0.18, -0.312, 1.57), "C1")
    assert trip["site_id"] == "world_261026"
    assert trip["zones"] == ["charge_corridor", "charge_bay"]
    assert {wp["speed_cap_mps"] for wp in trip["waypoints_site"] if wp["zone"] == "charge_bay"} == {0.05}
    assert all("zone" in wp and "speed_cap_mps" in wp for wp in trip["waypoints_site"])
