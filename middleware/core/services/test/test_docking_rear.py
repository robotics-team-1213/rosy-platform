"""Rear USB dock (approach="rear", D-950 follow-up) through DockingManager.

A kinematic unicycle stages by a teleporting Nav2 stub, reads the dock from a
LiDAR-V detector built from the true pose (5 Hz), aligns outside the rails,
reverses straight inside them and stops on the stop face. The pack voltage
rises only when the robot is docked squarely. Design:
Rosy/docs/research/pinky-usb-dock-guide-2026-11-01/README.md 「벽 마찰 · 롤러 · LiDAR 표지」.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from core_common.protocol.schemas import DockState, NavigationState
from core_features.docking.database import DockDatabase, DockInstance, DockType
from core_features.docking.detector import DockObservation, SimulatedDetector, select_detector
from core_features.docking.feed import LIDAR_V, DockObservationFeed, FeedDetector
from core_features.docking.manager import DockingConfig, DockingManager, DockPhase
from core_features.docking.rear_phases import rear_errors

DT = 0.05
DOCKED_ALONG = 0.1205          # stop face -> base_link when the bed back touches (scad bo + 74.5 mm)
NECK = (0.30, 0.003)           # inside 0.30 m the body neck holds the robot within +-3 mm
REAR = dict(name="rear-usb", detector="lidar_v", approach="rear", staging_offset_m=0.85,
            rail_entry_m=0.45, max_retries=3)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class World:
    """Dock at the origin, inward axis +x; the stop face holds base_link at -DOCKED_ALONG."""

    def __init__(self):
        self.pose = (-1.5, 0.0, 0.0)
        self.command = (0.0, 0.0)
        self.commands = []
        self.goals = []
        self.mark = self.pose
        self.manager = None
        self.arrival_error = (0.0, 0.0)

    def navigate_to(self, pose):
        self.goals.append(pose)
        dy, dyaw = self.arrival_error
        self.pose = (pose.x, pose.y + dy, pose.yaw + dyaw)
        self.manager.on_navigation_state(NavigationState.ARRIVED)

    def cancel_navigation(self):
        pass

    def drive(self, linear, angular):
        self.command = (float(linear), float(angular))
        self.commands.append((self.manager.phase, self.command))

    def stop(self):
        self.command = (0.0, 0.0)

    def set_collision_exemption(self, enabled):
        pass

    def travelled_m(self):
        return math.dist(self.mark[:2], self.pose[:2])

    def reset_odometry_mark(self):
        self.mark = self.pose

    def step(self):
        v, w = self.command
        x, y, yaw = self.pose
        mid = yaw + w * DT / 2
        x, y = x + v * DT * math.cos(mid), y + v * DT * math.sin(mid)
        if x > -NECK[0]:                                   # the walls, kinematically
            y = max(-NECK[1], min(NECK[1], y))
        self.pose = (min(x, -DOCKED_ALONG), y, yaw + w * DT)   # the stop face


class VDetector:
    """The dock origin and inward axis in base_link, from the true pose, 5 Hz."""

    def __init__(self, world, clock):
        self.world, self.clock, self.started, self.latest = world, clock, False, None

    def start(self, dock=None):
        self.started = True

    def stop(self):
        self.started = False

    def capture(self):
        x, y, yaw = self.world.pose
        c, s = math.cos(yaw), math.sin(yaw)
        self.latest = DockObservation(x=c * -x + s * -y, y=-s * -x + c * -y,
                                      yaw=math.atan2(-s, c), confidence=0.9, at=self.clock())

    def relative_pose(self):
        return self.latest if self.started else None


class Battery:
    """Rises only with the robot on the stop face and square to the dock."""

    def __init__(self, world, clock, charges=True):
        self.world, self.clock, self.charges, self.since = world, clock, charges, None
        self.charging_flags = []

    @property
    def voltage(self):
        x, y, yaw = self.world.pose
        seated = x >= -DOCKED_ALONG - 1e-9 and abs(y) <= 0.003 \
            and abs(math.atan2(math.sin(yaw - math.pi), math.cos(yaw - math.pi))) <= math.radians(1.5)
        if not (self.charges and seated):
            self.since = None
            return 7.60
        self.since = self.clock() if self.since is None else self.since
        return 7.60 + 0.004 * (self.clock() - self.since)

    def set_charging(self, flag):
        self.charging_flags.append(flag)


def a_rear(*, charges=True, **type_kwargs):
    clock, world = Clock(), World()
    detector = VDetector(world, clock)
    db = DockDatabase.empty()
    db.add_type(DockType(**dict(REAR, **type_kwargs)))
    db.add(DockInstance(id="rear", type="rear-usb", x=0.0, y=0.0, yaw=0.0))
    events, safety = [], SimpleNamespace(estop=False)
    manager = DockingManager(
        database=db, safety=safety, config=DockingConfig(), clock=clock,
        detector_factory=lambda dock, dock_type: detector,
        capability_provider=lambda: True, battery=Battery(world, clock, charges),
        events=SimpleNamespace(publish=lambda t, **kw: events.append((t, kw.get("data")))))
    manager.executor = world
    world.manager = manager
    return SimpleNamespace(manager=manager, world=world, detector=detector, clock=clock,
                           events=events, safety=safety)


def run(p, until, max_s=240.0):
    phases, k, t0 = [], 0, p.clock.now
    while p.clock.now - t0 < max_s:
        if k % 4 == 0:
            p.detector.capture()
        p.manager.tick()
        phase = p.manager.phase.value if p.manager.phase else None
        if not phases or phases[-1] != (p.manager.state.value, phase):
            phases.append((p.manager.state.value, phase))
        if until(p.manager):
            break
        p.world.step()
        p.clock.now += DT
        k += 1
    return phases


def done(manager):
    return manager.state in (DockState.DOCKED, DockState.DOCK_FAILED, DockState.UNDOCKED) \
        and manager.phase is None


@pytest.mark.parametrize("dy", [-0.04, 0.0, 0.04])
@pytest.mark.parametrize("dyaw_deg", [-6.0, 0.0, 6.0])
def test_it_aligns_outside_the_rails_then_reverses_straight_and_docks(dy, dyaw_deg):
    p = a_rear()
    p.world.arrival_error = (dy, math.radians(dyaw_deg))
    p.manager.dock()
    phases = run(p, done)
    assert p.manager.state is DockState.DOCKED, phases
    order = [ph for _, ph in phases if ph]
    # dock() stages at once (the Nav2 stub arrives in navigate_to); the first tick acquires.
    assert order[:4] == ["acquiring", "aligning", "reversing", "settling"], order
    # Staging faces away from the dock: the back looks down the dock axis.
    assert p.world.goals[0].yaw == pytest.approx(math.pi)
    assert p.world.goals[0].x == pytest.approx(-0.85)
    # Inside the rails the heading is never corrected (the walls would win).
    reversing = [cmd for phase, cmd in p.world.commands if phase is DockPhase.REVERSING]
    assert reversing and all(w == 0.0 and v < 0.0 for v, w in reversing)
    x, y, yaw = p.world.pose
    assert abs(y) <= 0.003 and x == pytest.approx(-DOCKED_ALONG)


def test_a_flat_pack_voltage_retries_from_staging_then_fails():
    p = a_rear(charges=False)
    p.manager.dock()
    phases = run(p, done, max_s=400.0)
    assert p.manager.state is DockState.DOCK_FAILED, phases
    retries = [d for t, d in p.events if t == "docking.retry"]
    assert [r["attempt"] for r in retries] == [1, 2, 3]
    assert all(r["reason"] == "no charge after contact" for r in retries)
    assert p.manager.status().error == "no charge after contact"
    # Backing off a rear dock means driving forward, out of the rails.
    backoff = [cmd for phase, cmd in p.world.commands if phase is DockPhase.BACKOFF]
    assert backoff and all(v > 0.0 and w == 0.0 for v, w in backoff)
    assert len(p.world.goals) == 4


def test_misaligned_at_the_rail_entry_never_enters_the_rails():
    p = a_rear(rear_align_tolerance_m=1e-6)
    p.world.arrival_error = (0.03, 0.0)
    p.manager.dock()
    phases = run(p, done)
    assert p.manager.state is DockState.DOCK_FAILED
    assert p.manager.status().error == "misaligned at the rail entry"
    assert "reversing" not in [ph for _, ph in phases]


def test_estop_while_reversing_fails_and_stops():
    p = a_rear()
    p.manager.dock()
    run(p, lambda m: m.phase is DockPhase.REVERSING)
    assert p.manager.fast_tick
    p.safety.estop = True
    p.manager.tick()
    assert p.manager.state is DockState.DOCK_FAILED
    assert p.world.command == (0.0, 0.0)


def test_undocking_a_rear_dock_drives_forward():
    p = a_rear()
    p.manager.dock()
    run(p, done)
    assert p.manager.state is DockState.DOCKED
    p.world.commands.clear()
    p.manager.undock()
    run(p, done, max_s=30.0)
    assert p.manager.state is DockState.UNDOCKED
    assert p.world.commands and all(v > 0.0 for _, (v, _w) in p.world.commands)
    assert p.world.pose[0] < -DOCKED_ALONG - 0.3


def test_rear_errors_read_the_observation_in_the_dock_frame():
    # Back squarely to the dock, 0.5 m out, 20 mm to the robot's left of the axis.
    obs = DockObservation(x=-0.5, y=-0.02, yaw=math.pi, confidence=1.0, at=0.0)
    along, lateral, heading = rear_errors(obs)
    assert along == pytest.approx(0.5)
    assert abs(lateral) == pytest.approx(0.02)
    assert heading == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("bad", [dict(detector="observation"), dict(rail_entry_m=0.9),
                                 dict(rail_entry_m=0.0), dict(staging=False),
                                 dict(rear_align_tolerance_rad=0.0)])
def test_a_rear_type_must_be_consistent(bad):
    with pytest.raises(ValueError):
        DockType(**dict(REAR, **bad))


def lidar_payload(**kwargs):
    body = {"source": LIDAR_V, "stamp": 100.0, "visible": True, "tag_id": None,
            "x": -0.5, "y": 0.0, "yaw": math.pi, "range_m": 0.5, "confidence": 0.8,
            "revision": None}
    body.update(kwargs)
    return body


def test_the_feed_keeps_lidar_and_camera_sightings_apart():
    feed = DockObservationFeed()
    assert feed.ingest(lidar_payload(), received_at=1.0, source_now=100.0)
    # A camera miss does not erase the LiDAR sighting.
    assert not feed.ingest({"source": "CAMERA_TAG", "stamp": 100.0, "visible": False},
                           received_at=1.0, source_now=100.0)
    assert feed.latest(source=LIDAR_V).x == -0.5
    assert feed.latest() is None
    with pytest.raises(ValueError):
        feed.ingest(lidar_payload(tag_id=7), received_at=1.1, source_now=100.1)
    assert feed.latest(source=LIDAR_V) is None


def test_the_lidar_v_detector_is_selected_only_with_a_feed():
    dock = DockInstance(id="rear", type="rear-usb")
    rear = DockType(**REAR)
    assert isinstance(select_detector(dock, rear), SimulatedDetector)
    detector = select_detector(dock, rear, feed=DockObservationFeed(), clock=lambda: 1.0)
    assert isinstance(detector, FeedDetector)
    feed = DockObservationFeed()
    detector = select_detector(dock, rear, feed=feed, clock=lambda: 1.0)
    feed.ingest(lidar_payload(), received_at=1.0, source_now=100.0)
    detector.start()
    assert detector.relative_pose().yaw == pytest.approx(math.pi)
