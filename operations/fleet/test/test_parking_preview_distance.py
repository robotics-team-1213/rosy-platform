"""The snapped road can end at P1 even though the measured robot is still beside it."""
from hashlib import sha256
import math

from fastapi.testclient import TestClient
import pytest

from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_ports import TripConfig
from fleet.site_map import SiteMap
from fleet.swarm.robots import RobotEndpoint
from rosy.world.state.projections.map_pose import MapPose
from test_trip_nav2_route import RouteFakeRobot


@pytest.mark.parametrize("xy", [(-.47, -.05), (-.43002, .04266)])
def test_preview_measures_from_site_pose_before_snapping(tmp_path, xy):
    p1, c1 = (-.43002, .04266), (-.41816, .47)
    model = SiteMap.model_validate({
        "map_id": "parking-test", "places": [
            {"id": "P1", "name": "P1", "kind": "junction", "x": p1[0], "y": p1[1]},
            {"id": "C1", "name": "C1", "kind": "charge", "x": c1[0], "y": c1[1], "yaw": -math.pi / 2}],
        "edges": [{"id": "bay_1", "from": "P1", "to": "C1", "direction": "two_way", "drive_mode": "lane",
                   "width_m": .18, "speed_cap_mps": .05, "polyline": [p1, [-.4342, .1845], [-.4354, .3294], c1]}]})
    store = SiteMapStore(tmp_path / "site.sqlite")
    store.import_if_empty(model, source="test")
    robot = RouteFakeRobot("rosy_42")
    console = FleetConsole([RobotEndpoint("rosy_42", "http://127.0.0.1:8081", "t")], [robot])
    users = {sha256(b"op-tok").hexdigest(): {"principal_id": "bob", "role": "operator"}}
    app = create_app(console, site_maps=store, site_users=users, trip_config=TripConfig(map_binding_required=False))

    async def pose(_):
        return MapPose(*xy, -math.pi / 2, "LOCALIZED", "sighting", 0., 0., anchor_age_s=0., map_id=model.map_id)

    app.state.trip_runner.map_pose = pose
    with TestClient(app) as client:
        reply = client.post("/api/fleet/robots/rosy_42/trip", json={"to": "C1", "drive_mode": "nav2"},
                            headers={"Authorization": "Bearer op-tok"})
        assert reply.status_code == 200, reply.text
        plan = reply.json()
        assert plan["parking_handoff"]["staging_place_id"] == "P1"
        assert plan["length_m"] == 0
        assert len(plan["segments"]) == (0 if xy == p1 else 1)
        assert plan["staging_distance_m"] == round(math.dist(xy, p1), 4)
        assert not robot.routes
