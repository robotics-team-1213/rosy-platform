"""D-257 site rectangle readback: the overhead-covered area as display geometry only."""

from hashlib import sha256

import pytest
import yaml
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.sightings_config import load_sighting_sources
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

SOURCE_TOKEN = "source-camera-secret"
OPERATOR_TOKEN = "operator-secret"
VIEWER_TOKEN = "viewer-secret"
RECT = ((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0))


def _source(**changes):
    fields = dict(
        source_id="ceiling-east", token=SOURCE_TOKEN, robot_ids=("rosy-pinky-8kcn",),
        map_id="site-v1", calibration_revision="cal-v3", corner_marker_ids=(30, 31, 32, 33),
        corner_world_m=RECT, robot_markers=(("rosy-pinky-8kcn", 40),),
    )
    fields.update(changes)
    return SightingSource(**fields)


def _console():
    robot = FakeRobot("rosy-pinky-8kcn", state={"robot_id": "rosy-pinky-8kcn", "mode": "IDLE"})
    endpoints = [RobotEndpoint("rosy-pinky-8kcn", "http://127.0.0.1:8080", "robot-rest")]
    return FleetConsole(endpoints, [robot])


def _client(sources=None, **app_kwargs):
    console = _console()
    service = (SightingService(sources, known_robot_ids=console.robot_ids)
               if sources is not None else None)
    app_kwargs.setdefault("console_token", OPERATOR_TOKEN)
    return TestClient(create_app(console, sightings=service, **app_kwargs))


def _auth(token=OPERATOR_TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_site_map_returns_the_configured_rectangle_without_secrets():
    client = _client([_source()])

    response = client.get("/api/fleet/site-map", headers=_auth())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["maps"] == [{
        "map_id": "site-v1",
        "frame": "map",
        "units": "m",
        "polygon_m": [[0.0, 0.0], [4.0, 0.0], [4.0, 2.0], [0.0, 2.0]],
        "bounds_m": {"min_x": 0.0, "min_y": 0.0, "max_x": 4.0, "max_y": 2.0},
        "sources": [{
            "source_id": "ceiling-east",
            "calibration_revision": "cal-v3",
            "corner_marker_ids": [30, 31, 32, 33],
            "robot_ids": ["rosy-pinky-8kcn"],
            "robot_markers": {"rosy-pinky-8kcn": 40},
        }],
    }]
    assert SOURCE_TOKEN not in response.text
    assert "token" not in response.text


def test_site_map_is_404_without_sighting_config_or_geometry():
    for client in (_client(None), _client([_source(corner_world_m=None)])):
        response = client.get("/api/fleet/site-map", headers=_auth())
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "NO_SITE_MAP"


def test_site_map_requires_a_read_credential_and_rejects_the_source_token():
    client = _client([_source()])

    assert client.get("/api/fleet/site-map").status_code == 401
    assert client.get("/api/fleet/site-map", headers=_auth(SOURCE_TOKEN)).status_code == 401


def test_site_map_is_readable_by_a_viewer(tmp_path):
    console = _console()
    service = SightingService([_source()], known_robot_ids=console.robot_ids)
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                                    robot_ids={"rosy-pinky-8kcn"})
    app = create_app(console, sightings=service, task_service=task_service,
                     start_task_dispatcher=False,
                     site_users={sha256(VIEWER_TOKEN.encode()).hexdigest(): {
                         "principal_id": "viewer-1", "role": "viewer"}})
    with TestClient(app) as client:
        response = client.get("/api/fleet/site-map", headers=_auth(VIEWER_TOKEN))
    assert response.status_code == 200
    assert response.json()["maps"][0]["map_id"] == "site-v1"


def test_sources_sharing_a_map_are_grouped_under_one_rectangle():
    second = _source(source_id="ceiling-west", token="other-source-secret",
                     corner_marker_ids=(34, 35, 36, 37), robot_markers=())
    client = _client([_source(), second])

    maps = client.get("/api/fleet/site-map", headers=_auth()).json()["maps"]

    assert len(maps) == 1
    assert [source["source_id"] for source in maps[0]["sources"]] == ["ceiling-east", "ceiling-west"]


def _write(path, row):
    path.write_text(yaml.safe_dump({"sources": [row]}), encoding="utf-8")
    return path


