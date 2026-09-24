"""Stage-3 parking dock wired into CORE (sim only).

The sim overlay (gz_sim config/map_v2_fleet_core.yaml) turns docking on and
seeds the parking dock, but only under runtime.mode simulation; the docking
API takes the DOCKING mode (the docking slot only reaches the wheels in
DOCKING) and refuses while line following holds the slot; the
bridge hands the mode back when docking stops moving the robot.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest
import yaml

from core_common.protocol.schemas import DockState
from core_features.command.arbitration import Mode
from core_features.command.manager import Twist
from core_features.docking.feed import FeedDetector
from core.bridge import docking_mode

ROOT = Path(__file__).resolve().parents[4]
OVERLAY = ROOT / "src" / "sim" / "gz_sim" / "config" / "map_v2_fleet_core.yaml"
BUILD_WORLD = ROOT / "src" / "core" / "control" / "map" / "map_v2_fleet" / "scripts" / "build_world.py"
GRAPH = ROOT / "src" / "core" / "control" / "map" / "map_v2_fleet" / "lane_graph.yaml"
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}


def overlay():
    return yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))


def sim_overrides(**runtime):
    data = overlay()
    return {"runtime": dict(data["runtime"], **runtime), "docking": data["docking"]}


def test_the_overlay_declares_the_wedge_parking_dock():
    docking = overlay()["docking"]
    assert docking["simulation_supported"] is True
    (dock_type,) = docking["seed"]["dock_types"]
    (dock,) = docking["seed"]["docks"]
    assert dock_type["detector"] == "observation" and dock_type["tag_id"] == 7
    assert (dock_type["staging"], dock_type["approach"], dock_type["settle"]) == \
        (False, "pose", "pose")
    assert dock_type["undock_distance_m"] == 0.27
    assert dock_type["undock_turn_rad"] == pytest.approx(math.pi / 2, abs=1e-6)
    assert dock["type"] == dock_type["name"]
    spot = yaml.safe_load(GRAPH.read_text(encoding="utf-8"))["parking"]
    assert (dock["x"], dock["y"], dock["yaw"]) == pytest.approx(tuple(spot["spot"]))


def test_the_tag_offset_is_the_world_markers_geometry():
    spec = importlib.util.spec_from_file_location("build_world_for_offset", BUILD_WORLD)
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    centre_x = build.DOCK_TAG_BOTTOM_X + build.DOCK_TAG_FACE_M / 2 * math.cos(
        build.DOCK_TAG_TILT_RAD)
    (dock_type,) = overlay()["docking"]["seed"]["dock_types"]
    (dock,) = overlay()["docking"]["seed"]["docks"]
    assert dock_type["tag_offset_m"] == pytest.approx(centre_x - dock["x"], abs=1e-4)
    assert dock_type["tag_size_m"] == build.DOCK_TAG_SIZE_M


def test_in_simulation_the_overlay_enables_and_seeds_docking(core_client):
    _, services = core_client(config_overrides=sim_overrides())
    assert services.capability.supports("docking.supported")
    assert [d.id for d in services.docking.database.list()] == ["parking"]
    dock = services.docking.database.get("parking")
    detector = services.docking._detector_factory(dock, services.docking.database.type_of("parking"))
    assert isinstance(detector, FeedDetector)


def test_outside_simulation_the_same_block_changes_nothing(core_client):
    overrides = sim_overrides(mode="hardware")
    _, services = core_client(config_overrides=overrides)
    assert not services.capability.supports("docking.supported")
    assert services.docking.database.list() == []


def test_the_dock_api_takes_the_docking_mode_and_its_twist_reaches_the_wheels(core_client):
    client, services = core_client(config_overrides=sim_overrides())
    services.command.select_output()     # settle readiness state, if any
    response = client.post("/api/v1/docking/dock", json={"dock": "parking"}, headers=OPERATOR)
    assert response.status_code == 200, response.text
    assert services.modes.mode is Mode.DOCKING
    services.command.set_docking_twist(Twist(linear=0.03, angular=0.1))
    out = services.command.select_output()
    assert (out.linear, out.angular) == pytest.approx((0.03, 0.1))


def test_docking_is_refused_while_line_following(core_client):
    client, services = core_client(config_overrides=sim_overrides())
    services.line_follow.set_mode("CAMERA_LINE")
    response = client.post("/api/v1/docking/dock", json={"dock": "parking"}, headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LINE_FOLLOW_ACTIVE" \
        if "error" in response.json() else "LINE_FOLLOW_ACTIVE" in response.text
    assert services.docking.state is DockState.UNDOCKED
    assert services.modes.mode is not Mode.DOCKING


class StillExecutor:
    """ros_bridge's DockingExecutor, standing at the spur entry."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None

    def odometry_pose(self):
        return (-1.2696, 0.0, math.pi / 2)

    def travelled_m(self):
        return 0.0

    def odometry_available(self):
        return True


def test_docking_releases_the_mode_once_it_stops_moving(core_client):
    client, services = core_client(config_overrides=sim_overrides())
    services.docking.executor = StillExecutor()
    client.post("/api/v1/docking/dock", json={"dock": "parking"}, headers=OPERATOR)
    services.docking.tick()
    assert services.modes.mode is Mode.DOCKING                 # still docking
    services.docking.cancel()
    assert services.modes.mode is Mode.IDLE
    services.docking.tick()
    assert services.modes.mode is Mode.IDLE                    # nothing to release


def test_the_docking_tick_is_fast_only_for_a_moving_parking_run():
    assert [docking_mode.due(k, fast=False) for k in range(1, 9)] == \
        [False, False, False, True, False, False, False, True]
    assert all(docking_mode.due(k, fast=True) for k in range(1, 9))
