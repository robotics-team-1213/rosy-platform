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
        assert spec["bay_pose"]["y"] == 0.470
        assert spec["stop_face_rg_m"] > 0.0


def test_berth_parking_status_and_dispatch_routes():
    app = FastAPI()

    class DummyConsole:
        def trip_refusal(self, ids):
            return None

        async def goal(self, robot_id: str, x: float, y: float, yaw: float) -> dict:
            return {"accepted": True, "robot_id": robot_id, "x": x, "y": y, "yaw": yaw, "queued": False}

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
        json={"bay_id": "C1", "mode": "forward_and_berth_park", "forward_m": 0.20,
              "execute_physical": False},
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


def test_road_nav2_plan_route_returns_plan_without_dispatch_and_rejects_bad_query():
    app = FastAPI()
    seen = {}

    async def fake_compute_road_plan(request, robot_id, x, y, yaw, place_id, label):
        seen.update(robot_id=robot_id, x=x, y=y, yaw=yaw, place_id=place_id, label=label)
        return {"robot_id": robot_id, "places": ["P1", place_id], "edges": ["bay_1"], "length_m": 0.2}

    install_berth_parking_routes(
        app, console=None, task_service=None, read_guard=[], operator_guard=[],
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


def _berth_client(*, task_service, principal_dep, plan, execute_physical=False):
    app = FastAPI()
    calls = []

    class Console:
        def trip_refusal(self, ids):
            return None

        async def goal(self, *a):
            calls.append(a)
            return {"accepted": True}

    async def fake_plan(request, robot_id, x, y, yaw, place_id, label):
        return plan

    install_berth_parking_routes(
        app, console=Console(), task_service=task_service, read_guard=[], operator_guard=[],
        require_named_operator=principal_dep, compute_road_plan=fake_plan,
    )
    return TestClient(app), calls


_PLAN = {"target_nav2": {"x": 0.1, "y": 0.2, "yaw": 0.0}, "waypoints_site": [], "length_m": 0.2, "eta_s": 5.0}
_OP = lambda: SitePrincipal(principal_id="op-test", role="operator")  # noqa: E731
_BODY = {"execute_physical": False}
_URL = "/api/fleet/robots/rosy_46/berth-park"


def test_berth_park_requires_named_operator():
    from fastapi import HTTPException

    def unnamed():
        raise HTTPException(403, {"code": "NAMED_OPERATOR_REQUIRED"})

    client, calls = _berth_client(task_service=None, principal_dep=unnamed, plan=_PLAN)
    assert client.post(_URL, json=_BODY).status_code == 403
    assert calls == []


def test_berth_park_requires_idempotency_key_with_task_service():
    class Tasks:
        async def submit_navigation(self, **kw):
            raise AssertionError("must not submit")

    client, calls = _berth_client(task_service=Tasks(), principal_dep=_OP, plan=_PLAN)
    res = client.post(_URL, json=_BODY)
    assert res.status_code == 400 and res.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert calls == []


def test_berth_park_submit_failure_is_refused_not_accepted_and_skips_console_goal():
    class Tasks:
        async def submit_navigation(self, **kw):
            raise OSError("hub down")

    client, calls = _berth_client(task_service=Tasks(), principal_dep=_OP, plan=_PLAN)
    res = client.post(_URL, json=_BODY, headers={"Idempotency-Key": "k1"})
    assert res.status_code >= 400
    assert "accepted" not in res.json() and calls == []


def test_berth_park_missing_pose_is_refused():
    from fastapi import HTTPException
    from fleet.server.ledger.task_dispatch_helpers import compute_road_plan

    class Console:
        async def trusted_map_pose(self, rid):
            return None

    class Req:
        class app:
            class state:
                pass

    import asyncio
    try:
        asyncio.run(compute_road_plan(Console(), Req, "rosy_46", 0.0, 0.0, None, None, ""))
    except HTTPException as exc:
        assert exc.status_code == 409 and exc.detail["code"] == "ROUTE_POSE_UNTRUSTED"
    else:
        raise AssertionError("expected refusal")