def _row(**changes):
    row = {
        "source_id": "ceiling_north", "token_env": "ROSY_FLEET_SIGHTING_TOKEN",
        "robot_ids": ["rosy-pinky-8kcn"], "map_id": "site-v1",
        "calibration_revision": "cal-v3", "corner_marker_ids": [30, 31, 32, 33],
        "corner_world_m": [[0.0, 0.0], [4.0, 0.0], [4.0, 2.0], [0.0, 2.0]],
        "robot_markers": {"rosy-pinky-8kcn": 40},
    }
    row.update(changes)
    return row


ENV = {"ROSY_FLEET_SIGHTING_TOKEN": "runtime-secret"}


def test_loader_keeps_site_geometry_for_display(tmp_path):
    source = load_sighting_sources(_write(tmp_path / "c.yaml", _row()), environ=ENV)[0]

    assert source.corner_world_m == RECT
    assert source.robot_markers == (("rosy-pinky-8kcn", 40),)


def test_loader_geometry_is_optional(tmp_path):
    row = _row()
    del row["corner_world_m"], row["robot_markers"]
    source = load_sighting_sources(_write(tmp_path / "c.yaml", row), environ=ENV)[0]

    assert source.corner_world_m is None
    assert source.robot_markers == ()


@pytest.mark.parametrize("corners", [
    [[0, 0], [1, 0], [1, 1]],
    [[0, 0], [1, 0], [1, 1], [0, "x"]],
    [[0, 0], [1, 0], [1, 1], [0, 0]],
    [[0, 0], [1, 0], [1, 1], [0, float("nan")]],
    [[0, 0], [1, 0], [1, 1], [0, 1, 2]],
])
def test_loader_rejects_malformed_site_rectangle(tmp_path, corners):
    with pytest.raises(ValueError, match="corner_world_m"):
        load_sighting_sources(_write(tmp_path / "c.yaml", _row(corner_world_m=corners)), environ=ENV)


def test_loader_rejects_malformed_robot_markers(tmp_path):
    for markers in ({"rosy-pinky-8kcn": "40"}, {"rosy-pinky-8kcn": -1}, ["rosy-pinky-8kcn"]):
        with pytest.raises(ValueError, match="robot_markers"):
            load_sighting_sources(_write(tmp_path / "c.yaml", _row(robot_markers=markers)),
                                  environ=ENV)


def test_hyphenated_site_robot_ids_pass_sighting_validation():
    from core_common.protocol.sightings import SiteSightingPayload

    payload = SiteSightingPayload(
        robot_id="rosy-pinky-8kcn", x=1.0, y=0.5, yaw=0.0, captured_at=1.0, seq=1,
        map_id="site-v1", calibration_revision="cal-v3", processor_revision="p",
        corner_marker_ids=(30, 31, 32, 33),
    )
    assert payload.robot_id == "rosy-pinky-8kcn"


def test_console_serves_the_site_layer_and_draws_sightings_apart_from_core_pose():
    client = _client([_source()])

    layer = client.get("/console/assets/site-layer.js")
    map_view = client.get("/console/assets/map-view.js").text
    shell = client.get("/console/assets/console.js").text
    page = client.get("/console").text

    assert layer.status_code == 200
    assert "classifySightings" in layer.text
    assert 'from "./site-layer.js"' in map_view
    assert '"/api/fleet/site-map"' in map_view and '"/api/fleet/sightings"' in map_view
    assert "mapView.refreshSightings()" in shell
    assert 'id="legend-sighting"' in page
    assert "<script>" not in page  # CSP: script-src 'self' only


def test_console_polls_sightings_only_for_a_configured_site_and_stops_on_404():
    client = _client([_source()])

    map_view = client.get("/console/assets/map-view.js").text
    shell = client.get("/console/assets/console.js").text

    # The sightings route is only registered with a sightings config; no site map → no polling.
    assert "sightingsUnavailable || !view.siteMap) return;" in map_view
    assert "if (err.status === 404) sightingsUnavailable = true;" in map_view
    assert "if (unchanged && !next.length) return;" in map_view
    # A transient site-map failure keeps the last rectangle; only NO_SITE_MAP clears it.
    assert 'err.status === 404 && err.code === "NO_SITE_MAP"' in map_view
    assert 'setAttribute("role", "img")' in map_view and 'setAttribute("role", "button")' in map_view
    assert "error.status = resp.status;" in shell and "error.code = detail.code;" in shell


def test_site_layer_node_unit_tests_pass():
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --test test/web/` where it is")
    spec = Path(__file__).resolve().parent / "web" / "site-layer.test.mjs"
    result = subprocess.run([node, "--test", str(spec)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
