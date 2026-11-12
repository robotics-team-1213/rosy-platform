"""Tests for multi-bay berthing/docking parking routes and centerline LiDAR gaps."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.ledger.berth_parking_routes import (
    BAY_DOCK_SPECS,
    centerline_axial_gaps,
    infer_bay_id,
    install_berth_parking_routes,
)
from fleet.server.site_auth import SitePrincipal


def test_centerline_axial_gaps_ignores_adjacent_bay_rails_and_neighbor_robot():
    # Neighbor robot / Bay C1 rail at y=+0.055m, x=-0.17m (would clip wide ±0.080m corridor at 0.11m),
    # while true Bay C2 rear stop face is at y=0.005m, x=-0.35m (rg_center = 0.29m).
    pts = [
        (-0.17, 0.055),
        (-0.18, -0.052),
        (-0.3509, 0.004),
        (0.8189, -0.008),
    ]
    fg_c, rg_c = centerline_axial_gaps(pts, half_length_m=0.06, half_corridor_m=0.025)
    assert rg_c == 0.2909
    assert fg_c == 0.7589


def test_compact_bay_dock_specs_invariants():
    for bay_id, spec in BAY_DOCK_SPECS.items():
        assert 0.0 < spec["rail_entry_m"] < spec["staging_offset_m"]
        assert spec["rail_entry_m"] == 0.085
        assert spec["staging_offset_m"] == 0.20


def test_berth_parking_status_and_dispatch_routes():
    app = FastAPI()

    class DummyConsole:
        async def goal(self, robot_id: str, x: float, y: float, yaw: float) -> dict:
            return {"robot_id": robot_id, "x": x, "y": y, "yaw": yaw, "queued": False}

    async def fake_compute_road_plan(request, robot_id, x, y, yaw, place_id, label):
        return {
            "robot_id": robot_id,
            "target_nav2": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            "places": ["P1", place_id or "C1"],
            "edges": ["bay_1"],
            "waypoints_site": [
                {"x": x, "y": round(y - 0.20, 4), "yaw": yaw, "place": "P1"},
                {"x": x, "y": y, "yaw": yaw, "place": place_id or "C1"},
            ],
            "length_m": 0.20,
            "eta_s": 5.5,
        }

    def fake_operator() -> SitePrincipal:
        return SitePrincipal(principal_id="op-test", role="operator")

    install_berth_parking_routes(
        app,
        console=DummyConsole(),
        task_service=None,
        read_guard=[],
        operator_guard=[],
        require_operator=fake_operator,
        compute_road_plan=fake_compute_road_plan,
    )

    client = TestClient(app)
    st = client.get("/api/fleet/robots/rosy_46/berth-park/status")
    assert st.status_code == 200
    body = st.json()
    assert body["assigned_bay_id"] == "C1"
    assert body["funnel_law"]["in_rail_angular_rad_s"] == 0.0
    assert set(BAY_DOCK_SPECS.keys()) == {"C1", "C2", "C3"}
    assert infer_bay_id("rosy_45") == "C2"

    res = client.post(
        "/api/fleet/robots/rosy_46/berth-park",
        json={"bay_id": "C1", "mode": "forward_and_berth_park", "forward_m": 0.20},
    )
    assert res.status_code == 200
    rbody = res.json()
    assert rbody["dispatched"] is True
    assert rbody["bay_id"] == "C1"
    assert rbody["dock_id"] == "bay_c1"
    assert rbody["in_rail_angular_rad_s"] == 0.0
    assert rbody["phases"] == ["FORWARD_UNDOCK", "ALIGNING", "REVERSING_IN_RAILS", "SETTLING", "DOCKED"]
    assert len(rbody["waypoints_site"]) == 4
