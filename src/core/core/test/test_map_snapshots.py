"""MAP-003 FastAPI map / path / costmap snapshots (Flask GET /api/state split)."""

from pathlib import Path

import pytest
import yaml

from core_api_web.api.app import create_app
from core_common.profile import RobotProfile, robot_config_dir
from core.services import CoreServices

CONFIG_DIR = Path(__file__).parent.parent / "config"

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}

GRID = {
    "width": 2,
    "height": 2,
    "resolution": 0.05,
    "origin": {"x": -1.0, "y": -0.5, "yaw": 0.0},
    "data": [0, 100, -1, 50],
}


@pytest.fixture
def client(tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    config = yaml.safe_load((CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8"))
    # D-193 7: the dev tokens left the defaults; tests opt in like ROSY_DEV_AUTH=1.
    config.update(yaml.safe_load((CONFIG_DIR / "rosy_dev_auth.yaml").read_text(encoding="utf-8")))
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    caps = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, profile, caps, tmp_path / "wp.json")
    return TestClient(create_app(config, services)), services


def test_map_requires_viewer(client):
    tc, _ = client
    assert tc.get("/api/v1/map").status_code == 401
    assert tc.get("/api/v1/navigation/path").status_code == 401
    assert tc.get("/api/v1/map/costmap", params={"scope": "global"}).status_code == 401


def test_map_missing_is_not_found(client):
    tc, _ = client
    response = tc.get("/api/v1/map", headers=VIEWER)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_map_returns_grid_and_map_id(client):
    tc, svc = client
    svc.state.set_map_id("lab:abc123")
    svc.maps.set_map(GRID)
    response = tc.get("/api/v1/map", headers=VIEWER)
    assert response.status_code == 200
    body = response.json()
    assert body["map_id"] == "lab:abc123"
    assert body["width"] == 2
    assert body["height"] == 2
    assert body["resolution"] == pytest.approx(0.05)
    assert body["origin"] == {"x": -1.0, "y": -0.5, "yaw": 0.0}
    assert body["data"] == [0, 100, -1, 50]


def test_path_empty_until_plan_arrives(client):
    tc, svc = client
    empty = tc.get("/api/v1/navigation/path", headers=VIEWER)
    assert empty.status_code == 200
    assert empty.json() == {"poses": []}
    svc.maps.set_path([{"x": 0.1, "y": 0.2}, {"x": 1.0, "y": 0.0}])
    body = tc.get("/api/v1/navigation/path", headers=VIEWER).json()
    assert body["poses"] == [{"x": 0.1, "y": 0.2}, {"x": 1.0, "y": 0.0}]


def test_costmap_rejects_bad_scope(client):
    tc, _ = client
    missing = tc.get("/api/v1/map/costmap", headers=VIEWER)
    assert missing.status_code == 400
    bad = tc.get("/api/v1/map/costmap", params={"scope": "middle"}, headers=VIEWER)
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"


def test_costmap_local_and_global(client):
    tc, svc = client
    absent = tc.get("/api/v1/map/costmap", params={"scope": "local"}, headers=VIEWER)
    assert absent.status_code == 404
    svc.maps.set_costmap("local", GRID)
    local = tc.get("/api/v1/map/costmap", params={"scope": "local"}, headers=VIEWER)
    assert local.status_code == 200
    assert local.json()["scope"] == "local"
    assert local.json()["data"] == GRID["data"]
    svc.maps.set_costmap("global", {**GRID, "data": [1, 2, 3, 4]})
    global_ = tc.get("/api/v1/map/costmap", params={"scope": "global"}, headers=VIEWER)
    assert global_.status_code == 200
    assert global_.json()["scope"] == "global"
    assert global_.json()["data"] == [1, 2, 3, 4]


def test_viewer_may_read_map_snapshots(client):
    tc, svc = client
    svc.maps.set_map(GRID)
    assert tc.get("/api/v1/map", headers=VIEWER).status_code == 200


def test_grid_frame_samples_costmap_in_world_coordinates():
    from core_features.maps import GridFrame

    occupancy = GridFrame.from_dict(GRID)
    assert occupancy.world_to_cell(-1.0, -0.5) == (0, 0)
    assert occupancy.sample_world(-1.0 + 0.06, -0.5) == 100

    cost = GridFrame.from_dict({
        "width": 1,
        "height": 1,
        "resolution": 0.05,
        "origin": {"x": -0.95, "y": -0.5, "yaw": 0.0},
        "data": [254],
    })
    assert occupancy.sample_other(cost, -0.95, -0.5) == 254
    assert occupancy.sample_other(cost, -1.0, -0.5) is None


def test_grid_frame_rejects_mismatched_data():
    from core_features.maps import GridFrame, MapSnapshotStore

    with pytest.raises(ValueError):
        GridFrame.from_dict({**GRID, "data": [0]})
    with pytest.raises(ValueError):
        GridFrame.from_dict({**GRID, "width": 0})
    store = MapSnapshotStore()
    with pytest.raises(ValueError):
        store.set_map({**GRID, "data": [1, 2, 3]})
    store.set_map(GRID)
    assert store.get_map()["data"] == GRID["data"]
    assert store.get_map()["origin"]["yaw"] == 0.0


def test_path_rejects_non_finite_poses():
    from core_features.maps import MapSnapshotStore

    store = MapSnapshotStore()
    with pytest.raises(ValueError):
        store.set_path([{"x": float("nan"), "y": 0.0}])
    store.set_path([{"x": 1.5, "y": -0.25}])
    assert store.get_path() == [{"x": 1.5, "y": -0.25}]
