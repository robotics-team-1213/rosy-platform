"""D-1022 map binding HTTP: read, approve with refit, revoke, and the marker-free wall proposal."""
import math
from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.localization.map_binding import Fit
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_charge_bays import _world_261026_charge_graph

TRUTH = Fit(math.radians(15), 0.2, -0.1, ())
GRID_ID = "occupancy:0123456789ab"
OP = {"Authorization": "Bearer op"}
ARENA = (-1.22, -0.61, 1.22, 0.61)


def _walls_grid(res=0.05):
    """A robot map whose occupied cells are the arena walls seen through TRUTH."""
    pts = []
    x = ARENA[0]
    while x <= ARENA[2] + 1e-9:
        pts += [(x, ARENA[1]), (x, ARENA[3])]
        x += res
    y = ARENA[1]
    while y <= ARENA[3] + 1e-9:
        pts += [(ARENA[0], y), (ARENA[2], y)]
        y += res
    robot = [TRUTH.inverse(p) for p in pts]
    ox, oy = min(p[0] for p in robot) - 0.1, min(p[1] for p in robot) - 0.1
    w = int((max(p[0] for p in robot) - ox) / res) + 3
    h = int((max(p[1] for p in robot) - oy) / res) + 3
    data = [0] * (w * h)
    for px, py in robot:
        data[int((py - oy) / res) * w + int((px - ox) / res)] = 100
    return {"width": w, "height": h, "resolution": res, "origin": {"x": ox, "y": oy}, "data": data}


def _client(tmp_path):
    site, _ = _world_261026_charge_graph()
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    draft = store.save_draft(site, expected_revision=None, principal_id="op")
    store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)
    here = TRUTH.inverse((-0.414, 0.47))
    bot = FakeRobot("rosy_42", state={
        "robot_id": "rosy_42", "map_id": "world_261026", "map_grid_id": GRID_ID,
        "pose": {"x": here[0], "y": here[1], "yaw": 0.0},
        "localization": {"state": "LOCALIZED", "pose_frame": "map"}}, map=_walls_grid())
    users = {sha256(b"op").hexdigest(): {"principal_id": "bob", "role": "operator"}}
    console = FleetConsole([RobotEndpoint("rosy_42", "http://x", "t")], [bot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_42"})
    return TestClient(create_app(console, task_service=tasks, site_users=users, site_maps=store))


def _pairs(points):
    return [{"site": list(p), "robot": list(TRUTH.inverse(p))} for p in points]


def test_approve_read_and_revoke(tmp_path):
    client = _client(tmp_path)
    assert client.get("/api/fleet/robots/rosy_42/map-binding", headers=OP).json()["reason"] == "MAP_BINDING_REQUIRED"
    res = client.post("/api/fleet/robots/rosy_42/map-binding", headers=OP, json={
        "pairs": _pairs([(-1.0, -0.5), (1.0, -0.5), (0.9, 0.45)]), "holdout": _pairs([(0.0, 0.0)])})
    assert res.status_code == 200, res.text
    assert res.json()["robot_grid_id"] == GRID_ID
    read = client.get("/api/fleet/robots/rosy_42/map-binding", headers=OP).json()
    assert read["matches"] is True and read["active"]["fit"]["yaw"] == __import__("pytest").approx(TRUTH.yaw)
    assert client.delete("/api/fleet/robots/rosy_42/map-binding", headers=OP).json() == {"revoked": True}


def test_a_bad_holdout_is_refused_with_its_code(tmp_path):
    client = _client(tmp_path)
    res = client.post("/api/fleet/robots/rosy_42/map-binding", headers=OP, json={
        "pairs": _pairs([(-1.0, -0.5), (1.0, -0.5), (0.9, 0.45)]),
        "holdout": [{"site": [0.2, 0.0], "robot": list(TRUTH.inverse((0.0, 0.0)))}]})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "HOLDOUT"


def test_the_walls_propose_pairs_that_then_approve_without_markers(tmp_path):
    client = _client(tmp_path)
    prop = client.post("/api/fleet/robots/rosy_42/map-binding/propose", headers=OP,
                       json={"seed_site": [-0.414, 0.47], "arena": list(ARENA)})
    assert prop.status_code == 200, prop.text
    body = prop.json()
    assert body["robot_grid_id"] == GRID_ID and abs(body["preview"]["yaw"] - TRUTH.yaw) < math.radians(3)
    res = client.post("/api/fleet/robots/rosy_42/map-binding", headers=OP, json={
        "pairs": body["pairs"], "holdout": _pairs([(0.5, 0.2)])})
    assert res.status_code == 200, res.text
