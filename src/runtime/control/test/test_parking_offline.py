"""Offline check of the stage-3 final approach (design §6): rendered frames
of the 260919 paint plus the wedge tag through the Gazebo camera model,
control's DockTagObserver, CORE's dock feed and DockingManager with the sim
overlay's parking type, on a kinematic robot. From the spur entry with
+-20 mm / +-5 deg tour-end errors it must park within 20 mm / 5 deg.

Frames are 5 Hz with 0.1 s delivery latency; CORE ticks at 20 Hz. Two
corner cases run by default; the whole 3 x 3 grid with `-m drift`.
"""

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import dock_scene
import lane_sim

REPO_ROOT = Path(__file__).parents[4]
_PACKAGE_ROOTS = {
    "core_common": "src/contracts/core_common",
    "core_events": "src/runtime/core_events",
    "core_features": "src/runtime/core_features",
}
for _package in _PACKAGE_ROOTS:
    _path = str(REPO_ROOT / _PACKAGE_ROOTS[_package])
    if _path not in sys.path:
        sys.path.insert(0, _path)

from core_common.protocol.schemas import DockState  # noqa: E402
from core_features.docking.database import DockDatabase, DockInstance, DockType  # noqa: E402
from core_features.docking.detector import select_detector  # noqa: E402
from core_features.docking.feed import DockObservationFeed  # noqa: E402
from core_features.docking.manager import DockingManager, DockPhase  # noqa: E402

from control.sensing.dock_observer import DockTagObserver  # noqa: E402
from control.sensing.dock_tag import CameraMount  # noqa: E402

OVERLAY = REPO_ROOT / "src/sim/gz_sim/config/map_v2_fleet_core.yaml"
DT = 0.05
LATENCY_TICKS = 2
LOOKING = (DockPhase.ACQUIRING, DockPhase.APPROACHING, DockPhase.ALIGNING, DockPhase.SETTLING)


@pytest.fixture(scope="module")
def world():
    return lane_sim.stl_world()


def park(world, start, max_s=120.0):
    seed = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))["docking"]["seed"]
    db = DockDatabase.empty()
    for item in seed["dock_types"]:
        db.add_type(DockType.model_validate(item))
    for item in seed["docks"]:
        db.add(DockInstance.model_validate(item))
    clock = SimpleNamespace(now=0.0)
    feed = DockObservationFeed()
    robot = SimpleNamespace(pose=tuple(start), command=(0.0, 0.0), mark=tuple(start))
    executor = SimpleNamespace(
        navigate_to=lambda pose: pytest.fail("parking must not stage through Nav2"),
        cancel_navigation=lambda: None,
        drive=lambda v, w: setattr(robot, "command", (float(v), float(w))),
        stop=lambda: setattr(robot, "command", (0.0, 0.0)),
        set_collision_exemption=lambda enabled: None,
        travelled_m=lambda: math.dist(robot.mark[:2], robot.pose[:2]),
        reset_odometry_mark=lambda: setattr(robot, "mark", robot.pose),
        odometry_pose=lambda: robot.pose)
    manager = DockingManager(
        database=db, safety=SimpleNamespace(estop=False), clock=lambda: clock.now,
        detector_factory=lambda dock, dock_type: select_detector(
            dock, dock_type, feed=feed, clock=lambda: clock.now),
        capability_provider=lambda: True, pose_provider=lambda: robot.pose)
    manager.executor = executor
    observer = DockTagObserver(
        tag_id=7, tag_size_m=0.05, hfov_rad=dock_scene.HFOV,
        mount=CameraMount(height_m=dock_scene.HEIGHT_M, pitch_rad=dock_scene.PITCH_RAD,
                          x_offset_m=dock_scene.CAM_X))
    manager.dock("parking")
    in_flight, frames, k = [], 0, 0
    while clock.now < max_s and manager.state is DockState.DOCKING:
        if k % 4 == 0 and manager.phase in LOOKING:
            in_flight.append((k + LATENCY_TICKS, clock.now,
                              observer.observe(dock_scene.render(robot.pose, world=world),
                                               clock.now)))
            frames += 1
        while in_flight and in_flight[0][0] <= k:
            _, stamp, payload = in_flight.pop(0)
            feed.ingest(payload, received_at=clock.now, source_now=clock.now)
        manager.tick()
        v, w = robot.command
        x, y, yaw = robot.pose
        mid = yaw + w * DT / 2
        robot.pose = (x + v * DT * math.cos(mid), y + v * DT * math.sin(mid), yaw + w * DT)
        clock.now += DT
        k += 1
    x, y, yaw = robot.pose
    dyaw = math.degrees(math.atan2(math.sin(yaw), math.cos(yaw)))
    return SimpleNamespace(state=manager.state, error_m=math.hypot(x + 1.0, y),
                           dyaw_deg=dyaw, sim_s=clock.now, frames=frames,
                           reseats=manager.reseats, retries=manager.retries, pose=robot.pose)


def _check(world, dy, dyaw_deg):
    start = (dock_scene.ENTRY[0], dy, math.pi / 2 + math.radians(dyaw_deg))
    r = park(world, start)
    print(f"offline park dy={dy:+.3f} dyaw={dyaw_deg:+.0f}: {r.state.value} "
          f"err={r.error_m * 1000:.1f} mm dyaw={r.dyaw_deg:+.2f} deg "
          f"sim={r.sim_s:.1f} s frames={r.frames} reseats={r.reseats} retries={r.retries}")
    assert r.state is DockState.DOCKED, r
    assert r.error_m <= 0.020 and abs(r.dyaw_deg) <= 5.0, r


@pytest.mark.parametrize("dy,dyaw_deg", [(0.02, 5.0), (-0.02, -5.0)])
def test_rendered_parking_converges_from_corner_entry_errors(world, dy, dyaw_deg):
    _check(world, dy, dyaw_deg)


@pytest.mark.drift
@pytest.mark.parametrize("dy", [-0.02, 0.0, 0.02])
@pytest.mark.parametrize("dyaw_deg", [-5.0, 0.0, 5.0])
def test_rendered_parking_grid(world, dy, dyaw_deg):
    _check(world, dy, dyaw_deg)
