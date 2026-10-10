"""D-601 in SIM: every Fleet that drives Gazebo robots loads one of two shared SIM site configs.
No-camera SIM (gz_multi) keeps ``lane_camera_check: false`` so lane plans are not refused for the
missing preview; camera SIM launches run sim_jpeg_relay.py and check the preview as on a device."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from fleet.cli import _trip_config
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.site_map import from_lane_graph
from fleet.swarm.robots import RobotEndpoint
from fakes import FakeRobot
from test_site_map_trip import LANE_GRAPH, OPERATOR, _on_ring_s

REPO = Path(__file__).resolve().parents[3]
SIM_SITE = "integrations/simulation/gazebo/config/fleet_sim_site.yaml"  # no camera
SIM_CAMERA_SITE = "integrations/simulation/gazebo/config/fleet_sim_camera_site.yaml"
# Every place that starts a Fleet against Gazebo SIM robots -> the shared config it loads.
SIM_FLEETS = {
    "tools/run_fleet_sim.sh": SIM_SITE,  # gz_multi start_camera:=false
    "tools/validation/fleet_gazebo/run.py": SIM_SITE,  # gz_multi
    "tools/sim/d395_s1_bench.py": SIM_SITE,  # gz_multi
    "docs/validation/d407-gazebo-console-rerun-2026-10-02/evidence/console.sh": SIM_CAMERA_SITE,
    "docs/validation/lane-trip-lap-sim-2026-10-08/evidence/lap_fleet.py": SIM_CAMERA_SITE,
    "docs/validation/lane-west-bend-candidate-2026-10-09/evidence/lap_fleet.py": SIM_CAMERA_SITE,
}
# Camera SIM launches that publish CORE's front preview through the relay.
CAMERA_LAUNCHES = (
    "integrations/simulation/gazebo/launch/map_v2_fleet_lane.launch.py",
    "integrations/simulation/gazebo/launch/map_v2_fleet_real.launch.py",
    "docs/validation/d495-junction-sim-2026-10-07/evidence/d495_real.launch.py",
    "docs/validation/lane-west-bend-candidate-2026-10-09/evidence/closed_loop.launch.py",
    "docs/validation/d407-gazebo-console-rerun-2026-10-02/evidence/run_sim.sh",
)


def test_every_sim_fleet_loads_the_shared_sim_site_config_for_its_camera():
    assert _trip_config(SimpleNamespace(site_config=REPO / SIM_SITE)).lane_camera_check is False
    assert _trip_config(SimpleNamespace(site_config=REPO / SIM_CAMERA_SITE)).lane_camera_check is True
    wrong = [p for p, site in SIM_FLEETS.items() if Path(site).name not in (REPO / p).read_text(encoding="utf-8")]
    assert wrong == []


def test_camera_sim_launches_publish_the_front_preview():
    missing = [p for p in CAMERA_LAUNCHES if "sim_jpeg_relay" not in (REPO / p).read_text(encoding="utf-8")]
    assert missing == []


def test_a_sim_lane_plan_is_not_refused_for_the_missing_front_preview(tmp_path):
    robot = FakeRobot("rosy_60", state={})
    robot.front_status_value = {"available": False, "stale": True, "age_ms": None}  # SIM CORE: no preview
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [robot])
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    store.import_if_empty(from_lane_graph(LANE_GRAPH), source="lane_graph.yaml")
    robot._state = _on_ring_s(store)
    users = {sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"}}
    app = create_app(console, site_maps=store, site_users=users,
                     task_service=FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"}),
                     trip_config=_trip_config(SimpleNamespace(site_config=REPO / SIM_SITE)))
    plan = TestClient(app).post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR)
    assert plan.status_code == 200, plan.text
