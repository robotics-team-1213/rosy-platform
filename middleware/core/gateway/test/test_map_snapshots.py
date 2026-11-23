"""MAP-003 FastAPI map / path / costmap snapshots (Flask GET /api/state split)."""

from pathlib import Path

import pytest
import yaml

from core_api_web.api.app import create_app
from core_common.profile import RobotProfile, robot_config_dir
from core.services import CoreServices

CONFIG_DIR = (Path(__file__).resolve().parents[4] / "contracts") / "foundation" / "config"

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


def test_map_id_stays_with_received_grid_when_robot_changes_map(client):
    tc, svc = client
    svc.maps.set_map(GRID, map_id="old-map")
    svc.state.set_map_id("new-map")
    assert tc.get("/api/v1/map", headers=VIEWER).json()["map_id"] == "old-map"


def test_path_empty_until_plan_arrives(client):
    tc, svc = client
    empty = tc.get("/api/v1/navigation/path", headers=VIEWER)
    assert empty.status_code == 200
    assert empty.json() == {"poses": []}
    svc.maps.set_path([{"x": 0.1, "y": 0.2}, {"x": 1.0, "y": 0.0}])
    body = tc.get("/api/v1/navigation/path", headers=VIEWER).json()
    assert body["poses"] == [{"x": 0.1, "y": 0.2}, {"x": 1.0, "y": 0.0}]


def test_path_keeps_receive_evidence_when_robot_map_changes(client):
    tc, svc = client
    svc.maps.set_path([{"x": 0.1, "y": 0.2}], map_id="old-map", frame_id="map")
    svc.state.set_map_id("new-map")
    body = tc.get("/api/v1/navigation/path", headers=VIEWER).json()
    assert body["poses"] == [{"x": 0.1, "y": 0.2}]
    assert body["map_id"] == "old-map" and body["frame_id"] == "map"
    assert 0 <= body["age_s"] < 5


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


