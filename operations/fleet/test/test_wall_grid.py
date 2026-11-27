"""Wall grid: the site map's wall faces as a Nav2 map in the site frame, and its read route."""
import base64
import importlib.util
import json
import math
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.localization import wall_grid
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.site_map import SiteMap
from fleet.swarm.robots import RobotEndpoint

ROOT = Path(__file__).resolve().parents[3]
V5 = ROOT / "deploy/site/site-maps/map_v2_fleet-v5.json"
OP = {"Authorization": "Bearer op"}
BOX = [((-1.2, -0.6), (1.2, -0.6)), ((1.2, -0.6), (1.2, 0.6)), ((1.2, 0.6), (-1.2, 0.6)), ((-1.2, 0.6), (-1.2, -0.6))]


def _map_health():
    spec = importlib.util.spec_from_file_location("map_health", ROOT / "tools/capture/map_health.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cell(grid, x, y, res=wall_grid.DEFAULT_RESOLUTION_M):
    ox, oy = grid["origin"]
    return grid["rows"][int((y - oy) // res)][int((x - ox) // res)]


def test_a_box_is_walls_over_free_over_unknown():
    grid = wall_grid.rasterize(BOX)
    assert _cell(grid, 0.0, 0.0) == wall_grid.FREE
    assert _cell(grid, -1.2, 0.0) == wall_grid.OCCUPIED and _cell(grid, 0.0, 0.6) == wall_grid.OCCUPIED
    assert _cell(grid, -1.25, 0.0) == wall_grid.UNKNOWN and _cell(grid, 0.0, 0.67) == wall_grid.UNKNOWN


@pytest.mark.parametrize("face", [((0.0, 0.0), (1.0, 0.0)), ((0.0, 0.0), (1.0, 1.0)), ((0.0, 0.0), (1.0, 0.3))])
def test_every_wall_is_at_least_one_cell_wide_and_unbroken(face):
    """A face is thinner than a cell, yet no gap may open along it, or AMCL sees through it."""
    grid = wall_grid.rasterize([face, ((0.0, 0.0), (0.0, 1.0)), ((1.0, 0.0), (1.0, 1.0))])
    res = wall_grid.DEFAULT_RESOLUTION_M
    for step in range(101):
        t = step / 100
        x, y = face[0][0] + t * (face[1][0] - face[0][0]), face[0][1] + t * (face[1][1] - face[0][1])
        near = [_cell(grid, x + i * res, y + j * res) for i in (-1, 0, 1) for j in (-1, 0, 1)]
        assert wall_grid.OCCUPIED in near, (x, y)


def test_build_is_deterministic_and_names_the_artifact():
    a, b = wall_grid.build("map_x", 7, BOX), wall_grid.build("map_x", 7, BOX)
    assert a["pgm"] == b["pgm"] and a["sha256"] == sha256(a["pgm"]).hexdigest() == b["sha256"]
    assert a["file_stem"] == "wall_map_x_v7" and a["yaml"]["image"] == "wall_map_x_v7.pgm"
    assert (a["yaml"]["mode"], a["yaml"]["negate"], a["yaml"]["occupied_thresh"], a["yaml"]["free_thresh"]) == \
        ("trinary", 0, 0.65, 0.25)
    assert a["pgm"].startswith(f"P5\n{a['width']} {a['height']}\n255\n".encode())
    assert wall_grid.build("map_x", 7, BOX[:3])["sha256"] != a["sha256"]


def test_no_faces_or_a_nan_refuse():
    with pytest.raises(wall_grid.WallGridError):
        wall_grid.rasterize([])
    with pytest.raises(wall_grid.WallGridError):
        wall_grid.rasterize([((0.0, float("nan")), (1.0, 0.0))])


def test_the_real_site_map_makes_an_enclosed_map_health_accepts():
    """Round trip through the capture health check: walls exist, no speckle, one closed free region, arena-sized."""
    health = _map_health()
    walls = SiteMap.model_validate(json.loads(V5.read_text(encoding="utf-8"))).walls
    built = wall_grid.build("map_v2_fleet", 5, [w.face for w in walls])
    meta = {"resolution": built["resolution"], "origin": built["yaml"]["origin"]}
    rows = [list(built["pgm"][built["pgm"].index(b"255\n") + 4:][r * built["width"]:(r + 1) * built["width"]])
            for r in range(built["height"])]
    grid = [[health.OCC if v == 0 else health.FREE if v == 254 else health.UNK for v in row] for row in rows]
    rep = health.analyze(meta, built["width"], built["height"], grid)
    assert rep["enclosed"] and rep["speckle"] == 0, rep
    assert health.verdict(rep, allow_resolution=built["resolution"])["verdict"] == "ok", rep


def _client(tmp_path, site):
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    if site is not None:
        draft = store.save_draft(site, expected_revision=None, principal_id="op")
        store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)
    bot = FakeRobot("rosy_42", state={"robot_id": "rosy_42", "map_id": "x"})
    users = {sha256(b"op").hexdigest(): {"principal_id": "bob", "role": "operator"}}
    console = FleetConsole([RobotEndpoint("rosy_42", "http://x", "t")], [bot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_42"})
    return TestClient(create_app(console, task_service=tasks, site_users=users, site_maps=store)), store


def test_the_route_serves_the_active_maps_walls(tmp_path):
    site = SiteMap.model_validate(json.loads(V5.read_text(encoding="utf-8")))
    client, store = _client(tmp_path, site)
    res = client.get("/api/fleet/site-map/wall-grid", headers=OP)
    assert res.status_code == 200, res.text
    body = res.json()
    version, active = store.active()[:2]
    assert (body["map_id"], body["version"]) == (active.map_id, version)
    assert body["file_stem"] == f"wall_{active.map_id}_v{version}"
    pgm = base64.b64decode(body["pgm_base64"])
    assert sha256(pgm).hexdigest() == body["sha256"] and body["yaml"]["image"] == f"{body['file_stem']}.pgm"
    assert body["yaml"]["resolution"] == pytest.approx(0.025) and math.isfinite(body["yaml"]["origin"][0])


def test_the_route_says_why_there_is_no_map(tmp_path):
    client, _ = _client(tmp_path, None)
    res = client.get("/api/fleet/site-map/wall-grid", headers=OP)
    assert res.status_code == 404 and res.json()["detail"]["code"] == "SITE_MAP_NOT_ACTIVE"
    assert client.get("/api/fleet/site-map/wall-grid").status_code in (401, 403)


def test_the_route_refuses_a_map_without_walls(tmp_path):
    body = json.loads(V5.read_text(encoding="utf-8"))
    client, _ = _client(tmp_path, SiteMap.model_validate({**body, "walls": []}))
    res = client.get("/api/fleet/site-map/wall-grid", headers=OP)
    assert res.status_code == 404 and res.json()["detail"]["code"] == "SITE_MAP_NO_WALLS"


def test_lane_mask_is_graded_non_lethal_and_aligned_with_wall_grid(tmp_path):
    site = SiteMap.model_validate(json.loads(V5.read_text(encoding="utf-8")))
    wall_built = wall_grid.build("map_v2_fleet", 5, [w.face for w in site.walls])
    mask_built = wall_grid.build_lane_mask("map_v2_fleet", 5, [w.face for w in site.walls], site.edges, site.places)
    assert (mask_built["width"], mask_built["height"]) == (wall_built["width"], wall_built["height"])
    assert mask_built["yaml"]["origin"] == wall_built["yaml"]["origin"]
    assert mask_built["yaml"]["mode"] == "scale" and mask_built["file_stem"] == "lane_mask_map_v2_fleet_v5"
    body = mask_built["pgm"][mask_built["pgm"].index(b"255\n") + 4:]
    assert min(body) > 0 and max(body) == 255  # strictly non-lethal everywhere; lane centerlines are cost 0 (255)
    off_pixel = max(1, min(255, round(255 * (1.0 - wall_grid.OFF_LANE_COST / 100.0))))
    assert off_pixel in body

    client, _ = _client(tmp_path, site)
    res = client.get("/api/fleet/site-map/lane-mask", headers=OP)
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["sha256"] == sha256(base64.b64decode(payload["pgm_base64"])).hexdigest()
    assert client.get("/api/fleet/site-map/lane-mask").status_code in (401, 403)
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    client_no_map, _ = _client(empty_dir, None)
    assert client_no_map.get("/api/fleet/site-map/lane-mask", headers=OP).status_code == 404
