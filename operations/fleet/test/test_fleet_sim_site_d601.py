"""D-601 B in SIM: every Fleet that drives Gazebo robots loads the shared SIM site config, whose
``fleet.trip.lane_camera_check: false`` keeps lane plans from being refused for the missing preview."""

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
SIM_SITE = "integrations/simulation/gazebo/config/fleet_sim_site.yaml"
# Every place that starts a Fleet against Gazebo SIM robots.
SIM_FLEETS = (
    "tools/run_fleet_sim.sh",
    "tools/validation/fleet_gazebo/run.py",
    "tools/sim/d395_s1_bench.py",
    "docs/validation/d407-gazebo-console-rerun-2026-10-02/evidence/console.sh",
    "docs/validation/lane-trip-lap-sim-2026-10-08/evidence/lap_fleet.py",
    "docs/validation/lane-west-bend-candidate-2026-10-09/evidence/lap_fleet.py",
)


def test_every_sim_fleet_loads_the_shared_sim_site_config():
    config = _trip_config(SimpleNamespace(site_config=REPO / SIM_SITE))
    assert config.lane_camera_check is False
    missing = [p for p in SIM_FLEETS if Path(SIM_SITE).name not in (REPO / p).read_text(encoding="utf-8")]
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
