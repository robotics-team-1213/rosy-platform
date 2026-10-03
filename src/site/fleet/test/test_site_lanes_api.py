"""D-375 console map-fit overlay: Fleet serves lane_graph polylines as display geometry only."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.cli import parse_args
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.site_lanes import (
    load_lane_graph, load_lane_paint, parse_lane_graph_flags, unmatched_map_ids,
)
from fleet.swarm.robots import RobotEndpoint

REPO = Path(__file__).resolve().parents[4]
LANE_GRAPH = REPO / "src/runtime/sensing/map/map_v2_fleet/lane_graph.yaml"
ROAD_LINES = REPO / "src/runtime/sensing/map/map_v2_fleet/meshes/road_lines.stl"
OPERATOR_TOKEN = "operator-secret"
SOURCE_TOKEN = "source-camera-secret"


def _source(source_id="ceiling-north", map_id="site-v1", token=SOURCE_TOKEN):
    return SightingSource(source_id=source_id, token=token, robot_ids=("rosy-pinky-8kcn",),
                          map_id=map_id, calibration_revision="cal-v3",
                          corner_marker_ids=(30, 31, 32, 33))


def _client(site_lanes, sources=(_source(),)):
    robot = FakeRobot("rosy-pinky-8kcn", state={"robot_id": "rosy-pinky-8kcn", "mode": "IDLE"})
    console = FleetConsole([RobotEndpoint("rosy-pinky-8kcn", "http://127.0.0.1:8080", "robot-rest")],
                           [robot])
    service = SightingService(list(sources), known_robot_ids=console.robot_ids) if sources else None
    return TestClient(create_app(console, sightings=service, console_token=OPERATOR_TOKEN,
                                 site_lanes=site_lanes))


def _auth(token=OPERATOR_TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_map_v2_fleet_lane_graph_becomes_segments_parking_and_roundabout():
    lanes = load_lane_graph(LANE_GRAPH)

    by_id = {line["id"]: line for line in lanes["polylines"]}
    assert {"east", "west", "ring_n", "ring_e", "ring_s", "ring_w", "parking", "roundabout"} <= set(by_id)
    assert by_id["east"]["kind"] == "segment" and by_id["east"]["closed"] is False
    assert by_id["roundabout"]["closed"] is True and len(by_id["roundabout"]["points"]) == 72
    assert by_id["parking"]["points"][0] == [-1.2696, 0.0]
    bounds = lanes["bounds_m"]
    # 2.81 x 1.26 m track: the centrelines sit inside it.
    assert -1.41 < bounds["min_x"] < bounds["max_x"] < 1.41
    assert -0.63 < bounds["min_y"] < bounds["max_y"] < 0.63
    assert len(lanes["lane_graph_sha256"]) == 64


def test_site_lanes_route_serves_polylines_with_the_sources_on_that_map():
    client = _client(parse_lane_graph_flags([str(LANE_GRAPH)]))

    response = client.get("/api/fleet/site-lanes", headers=_auth())

    assert response.status_code == 200, response.text
    entry = response.json()["maps"][0]
    assert entry["map_id"] is None  # no MAP_ID= prefix: applies to every map
    assert entry["frame"] == "map" and entry["units"] == "m"
    assert entry["source_ids"] == ["ceiling-north"]
    assert entry["polylines"] and entry["bounds_m"]
    assert SOURCE_TOKEN not in response.text and "token" not in response.text


def test_map_scoped_lane_graph_lists_only_that_maps_sources():
    sources = (_source(), _source("ceiling-south", map_id="other-map", token="other-secret"))
    client = _client(parse_lane_graph_flags([f"site-v1={LANE_GRAPH}"]), sources)

    entry = client.get("/api/fleet/site-lanes", headers=_auth()).json()["maps"][0]

    assert entry["map_id"] == "site-v1"
    assert entry["source_ids"] == ["ceiling-north"]


def test_site_lanes_is_404_without_a_lane_graph_and_needs_a_read_credential():
    assert _client(None).get("/api/fleet/site-lanes", headers=_auth()).json()["detail"]["code"] \
        == "NO_SITE_LANES"
    client = _client(parse_lane_graph_flags([str(LANE_GRAPH)]))
    assert client.get("/api/fleet/site-lanes").status_code == 401
    assert client.get("/api/fleet/site-lanes", headers=_auth(SOURCE_TOKEN)).status_code == 401


def test_site_lanes_work_without_any_sighting_config():
    client = _client(parse_lane_graph_flags([str(LANE_GRAPH)]), sources=())
    entry = client.get("/api/fleet/site-lanes", headers=_auth()).json()["maps"][0]
    assert entry["source_ids"] == []


def _graph(tmp_path, graph):
    path = tmp_path / "lane_graph.yaml"
    path.write_text(yaml.safe_dump(graph), encoding="utf-8")
    return path


@pytest.mark.parametrize("graph, message", [
    ({}, "segments"),
    ({"segments": {"a": {"points": [[0, 0]]}}}, "at least two"),
    ({"segments": {"a": {"points": [[0, 0], [1, "x"]]}}}, "finite"),
    ({"segments": {"a": {"points": [[0, 0], [1, float("nan")]]}}}, "finite"),
    ({"segments": {"a": {"points": [[0, 0], [1, 0]]}}, "roundabout": {"centre": [0, 0], "radius": -1}},
     "radius"),
])
def test_malformed_lane_graph_fails_at_load(tmp_path, graph, message):
    with pytest.raises(ValueError, match=message):
        load_lane_graph(_graph(tmp_path, graph))


def test_lane_graph_flags_reject_a_missing_file_and_duplicates(tmp_path):
    with pytest.raises(ValueError, match="cannot read lane graph"):
        parse_lane_graph_flags([str(tmp_path / "missing.yaml")])
    with pytest.raises(ValueError, match="twice"):
        parse_lane_graph_flags([str(LANE_GRAPH), str(LANE_GRAPH)])
    with pytest.raises(ValueError, match="MAP_ID=PATH"):
        parse_lane_graph_flags([f"={LANE_GRAPH}"])


def test_site_lanes_is_readable_by_a_viewer_and_revalidates_by_etag(tmp_path):
    from hashlib import sha256

    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore

    robot = FakeRobot("rosy-pinky-8kcn", state={"robot_id": "rosy-pinky-8kcn", "mode": "IDLE"})
    console = FleetConsole([RobotEndpoint("rosy-pinky-8kcn", "http://127.0.0.1:8080", "robot-rest")],
                           [robot])
    app = create_app(console, sightings=SightingService([_source()], known_robot_ids=console.robot_ids),
                     task_service=FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                                                   robot_ids={"rosy-pinky-8kcn"}),
                     start_task_dispatcher=False, site_lanes=parse_lane_graph_flags([str(LANE_GRAPH)]),
                     site_users={sha256(b"viewer-secret").hexdigest(): {
                         "principal_id": "viewer-1", "role": "viewer"}})
    with TestClient(app) as client:
        first = client.get("/api/fleet/site-lanes", headers=_auth("viewer-secret"))
        assert first.status_code == 200 and first.json()["maps"][0]["polylines"]
        assert first.headers["Cache-Control"] == "private, no-cache"
        etag = first.headers["ETag"]
        again = client.get("/api/fleet/site-lanes",
                           headers={**_auth("viewer-secret"), "If-None-Match": etag})
        assert again.status_code == 304 and again.headers["ETag"] == etag
        assert client.get("/api/fleet/site-lanes", headers={"If-None-Match": etag}).status_code == 401


def test_a_path_containing_equals_is_not_split_and_unknown_map_ids_are_reported(tmp_path):
    odd = tmp_path / "a=b"
    odd.mkdir()
    copy = odd / "lane_graph.yaml"
    copy.write_bytes(LANE_GRAPH.read_bytes())
    assert list(parse_lane_graph_flags([str(copy)])) == [None]
    lanes = parse_lane_graph_flags([f"site-v1={LANE_GRAPH}", f"typo-map={copy}"])
    assert unmatched_map_ids(lanes, [_source()]) == ["typo-map"]


def test_console_serves_the_map_fit_view_wired_to_vision_and_fleet():
    client = _client(None)

    # D-410 — 맵 맞춤 도구와 레이어 토글은 설치 문서에 산다.
    page = client.get("/console/install").text
    pure = client.get("/console/assets/map-fit.js")
    fit_view = client.get("/console/assets/map-fit-view.js").text
    vision_view = client.get("/console/assets/vision-view.js").text
    shell = client.get("/console/assets/console.js").text

    assert pure.status_code == 200 and "normalizeMapProposal" in pure.text
    assert 'from "./map-fit.js"' in fit_view and '"/api/fleet/site-lanes"' in fit_view
    # The warp is field-view's, not a copy.
    assert 'import { warpImage } from "./field-view.js"' in fit_view
    # Vision serves the proposal on the same lease; Fleet never relays it.
    assert 'fetchFieldProposal("map-proposal")' in vision_view
    assert "createMapFitView({ scope: pageScope, el, view, call, visionView, onChanged: () => fieldView.render() })" in client.get("/console/assets/install.js").text
    # D-360 fallback: the field view warps through the full map homography, never the clamped corners.
    field_view = client.get("/console/assets/field-view.js").text
    assert "view.mapFieldFallback?.(frame)" in field_view
    assert "multiply3(byMap.mapToShown, fieldToMap(byMap.bounds, field))" in field_view
    # A busy (429) proposal read is retried, not shown as an error.
    assert "retryDelay(error, attempt)" in fit_view and "맞추는 중…" in fit_view
    for element_id in ("map-fit-detect", "map-fit-accept", "map-fit-state", "map-fit-guidance",
                       "map-fit-canvas", "vision-lane-overlay"):
        assert f'id="{element_id}"' in page
    assert 'data-layer="lanes"' in page and 'data-layer="maptop"' in page
    assert "<script>" not in page


def test_console_cli_accepts_repeatable_site_lane_graph_and_paint():
    args = parse_args(["console", "--site-lane-graph", "a=x.yaml", "--site-lane-graph", "y.yaml",
                       "--site-lane-paint", "road_lines.stl"])
    assert args.site_lane_graph == ["a=x.yaml", "y.yaml"]
    assert args.site_lane_paint == ["road_lines.stl"]


def test_lane_paint_stl_is_served_as_flat_triangles_with_the_centrelines():
    paint = load_lane_paint(ROAD_LINES)
    assert len(paint["paint_triangles"]) == (ROAD_LINES.stat().st_size - 84) // 50
    assert all(len(tri) == 6 for tri in paint["paint_triangles"])

    client = _client(parse_lane_graph_flags([str(LANE_GRAPH)], [str(ROAD_LINES)]))
    entry = client.get("/api/fleet/site-lanes", headers=_auth()).json()["maps"][0]

    assert entry["polylines"] and len(entry["paint_triangles"]) == len(paint["paint_triangles"])
    # 2.81 x 1.26 m: the paint frames the view, not the centrelines inside it.
    assert entry["bounds_m"]["max_x"] == pytest.approx(1.405, abs=1e-3)
    assert entry["bounds_m"]["min_y"] == pytest.approx(-0.63, abs=1e-3)


def test_paint_only_entry_has_empty_polylines(tmp_path):
    client = _client(parse_lane_graph_flags(None, [str(ROAD_LINES)]))
    entry = client.get("/api/fleet/site-lanes", headers=_auth()).json()["maps"][0]
    assert entry["polylines"] == [] and entry["paint_triangles"]
    (tmp_path / "bad.stl").write_bytes(b"solid ascii\n")
    with pytest.raises(ValueError, match="binary STL"):
        load_lane_paint(tmp_path / "bad.stl")
