"""Fleet master-map exchange routes: pull -> upload -> get -> push/activate & refusals."""

from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path

from fastapi.testclient import TestClient
import httpx

from core_common.protocol.map_grid import occupancy_map_id
from fakes import FakeRobot, run
from fleet.hub.hub import HubError
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMap, SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient, RobotApiError

V5 = Path(__file__).resolve().parents[3] / "deploy/site/site-maps/map_v2_fleet-v5.json"
OP = {"Authorization": "Bearer op"}
VIEWER = {"Authorization": "Bearer vw"}


def _app_client(tmp_path: Path, *, active_site: bool = True, robot_map: dict | None = None):
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    if active_site:
        site = SiteMap.model_validate(json.loads(V5.read_text(encoding="utf-8")))
        draft = store.save_draft(site, expected_revision=None, principal_id="op")
        store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)
    bot = FakeRobot("rosy_46", state={"robot_id": "rosy_46", "map_id": "x"})
    bot._map = robot_map
    users = {
        sha256(b"op").hexdigest(): {"principal_id": "alice", "role": "operator"},
        sha256(b"vw").hexdigest(): {"principal_id": "viewer-1", "role": "viewer"},
    }
    console = FleetConsole([RobotEndpoint("rosy_46", "http://127.0.0.1:9999", "t")], [bot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_46"})
    return TestClient(create_app(console, task_service=tasks, site_users=users, site_maps=store)), bot, store, console


def _pgm_payload(*, w=4, h=4, comment=True, res=0.05, origin=None):
    rows = bytes([0] * w + [0, 254, 254, 0] * (h - 2) + [0] * w)
    hdr = f"P5\n# rosy map bundle: test\n{w} {h}\n255\n" if comment else f"P5\n{w} {h}\n255\n"
    pgm = hdr.encode("ascii") + rows
    return pgm, {
        "sha256": sha256(pgm).hexdigest(),
        "resolution": res,
        "origin": list(origin or [-0.1, -0.1, 0.0]),
        "occupied_thresh": 0.65,
        "free_thresh": 0.196,
        "pgm_base64": base64.b64encode(pgm).decode("ascii"),
        "source": "rosy_45+rosy_46",
    }


def test_end_to_end_pull_upload_get_and_push_preserves_float32_grid_id(tmp_path):
    # Robot reports ROS float32 resolution (0.05000000074505806) and -0.0 origin yaw.
    robot_cells = [100, 100, 100, 100, 100, 0, 0, 100, 100, 0, 0, 100, 100, 100, 100, 100]
    robot_map = {
        "map_id": "slam-live",
        "width": 4,
        "height": 4,
        "resolution": 0.05000000074505806,
        "origin": {"x": -0.1, "y": -0.1, "yaw": -0.0},
        "data": robot_cells,
    }
    client, bot, _, _ = _app_client(tmp_path, active_site=True, robot_map=robot_map)

    pulled = client.get("/api/fleet/robots/rosy_46/map/bundle", headers=VIEWER)
    assert pulled.status_code == 200, pulled.text
    b = pulled.json()
    assert b["yaml"]["resolution"] == 0.05000000074505806 and b["yaml"]["origin"] == [-0.1, -0.1, 0.0]
    grid_id = occupancy_map_id(robot_map)  # the pull carries no grid_id; CORE and the upload compute it
    assert grid_id.startswith("occupancy:")

    # Upload with canonical 0.05 resolution + comment-bearing PGM computes identical grid_id.
    _, upload_body = _pgm_payload(res=0.05, origin=[-0.1, -0.1, 0.0])
    up = client.put("/api/fleet/site-map/master-grid", json=upload_body, headers=OP)
    assert up.status_code == 200, up.text
    assert up.json()["grid_id"] == grid_id

    fetched = client.get("/api/fleet/site-map/master-grid", headers=VIEWER)
    assert fetched.status_code == 200
    assert fetched.json()["grid_id"] == grid_id
    assert fetched.json()["pgm_base64"] == upload_body["pgm_base64"]

    pushed = client.post("/api/fleet/robots/rosy_46/master-map/push", json={"activate": True}, headers=OP)
    assert pushed.status_code == 200, pushed.text
    assert pushed.json()["grid_id"] == grid_id
    assert len(bot.site_map_pushed) == 1
    assert bot.site_map_pushed[0]["grid_id"] == grid_id
    assert bot.site_map_pushed[0]["activate"] is True
    assert bot.site_map_pushed[0]["map_id"] == "map_v2_fleet"


def test_refusals_cover_auth_missing_site_map_missing_master_and_validation(tmp_path):
    client_no_site, bot_no_site, _, _ = _app_client(tmp_path, active_site=False, robot_map=None)

    assert client_no_site.get("/api/fleet/robots/rosy_46/map/bundle").status_code in (401, 403)
    assert client_no_site.get("/api/fleet/site-map/master-grid").status_code in (401, 403)

    no_map = client_no_site.get("/api/fleet/robots/rosy_46/map/bundle", headers=VIEWER)
    assert no_map.status_code == 404 and no_map.json()["detail"]["code"] == "NO_MAP"

    bot_no_site.map_error = RobotApiError("rosy_46", 404, "NOT_FOUND", "no map")
    assert client_no_site.get("/api/fleet/robots/rosy_46/map/bundle", headers=VIEWER).json()["detail"]["code"] == "NO_MAP"

    _, body = _pgm_payload()
    assert client_no_site.put("/api/fleet/site-map/master-grid", json=body, headers=VIEWER).status_code == 403
    no_active = client_no_site.put("/api/fleet/site-map/master-grid", json=body, headers=OP)
    assert no_active.status_code == 404 and no_active.json()["detail"]["code"] == "SITE_MAP_NOT_ACTIVE"

    client, bot, _, console = _app_client(tmp_path, active_site=True)
    missing_master = client.get("/api/fleet/site-map/master-grid", headers=VIEWER)
    assert missing_master.status_code == 404 and missing_master.json()["detail"]["code"] == "MASTER_GRID_NOT_SET"
    push_missing = client.post("/api/fleet/robots/rosy_46/master-map/push", json={}, headers=OP)
    assert push_missing.status_code == 404 and push_missing.json()["detail"]["code"] == "MASTER_GRID_NOT_SET"

    bad_yaw = client.put("/api/fleet/site-map/master-grid", json={**body, "origin": [0.0, 0.0, 0.2]}, headers=OP)
    assert bad_yaw.status_code == 422 and bad_yaw.json()["detail"]["code"] == "VALIDATION_ERROR"

    bad_sha = client.put("/api/fleet/site-map/master-grid", json={**body, "sha256": "0" * 64}, headers=OP)
    assert bad_sha.status_code == 422 and bad_sha.json()["detail"]["code"] == "VALIDATION_ERROR"

    bad_gid = client.put(
        "/api/fleet/site-map/master-grid", json={**body, "grid_id": "occupancy:000000000000"}, headers=OP,
    )
    assert bad_gid.status_code == 422 and bad_gid.json()["detail"]["code"] == "VALIDATION_ERROR"

    invalid_model = client.put(
        "/api/fleet/site-map/master-grid", json={**body, "unexpected_field": 1}, headers=OP,
    )
    assert invalid_model.status_code == 422 and invalid_model.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert body["pgm_base64"] not in invalid_model.text

    # Timeout from robot returns 502 instead of 500, and trip busy refuses activation push
    assert client.put("/api/fleet/site-map/master-grid", json=body, headers=OP).status_code == 200
    bot.map_error = httpx.ReadTimeout("map stalled")
    assert client.get("/api/fleet/robots/rosy_46/map/bundle", headers=VIEWER).status_code == 502
    bot.site_map_push_error = httpx.ReadTimeout("push stalled")
    assert client.post("/api/fleet/robots/rosy_46/master-map/push", json={"activate": True}, headers=OP).status_code == 502
    bot.site_map_push_error = None
    console.trip_refusal = lambda _ids: HubError("TRIP_ROBOT_BUSY", "rosy_46")
    busy = client.post("/api/fleet/robots/rosy_46/master-map/push", json={"activate": True}, headers=OP)
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "TRIP_ROBOT_BUSY"


def test_http_robot_client_site_map_push_preserves_default_or_activation_timeout():
    seen_timeouts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_timeouts.append(dict(request.extensions.get("timeout") or {}))
        return httpx.Response(202, json={"staged": True, "activated": False})

    async def exercise():
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:9999", transport=httpx.MockTransport(handler), timeout=5.0,
        ) as http:
            ep = RobotEndpoint("rosy_46", "http://127.0.0.1:9999", "tok")
            rc = HttpRobotClient(ep, http=http)
            await rc.site_map_push({"activate": False})
            await rc.site_map_push({"activate": True})
            await rc.aclose()

    run(exercise())
    assert seen_timeouts[0]["read"] == 5.0
    assert seen_timeouts[1]["read"] == 40.0
