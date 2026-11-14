"""Tests for multi-bay berthing/docking parking routes and centerline LiDAR gaps."""

from __future__ import annotations

from types import SimpleNamespace

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
        assert spec["bay_pose"]["y"] == 0.470
        assert spec["stop_face_rg_m"] > 0.0


def test_berth_parking_status_and_dispatch_routes():
    app = FastAPI()

    class DummyConsole:
        async def goal(self, robot_id: str, x: float, y: float, yaw: float) -> dict:
            return {"robot_id": robot_id, "x": x, "y": y, "yaw": yaw, "queued": False, "accepted": True}

        def trip_refusal(self, robot_ids):
            return None

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
        require_named_operator=fake_operator,
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

    scen = client.post("/api/fleet/scenario/bay-departure", json={"execute_physical": False})
    assert scen.status_code == 200
    sbody = scen.json()
    assert sbody["depart_order"] == ["rosy_46", "rosy_45", "rosy_42"]
    assert sbody["live_robots"]["rosy_46"]["site_pose"]["y"] == 0.470
    assert sbody["live_robots"]["rosy_45"]["site_pose"]["y"] == 0.470
    assert sbody["cell_contract_handoff"]["stop_place_id"] == "S3"


def _road_app(goal, refusal=None):
    from fastapi import HTTPException
    from fleet.hub.hub import HubError

    app = FastAPI()
    console = SimpleNamespace(goal=goal, trip_refusal=lambda ids: refusal)

    async def plan(request, robot_id, x, y, yaw, place_id, label):
        return {"target_nav2": {"x": 0.1, "y": 0.0, "yaw": 0.0}, "waypoints_site": []}

    def named() -> SitePrincipal:
        return SitePrincipal(principal_id="op-named", role="operator")

    install_berth_parking_routes(app, console=console, task_service=None, read_guard=[], operator_guard=[],
                                 require_operator=named, require_named_operator=named, compute_road_plan=plan)
    return TestClient(app, raise_server_exceptions=False), HTTPException, HubError


def test_road_nav2_failure_is_an_error_never_a_simulated_dispatch():
    async def goal(*args):
        raise HubError("robot unreachable")
    client, _, _ = _road_app(goal)
    res = client.post("/api/fleet/robots/rosy_46/road-nav2", json={"x": 0.0, "y": 0.0})
    assert res.status_code >= 400 and "simulated_dispatch" not in res.text


def test_road_nav2_refuses_a_robot_on_a_running_trip():
    sent = []

    async def goal(*args):
        sent.append(args)
        return {"accepted": True}
    from fastapi import HTTPException
    client, _, _ = _road_app(goal, refusal=HTTPException(409, {"code": "TRIP_RUNNING"}))
    res = client.post("/api/fleet/robots/rosy_46/road-nav2", json={"x": 0.0, "y": 0.0})
    assert res.status_code == 409 and not sent


def test_road_nav2_route_needs_a_named_operator():
    import inspect
    from fleet.server.ledger import berth_parking_routes
    assert "Depends(require_named_operator)" in inspect.getsource(berth_parking_routes.install_berth_parking_routes)


def test_berth_park_failure_is_an_error_never_a_reported_dispatch():
    from fleet.hub.hub import HubError

    async def goal(*args):
        raise HubError("robot unreachable")
    client, _, _ = _road_app(goal)
    res = client.post("/api/fleet/robots/rosy_46/berth-park", json={"bay_id": "C1", "execute_physical": False})
    assert res.status_code >= 400 and '"dispatched":true' not in res.text.replace(" ", "")


def test_queued_road_nav2_is_reported_queued_not_dispatched():
    from fleet.server.ledger import berth_parking_routes as routes
    app = FastAPI()

    class Tasks:
        async def submit_navigation(self, **kwargs):
            return {"status": "QUEUED", "task_id": "t1"}

    async def plan(*args):
        return {"target_nav2": {"x": 0.1, "y": 0.0, "yaw": 0.0}, "waypoints_site": []}

    named = lambda: SitePrincipal(principal_id="op-named", role="operator")  # noqa: E731
    routes.install_berth_parking_routes(app, console=SimpleNamespace(trip_refusal=lambda ids: None), task_service=Tasks(),
                                        read_guard=[], operator_guard=[], require_operator=named,
                                        require_named_operator=named, compute_road_plan=plan)
    res = TestClient(app).post("/api/fleet/robots/rosy_46/road-nav2", json={"x": 0.0, "y": 0.0},
                               headers={"Idempotency-Key": "k1"})
    body = res.json()
    assert res.status_code == 200 and body["queued"] is True and body["dispatched"] is False


def test_only_a_measured_stop_face_counts_as_a_berth_park():
    from fleet.server.ledger.berth_parking_helpers import BERTH_SUCCESS_REASONS
    assert "dock_stop_face_reached" in BERTH_SUCCESS_REASONS
    assert not {"completed", "reverse_timeout", "emergency_latched", "emergency_during_forward"} & BERTH_SUCCESS_REASONS

def test_road_nav2_plan_route_returns_plan_without_dispatch_and_rejects_bad_query():
    app = FastAPI()
    seen = {}

    async def fake_compute_road_plan(request, robot_id, x, y, yaw, place_id, label):
        seen.update(robot_id=robot_id, x=x, y=y, yaw=yaw, place_id=place_id, label=label)
        return {"robot_id": robot_id, "places": ["P1", place_id], "edges": ["bay_1"], "length_m": 0.2}

    install_berth_parking_routes(
        app, console=None, task_service=None, read_guard=[], operator_guard=[],
        require_operator=lambda: SitePrincipal(principal_id="op-test", role="operator"),
        require_named_operator=lambda: SitePrincipal(principal_id="op-test", role="operator"),
        compute_road_plan=fake_compute_road_plan,
    )
    client = TestClient(app)
    res = client.get("/api/fleet/robots/rosy_46/road-nav2/plan",
                     params={"x": 0.1, "y": 0.2, "yaw": 1.5, "place_id": "C1", "label": "charge 1"})
    assert res.status_code == 200
    assert res.json() == {"planned": True, "dispatched": False, "robot_id": "rosy_46",
                          "places": ["P1", "C1"], "edges": ["bay_1"], "length_m": 0.2}
    assert seen == {"robot_id": "rosy_46", "x": 0.1, "y": 0.2, "yaw": 1.5, "place_id": "C1", "label": "charge 1"}
    assert client.get("/api/fleet/robots/rosy_46/road-nav2/plan", params={"x": "not-a-number"}).status_code == 422
