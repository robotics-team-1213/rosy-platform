"""Fleet berth-park mode core_line: never a plain Nav2 goal at the bay (D-1042 safety review F3)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.ledger.berth_parking_routes import install_berth_parking_routes
from fleet.server.site_auth import SitePrincipal


def test_core_line_never_falls_back_to_a_plain_nav2_goal():
    sent = []

    async def plan(*args):
        return {"target_nav2": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "waypoints_site": []}

    async def dispatch_nav(**kw):
        sent.append(kw)
        return {"accepted": True}
    app = FastAPI()
    op = lambda: SitePrincipal(principal_id="op", role="operator")  # noqa: E731
    install_berth_parking_routes(app, console=SimpleNamespace(trip_refusal=lambda ids: None, _clients={}),
                                 task_service=None, read_guard=[], operator_guard=[], require_operator=op,
                                 require_named_operator=op, compute_road_plan=plan, dispatch_nav=dispatch_nav)
    client = TestClient(app)
    res = client.post("/api/fleet/robots/rosy_45/berth-park", json={"bay_id": "C3", "mode": "core_line"})
    assert res.status_code == 502 and sent == []
    res = client.post("/api/fleet/robots/rosy_45/berth-park",
                      json={"bay_id": "C3", "mode": "core_line", "execute_physical": False})
    assert res.status_code == 400 and sent == []
