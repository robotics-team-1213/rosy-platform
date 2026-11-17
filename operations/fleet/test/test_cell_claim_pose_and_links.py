"""Cell claims follow the robot's real pose, arm states say when they were observed, bay links follow the bay plan."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.routing.graph import build_graph
from fleet.server.charge_bay_routes import install_charge_bay_routes
from fleet.server.pipeline_routes import install_pipeline_routes
from fleet.site_map import SiteMap

AT_S3 = (0.68, -0.2528)          # inside 0.18 m of the cell_s station (S3 default 0.6987, -0.2512)
AWAY = (-0.003, 0.539)           # the 11-18 rosy_45 pin: nowhere near S3


def _map():
    return SiteMap(map_id="claim-test", places=[
        {"id": "C1", "name": "C1", "x": 0, "y": 0, "kind": "charge"},
        {"id": "C2", "name": "C2", "x": 1, "y": 0, "kind": "charge"},
        {"id": "C3", "name": "C3", "x": 2, "y": 0, "kind": "charge"},
        {"id": "S1", "name": "S1", "x": 3, "y": 0, "kind": "junction"},
    ], edges=[
        {"id": f"e{i}", "from": p1, "to": p2, "direction": "two_way",
         "width_m": 0.5, "speed_cap_mps": 0.15, "polyline": [[i-1, 0], [i, 0]]}
        for i, (p1, p2) in enumerate((("C1", "C2"), ("C2", "C3"), ("C3", "S1")), 1)
    ])


def _bay_app(poses):
    """A charge-bay app whose robots sit at ``poses`` (robot_id -> (x, y) or None for unlocated)."""
    site_map = _map()
    graph = build_graph(site_map)
    app = FastAPI()
    app.state.site_maps = SimpleNamespace(active=lambda: (1, site_map, graph, None),
                                          rules=SimpleNamespace(active_rules=lambda: None))
    app.state.map_pose = SimpleNamespace(arbitrated_pose=lambda rid: (
        SimpleNamespace(state="LOCALIZED", x=poses[rid][0], y=poses[rid][1], yaw=0.0)
        if poses.get(rid) is not None else SimpleNamespace(state="UNKNOWN", x=None, y=None, yaw=None)))

    async def gathered():
        return {"robots": [{"robot_id": rid, "online": True} for rid in poses]}

    install_charge_bay_routes(app, SimpleNamespace(_clock=lambda: 0.0), gathered, ())
    return app


def _claim(app, phase):
    app.state.omx_cell_states["cell_s"] = {
        "robot_id": "pinky_1", "phase": phase,
        "docked_robot": {"robot_id": "pinky_1", "robot_kind": "pinky",
                         "pose": {"x": AT_S3[0], "y": AT_S3[1], "yaw": 0.0}}}


@pytest.mark.parametrize("pose, phase, locked", [
    (AWAY, "CLAIMED", False),          # a known pose away from S3 releases the stale claim
    (AT_S3, "CLAIMED", True),          # at the station: the claim stands
    (None, "CLAIMED", True),           # pose unknown: keep the claim (safe side)
    (AWAY, "HUMAN_HOLD", True),        # a person in the bed zone holds regardless of pose
    (AWAY, "ARM_IN_BED_ZONE", True),   # an arm in the bed zone holds regardless of pose
])
def test_cell_claim_follows_the_robots_current_pose(pose, phase, locked):
    app = _bay_app({"pinky_1": pose})
    _claim(app, phase)
    plan = TestClient(app).get("/api/fleet/charge-bays").json()
    gate = plan["omx_cells"]["cell_s"]["gate"]
    action = next((a for a in plan["actions"] if a["robot_id"] == "pinky_1"), {})
    assert gate["amr_motion_inhibited"] is locked
    assert (gate["robot_id"] == "pinky_1") is locked
    assert (action.get("reason") == "locked_by_cell") is locked


def test_boot_default_arm_state_is_not_fresh_until_a_live_report():
    site_map = _map()
    app = FastAPI()
    install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site_map, build_graph(site_map), None)))
    client = TestClient(app)
    boot = client.get("/api/fleet/pipeline/cell-tasks").json()["arm_live_states"]
    for arm in ("arm_s", "arm_a", "arm_b"):
        assert (boot[arm]["observed"], boot[arm]["fresh"], boot[arm]["age_s"]) == (False, False, None)
    app.state.omx_cell_tasks["run"] = {"task_id": "run", "cell_id": "cell_s", "arm_id": "arm_s", "status": "RUNNING"}
    assert client.get("/api/fleet/pipeline/cell-tasks").json()["arm_live_states"]["arm_s"]["fresh"] is False

    live = client.post("/api/fleet/pipeline/cell-quality", json={
        "schema": "rosy.pipeline.cell-quality.v1",
        "arm_states": {"arm_s": {"joints_deg": [0.0, -58.0, 50.0, 50.0, -5.0, 58.0], "folded": True}},
    }).json()["arm_live_states"]["arm_s"]
    assert (live["source"], live["observed"], live["fresh"]) == ("live_stream", True, True)
    assert live["age_s"] is not None and live["age_s"] <= 15.0


def test_charge_bay_camera_links_follow_the_robot_in_the_bay():
    app = _bay_app({"pinky_2": (1.0, 0.0)})   # parked in C2
    asyncio.run(app.state.charge_bays_tick())
    links = TestClient(app).get("/api/fleet/charge-bays").json()["station_camera_links"]
    assert (links["C2"]["target_id"], links["C2"]["label"]) == ("pinky_2", "C2 충전칸 · pinky_2")
    assert (links["C1"]["target_id"], links["C1"]["label"]) == (None, "C1 충전칸")
    assert (links["C3"]["target_id"], links["C3"]["label"]) == (None, "C3 충전칸")
    assert links["S3"]["target_id"] == "arm_s"
    assert all(link["target_id"] not in ("rosy_42", "rosy_45", "rosy_46")
               for pid, link in links.items() if pid.startswith("C"))