def test_site_map_get_and_post_enforce_auth_validation_and_stop_evidence(client, monkeypatch, tmp_path):
    import base64
    import hashlib
    import json
    from core_api_web.api.deps import Mode
    from core_api_web.api.host_agent_client import AgentReply
    from core_api_web.api.v1 import map as v1_map

    monkeypatch.setattr(v1_map, "_ACTIVATE_POLL_S", 0.0)

    class FakeHost:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, bool]] = []
            self.status_sequence: list[AgentReply] = []
            self.stage_reply: AgentReply | None = None

        def request(self, command: str, *, role: str, user_id: str | None = None, **_kwargs) -> AgentReply:
            self.calls.append((command, role, svc.modes.motion_reserved))
            if command == "site_map.status":
                if self.status_sequence:
                    return self.status_sequence.pop(0)
                return AgentReply(True, "OK", data={"phase": "IDLE", "backend": "slam"})
            if command == "site_map.stage":
                if self.stage_reply is not None:
                    return self.stage_reply
                return AgentReply(True, "OK", data={"staged": "site_site-a_v1"})
            return AgentReply(True, "OK", data={"phase": "ACTIVATING"})

    tc, svc = client
    fake_host = FakeHost()
    svc.host_agent = fake_host
    state_dir = tmp_path / "core-state"
    monkeypatch.setenv("STATE_DIRECTORY", str(state_dir))

    assert tc.get("/api/v1/map/site").status_code == 401
    st = tc.get("/api/v1/map/site", headers=VIEWER)
    assert st.status_code == 200 and st.json()["available"] is True and st.json()["phase"] == "IDLE"

    pgm = b"P5\n# rosy map bundle: test\n4 4\n255\n" + bytes([254] * 16)
    payload = {
        "map_id": "site-a",
        "version": 1,
        "sha256": hashlib.sha256(pgm).hexdigest(),
        "resolution": 0.05,
        "origin": [-0.1, -0.1, 0.0],
        "occupied_thresh": 0.65,
        "free_thresh": 0.196,
        "pgm_base64": base64.b64encode(pgm).decode("ascii"),
        "grid_id": "occupancy:1234567890ab",
        "activate": False,
    }
    assert tc.post("/api/v1/map/site", json=payload, headers=VIEWER).status_code == 403

    bad_sha = tc.post("/api/v1/map/site", json={**payload, "sha256": "0" * 64}, headers=OPERATOR)
    assert bad_sha.status_code == 400 and bad_sha.json()["error"]["code"] == "SHA256_MISMATCH"

    bad_yaw = tc.post("/api/v1/map/site", json={**payload, "origin": [-0.1, -0.1, 0.25]}, headers=OPERATOR)
    assert bad_yaw.status_code == 400 and bad_yaw.json()["error"]["code"] == "VALIDATION_ERROR"

    staged = tc.post("/api/v1/map/site", json=payload, headers=OPERATOR)
    assert staged.status_code == 202 and staged.json()["staged"] is True and staged.json()["activated"] is False
    assert fake_host.calls[-1][:2] == ("site_map.stage", "machine")

    # Unreachable host agent maps to 503
    fake_host.stage_reply = AgentReply(False, "HOST_AGENT_UNAVAILABLE", "socket missing")
    unreach = tc.post("/api/v1/map/site", json=payload, headers=OPERATOR)
    assert unreach.status_code == 503
    fake_host.stage_reply = None

    now = [100.0]
    monkeypatch.setattr(svc.state, "_monotonic", lambda: now[0])
    monkeypatch.setattr(svc.state, "_clock", lambda: 1_700_000_000.0 + now[0])

    # Moving -> ROBOT_NOT_STOPPED
    svc.state.set_velocity(0.2, 0.0, sampled_at=now[0])
    moving = tc.post("/api/v1/map/site", json={**payload, "activate": True}, headers=OPERATOR)
    assert moving.status_code == 409 and moving.json()["error"]["code"] == "ROBOT_NOT_STOPPED"

    # Zero velocity held < 2.0 s -> ROBOT_NOT_STOPPED
    for step in (100.4, 100.8, 101.2):
        now[0] = step
        svc.state.set_velocity(0.0, 0.0, sampled_at=1_700_000_000.0 + now[0])
    too_soon = tc.post("/api/v1/map/site", json={**payload, "activate": True}, headers=OPERATOR)
    assert too_soon.status_code == 409 and too_soon.json()["error"]["code"] == "ROBOT_NOT_STOPPED"

    # Odometry silence gap > 0.5 s followed by 1 zero sample resets zero_velocity_since -> refused
    now[0] = 102.5
    svc.state.set_velocity(0.0, 0.0, sampled_at=1_700_000_000.0 + now[0])
    assert svc.state.zero_velocity_since == 102.5
    after_gap = tc.post("/api/v1/map/site", json={**payload, "activate": True}, headers=OPERATOR)
    assert after_gap.status_code == 409 and after_gap.json()["error"]["code"] == "ROBOT_NOT_STOPPED"

    # Continuous zero samples <= 0.4 s apart across >= 2.0 s pass
    for offset in (0.4, 0.8, 1.2, 1.6, 2.0, 2.2):
        now[0] = 102.5 + offset
        svc.state.set_velocity(0.0, 0.0, sampled_at=1_700_000_000.0 + now[0])

    # Rejected timestamp (sampled_at=None after seeing finite stamp) resets zero_velocity_since -> refused
    now[0] = 104.9
    svc.state.set_velocity(0.0, 0.0, sampled_at=None)
    assert svc.state.zero_velocity_since is None
    rejected_stamp = tc.post("/api/v1/map/site", json={**payload, "activate": True}, headers=OPERATOR)
    assert rejected_stamp.status_code == 409 and rejected_stamp.json()["error"]["code"] == "ROBOT_NOT_STOPPED"

    # Re-establish continuous >= 2.0 s zero velocity with valid timestamps
    for offset in (0.0, 0.4, 0.8, 1.2, 1.6, 2.0, 2.2):
        now[0] = 105.0 + offset
        svc.state.set_velocity(0.0, 0.0, sampled_at=1_700_000_000.0 + now[0])

    # Mode / E-stop / Calibration / Trip lease gates refuse
    svc.modes.transition(Mode.MANUAL)
    assert tc.post("/api/v1/map/site", json={**payload, "activate": True}, headers=OPERATOR).json()["error"]["code"] == "MODE_CONFLICT"
    svc.modes.transition(Mode.IDLE)

    svc.safety.trigger_estop("operator")
    assert tc.post("/api/v1/map/site", json={**payload, "activate": True}, headers=OPERATOR).json()["error"]["code"] == "ESTOP_ACTIVE"
    svc.modes.release_emergency()
    svc.safety.release(by="operator")

    # Activation reserves idle motion across stage + activate + status poll, then releases
    fake_host.calls.clear()
    fake_host.status_sequence = [
        AgentReply(True, "OK", data={"phase": "ACTIVATING"}),
        AgentReply(True, "OK", data={"phase": "ACTIVE", "backend": "localization"}),
    ]
    act = tc.post("/api/v1/map/site", json={**payload, "activate": True}, headers=OPERATOR)
    assert act.status_code == 202 and act.json()["activated"] is True
    assert act.json()["activation"]["phase"] == "ACTIVE"
    assert svc.modes.motion_reserved is False
    assert fake_host.calls == [
        ("site_map.stage", "machine", True),
        ("site_map.activate", "machine", True),
        ("site_map.status", "machine", True),
        ("site_map.status", "machine", True),
    ]
    stop_doc = json.loads((state_dir / "site-map-stop.json").read_text(encoding="utf-8"))
    assert stop_doc["goal_active"] is False and stop_doc["written_at"] - stop_doc["zero_since"] >= 2.0

    # Rolled-back terminal phase returns 409 SITE_MAP_ACTIVATE_FAILED and releases motion_reserved
    fake_host.status_sequence = [AgentReply(True, "OK", data={"phase": "ROLLED_BACK", "reason": "nav failed"})]
    failed_act = tc.post("/api/v1/map/site", json={**payload, "activate": True}, headers=OPERATOR)
    assert failed_act.status_code == 409 and failed_act.json()["error"]["code"] == "SITE_MAP_ACTIVATE_FAILED"
    assert svc.modes.motion_reserved is False
