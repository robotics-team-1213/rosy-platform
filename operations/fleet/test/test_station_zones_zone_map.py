"""Station-zones zone map: no stored zone coordinate, the vehicle footprint, fixed areas and the overlap check."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.pipeline.station_zones import (
    active_lanes,
    area_conflicts,
    load_station_zones,
    parse_areas,
    parse_vehicle,
    save_station_zones_yaml,
)
from fleet.routing.graph import build_graph
from fleet.server.sitemap.pipeline_routes import install_pipeline_routes
from fleet.site_map import SiteMap

ROOT = Path(__file__).resolve().parents[3]
# The override file is redirected where install_pipeline_routes resolves it. This file imports that
# function from its holder module, so the patch must name the same module: patching the
# fleet.server.pipeline_routes alias instead left the real /tmp/station_zones.yaml written on a test host.
STORAGE_DIR = "fleet.server.sitemap.pipeline_routes._storage_dir"


def square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_zones_carry_no_coordinate_and_the_vehicle_is_the_profile():
    zones = load_station_zones()
    for zone in zones["zones_by_id"].values():
        assert zone["place_id"], zone["id"]
        assert not {"x", "y", "yaw_deg"} & zone.keys(), zone["id"]
    geometry = yaml.safe_load(
        (ROOT / "middleware/devices/pinky/profile/config/geometry.yaml").read_text(encoding="utf-8"))
    assert zones["vehicle"] == {"front_m": geometry["footprint"]["front_x_m"],
                                "rear_m": geometry["cargo_tray"]["rear_x_m"],
                                "half_width_m": geometry["footprint"]["half_width_m"]}
    assert zones["area_errors"] == []
    assert {area["zone_id"] for area in zones["areas"]} == {"", "yard", "temp_a", "temp_b", "stand"}
    assert area_conflicts(zones["areas"]) == []


def test_area_conflicts_see_partial_overlaps_and_lane_cuts_but_not_touching_or_nesting():
    def area(name, polygon):
        return {"id": name, "polygon": polygon}

    assert area_conflicts([area("A", square(0, 0, 1, 1)), area("B", square(1, 0, 2, 1))]) == []
    assert area_conflicts([area("A", square(0, 0, 1, 1)), area("B", square(0.2, 0.2, 0.8, 0.8))]) == []
    assert area_conflicts([area("A", square(0, 0, 1, 1)), area("B", square(0.5, 0, 1.5, 1))]) == [
        "area A partially overlaps area B"]
    # Two rectangles overlapping in a third one: no vertex lies inside the other and edges meet in T-junctions.
    assert area_conflicts([area("A", square(0, 0, 0.5, 0.3)), area("B", square(0.4, 0, 0.9, 0.3))]) == [
        "area A partially overlaps area B"]
    lane = ("lane_1", [(0, -1), (0, 2)], 0.2)  # centreline x = 0, half width 0.1
    assert area_conflicts([area("A", square(0.085, 0, 1, 1))], [lane]) == []
    assert area_conflicts([area("A", square(0.075, 0, 1, 1))], [lane]) == [
        "area A overlaps lane lane_1 by 25 mm (more than 20 mm)"]


@pytest.mark.parametrize("raw", [
    [{"id": "A", "polygon": [[0, 0], [1, 0]]}],
    [{"id": "A", "polygon": [[0, 0], [1, 0], [2, 0]]}],
    [{"id": "A", "polygon": [[0, 0], [1, 0], [1, 1], [0, float("inf")]]}],
    [{"id": "A", "kind": "robot", "polygon": [[0, 0], [1, 0], [1, 1]]}],
    [{"id": "A", "status": "guess", "polygon": [[0, 0], [1, 0], [1, 1]]}],
    [{"id": "A", "polygon": [[0, 0], [1, 0], [1, 1]]}, {"id": "A", "polygon": [[2, 2], [3, 2], [3, 3]]}],
    [{"id": "A", "height_m": 0, "polygon": [[0, 0], [1, 0], [1, 1]]}],
    # Concave or self-crossing rings: the overlap check cuts with a convex clip, so both inputs must be convex.
    [{"id": "L", "polygon": [[0, 0], [2, 0], [2, 2], [1, 2], [1, 1], [0, 1]]}],
    [{"id": "BOOMERANG", "polygon": [[0, 0], [2, 0], [1, 1], [2, 2], [0, 2]]}],
])
def test_malformed_areas_are_refused(raw):
    with pytest.raises(ValueError):
        parse_areas(raw)


def test_vehicle_needs_a_forward_front_a_rear_and_a_width():
    assert parse_vehicle(None) is None
    assert parse_vehicle({"front_m": 0.04, "rear_m": -0.13, "half_width_m": 0.05}) == {
        "front_m": 0.04, "rear_m": -0.13, "half_width_m": 0.05}
    for bad in ({"front_m": 0, "rear_m": -0.1, "half_width_m": 0.05},
                {"front_m": 0.04, "rear_m": 0.1, "half_width_m": 0.05},
                {"front_m": 0.04, "rear_m": -0.1, "half_width_m": "wide"}):
        with pytest.raises(ValueError):
            parse_vehicle(bad)


def test_save_refuses_an_area_over_a_lane_and_writes_nothing(tmp_path):
    target = tmp_path / "station_zones.yaml"
    lane = ("upper_east", [(0.745, -0.207), (0.3142, -0.2501)], 0.2)
    on_lane = ("staging_bays: []\nareas:\n  - id: ON_LANE\n"
               "    polygon: [[0.4, -0.3], [0.6, -0.3], [0.6, -0.2], [0.4, -0.2]]\n")
    with pytest.raises(ValueError, match="overlaps lane upper_east"):
        save_station_zones_yaml(on_lane, target, lanes=[lane])
    assert not target.exists()
    beside = ("staging_bays: []\nareas:\n  - id: BESIDE\n"
              "    polygon: [[0.4, 0.0], [0.6, 0.0], [0.6, 0.2], [0.4, 0.2]]\n")
    saved = save_station_zones_yaml(beside, target, lanes=[lane])
    assert [area["id"] for area in saved["areas"]] == ["BESIDE"]


def test_an_override_that_predates_the_zone_map_keeps_the_packaged_map(tmp_path):
    override = tmp_path / "station_zones.yaml"
    override.write_text("staging_bays:\n  - id: STG_ONLY\n    place_id: C2\n", encoding="utf-8")
    zones = load_station_zones(override)
    assert [zone["id"] for zone in zones["staging_bays"]] == ["STG_ONLY"]
    assert zones["export_stations"] == []  # the legacy keys still come from the override alone
    assert zones["vehicle"] and zones["areas"] and zones["area_errors"] == []


def test_active_lanes_follow_the_route_helper_and_treat_only_its_no_map_404_as_no_map():
    class NoActiveMap(Exception):
        status_code = 404
        detail = {"code": "NO_ACTIVE_MAP"}

    def no_map():
        raise NoActiveMap()

    assert active_lanes(no_map) == []

    class Other404(Exception):
        status_code = 404
        detail = {"code": "SOMETHING_ELSE"}

    class Fault(Exception):
        status_code = 500

    for error in (Other404, Fault):
        def broken(error=error):
            raise error()

        with pytest.raises(error):
            active_lanes(broken)
    edge = SimpleNamespace(id="e1", polyline=[(0, 0), (1, 0)], width_m=0.2)
    assert active_lanes(lambda: (7, SimpleNamespace(edges=[edge]), None, None)) == [("e1", [(0, 0), (1, 0)], 0.2)]


def test_station_zones_put_refuses_an_area_over_the_active_lane(tmp_path, monkeypatch):
    monkeypatch.setattr(STORAGE_DIR, lambda: tmp_path)
    site_map = SiteMap(map_id="zone-map-test", places=[
        {"id": "A", "name": "A", "x": 0, "y": 0, "kind": "junction"},
        {"id": "B", "name": "B", "x": 1, "y": 0, "kind": "junction"},
    ], edges=[{"id": "e1", "from": "A", "to": "B", "width_m": 0.2, "speed_cap_mps": 0.15,
               "polyline": [[0, 0], [1, 0]]}])
    graph = build_graph(site_map)
    maps = SimpleNamespace(active=lambda: (1, site_map, graph, None),
                           rules=SimpleNamespace(active_rules=lambda: None))
    app = FastAPI()
    app.state.site_maps = maps
    install_pipeline_routes(app, site_maps=maps)
    client = TestClient(app)

    on_lane = ("staging_bays: []\nareas:\n  - id: ON_LANE\n"
               "    polygon: [[0.2, -0.05], [0.4, -0.05], [0.4, 0.05], [0.2, 0.05]]\n")
    refused = client.put("/api/fleet/pipeline/station-zones", json={"yaml_text": on_lane})
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "INVALID_STATION_ZONES_YAML"
    assert not (tmp_path / "station_zones.yaml").exists()

    beside = ("staging_bays: []\nareas:\n  - id: BESIDE\n    name: beside\n"
              "    polygon: [[0.2, 0.3], [0.4, 0.3], [0.4, 0.5], [0.2, 0.5]]\n")
    assert client.put("/api/fleet/pipeline/station-zones", json={"yaml_text": beside}).status_code == 200
    listed = client.get("/api/fleet/pipeline/station-zones").json()["areas"]
    assert [area["id"] for area in listed] == ["BESIDE"]


def test_station_zones_put_without_an_active_map_saves_without_the_lane_check(tmp_path, monkeypatch):
    monkeypatch.setattr(STORAGE_DIR, lambda: tmp_path)
    maps = SimpleNamespace(active=lambda: None, rules=SimpleNamespace(active_rules=lambda: None))
    app = FastAPI()
    app.state.site_maps = maps
    install_pipeline_routes(app, site_maps=maps)
    client = TestClient(app)

    # No active map raises NO_ACTIVE_MAP in active_map(); the save keeps its earlier behaviour.
    text = ("staging_bays: []\nareas:\n  - id: ANYWHERE\n"
            "    polygon: [[0.2, -0.05], [0.4, -0.05], [0.4, 0.05], [0.2, 0.05]]\n")
    saved = client.put("/api/fleet/pipeline/station-zones", json={"yaml_text": text})
    assert saved.status_code == 200 and saved.json()["ok"] is True
    assert (tmp_path / "station_zones.yaml").read_text(encoding="utf-8") == text
    # The response is the merged view a following GET gives: the packaged vehicle, not the text's omission.
    again = client.get("/api/fleet/pipeline/station-zones").json()
    assert saved.json()["vehicle"] == again["vehicle"]
