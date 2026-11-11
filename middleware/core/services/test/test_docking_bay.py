"""Charge bay pink guide line (approach="line", D-1013) through DockingManager.

A kinematic unicycle stages by a teleporting Nav2 stub (facing the bay), turns
180 deg in place on odometry, creeps to settle the caster, then reverses along
the virtual dock observation (the guide line) with the gate/coast/scan ladder
until the guide stalls it; the pack voltage then rises (D-941 numbers).
`travelled_m` is wheel odometry: against the 3D guide the wheels spin while the
body is held, so contact must come from the slip divergence (odometry advances,
the line observation stands still), not from a stall.
Design: D-1013 and Rosy/docs/research/charge-bay-pink-line-2026-11-10/.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from core_common.protocol.schemas import DockState, NavigationState
from core_features.docking.database import DockDatabase, DockInstance, DockType
from core_features.docking.detector import DockObservation, select_detector
from core_features.docking.feed import CAMERA_LINE, DockObservationFeed
from core_features.docking.manager import DockingConfig, DockingManager, DockPhase

DT = 0.05
DOCKED_ALONG = 0.05           # stop face -> base_link at guide contact
NECK = (0.10, 0.006)          # inside 0.10 m the 3D guide holds the robot within +-6 mm
BAY = dict(name="bay-line", detector="camera_line", approach="line",
           staging_offset_m=0.45, max_retries=3)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class World:
    """Bay at the origin, inward axis +x; the robot arrives at the 교차점 facing it."""

    def __init__(self):
        self.pose = (-1.0, 0.0, 0.0)
        self.command = (0.0, 0.0)
        self.commands = []
        self.goals = []
        self.mark = self.pose
        self.odo = 0.0
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
        return self.odo                       # wheel odometry (spins against the guide)

    def reset_odometry_mark(self):
        self.odo = 0.0

    def odometry_pose(self):
        return self.pose

    def step(self):
        v, w = self.command
        self.odo += abs(v) * DT
        x, y, yaw = self.pose
        mid = yaw + w * DT / 2
        x, y = x + v * DT * math.cos(mid), y + v * DT * math.sin(mid)
        if x > -NECK[0]:                                   # the 3D guide, kinematically
            y = max(-NECK[1], min(NECK[1], y))
        self.pose = (min(x, -DOCKED_ALONG), y, yaw + w * DT)   # the stop face


class LineDetector:
    """The guide line as the virtual dock: stop-face centre in base_link, 5 Hz.

    `dead_in_phase`/`frozen_in_phase` arm a mode when the manager first reaches
    that phase; `dead` loses the line for good (a lost marker reads as lost),
    `frozen` keeps the last observation while the robot moves (a lying picture),
    `glitch_frames` offsets the lateral by a neighbour-line jump for N captures."""

    def __init__(self, world, clock):
        self.world, self.clock, self.started, self.latest = world, clock, False, None
        self.dead = False
        self.dead_in_phase = None
        self.frozen = False
        self.frozen_in_phase = None
        self.glitch_frames = 0

    def start(self, dock=None):
        self.started = True

    def stop(self):
        self.started = False

    def _arm(self):
        phase = self.world.manager.phase if self.world.manager else None
        if self.dead_in_phase is not None and phase is self.dead_in_phase:
            self.dead = True
        if self.frozen_in_phase is not None and phase is self.frozen_in_phase:
            self.frozen = True

    def capture(self):
        self._arm()
        if self.dead:
            self.latest = None
            return
        if self.frozen and self.latest is not None:
            self.latest = self.latest.model_copy(update={"at": self.clock()})
            return
        x, y, yaw = self.world.pose
        c, s = math.cos(yaw), math.sin(yaw)
        oy = 0.10 if self.glitch_frames > 0 else 0.0
        self.glitch_frames = max(0, self.glitch_frames - 1)
        self.latest = DockObservation(x=c * -x + s * -y, y=-s * -x + c * -y + oy,
                                      yaw=math.atan2(-s, c), confidence=0.9, at=self.clock())

    def relative_pose(self):
        if not self.started or self.latest is None:
            return None
        if self.clock() - self.latest.at > 0.6:
            return None
        return self.latest


class Battery:
    """Rises only when the robot is on the stop face and square to the bay."""

    def __init__(self, world, clock, charges=True):
        self.world, self.clock, self.charges, self.since = world, clock, charges, None
        self.charging_flags = []

    @property
    def voltage(self):
        x, y, yaw = self.world.pose
        seated = x >= -DOCKED_ALONG - 1e-9 and abs(y) <= NECK[1] \
            and abs(math.atan2(math.sin(yaw - math.pi), math.cos(yaw - math.pi))) <= math.radians(2.0)
        if not (self.charges and seated):
            self.since = None
            return 7.60
        self.since = self.clock() if self.since is None else self.since
        return 7.60 + 0.008 * (self.clock() - self.since)

    def set_charging(self, flag):
        self.charging_flags.append(flag)


def a_bay(*, charges=True, **type_kwargs):
    clock, world = Clock(), World()
    detector = LineDetector(world, clock)
    db = DockDatabase.empty()
    db.add_type(DockType(**dict(BAY, **type_kwargs)))
    db.add(DockInstance(id="bay1", type="bay-line", x=0.0, y=0.0, yaw=0.0))
    events, safety = [], SimpleNamespace(estop=False)
    battery = Battery(world, clock, charges)
    manager = DockingManager(
        database=db, safety=safety, config=DockingConfig(), clock=clock,
        detector_factory=lambda dock, dock_type: detector,
        capability_provider=lambda: True, battery=battery,
        events=SimpleNamespace(publish=lambda t, **kw: events.append((t, kw.get("data")))))
    manager.executor = world
    world.manager = manager
    return SimpleNamespace(manager=manager, world=world, detector=detector, clock=clock,
                           events=events, safety=safety, battery=battery)


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


@pytest.mark.parametrize("dy", [-0.03, 0.0, 0.03])
@pytest.mark.parametrize("dyaw_deg", [-3.0, 0.0, 3.0])
def test_it_turns_creeps_aligns_on_the_line_and_docks(dy, dyaw_deg):
    p = a_bay()
    p.world.arrival_error = (dy, math.radians(dyaw_deg))
    p.manager.dock()
    phases = run(p, done)
    assert p.manager.state is DockState.DOCKED, phases
    order = [ph for _, ph in phases if ph]
    # dock() stages at once (the Nav2 stub arrives in navigate_to); the first
    # tick turns away from the bay — the 180 deg is ours, not the staging goal's.
    assert order[:4] == ["turning", "acquiring", "aligning", "settling"], order
    assert p.world.goals[0].yaw == pytest.approx(0.0)
    assert p.world.goals[0].x == pytest.approx(-0.45)
    # The alignment reverses (rear to the bay) and steers while reversing.
    aligning = [cmd for phase, cmd in p.world.commands if phase is DockPhase.ALIGNING]
    assert aligning and all(cmd[0] < 0.0 for cmd in aligning)
    assert any(abs(cmd[1]) > 1e-6 for cmd in aligning)
    # Contact: on the stop face, square, within the guide neck.
    x, y, yaw = p.world.pose
    assert x == pytest.approx(-DOCKED_ALONG, abs=1e-6)
    assert abs(y) <= NECK[1] + 1e-9
    assert abs(math.atan2(math.sin(yaw - math.pi), math.cos(yaw - math.pi))) <= math.radians(2.0)


def test_a_neighbour_line_jump_is_rejected_not_followed():
    p = a_bay()
    p.manager.dock()
    # Three glitched captures (a neighbour bay's line, +10 cm lateral) while aligned.
    p.detector.glitch_frames = 3
    phases = run(p, done)
    assert p.manager.state is DockState.DOCKED, phases
    assert abs(p.world.pose[1]) <= NECK[1] + 1e-9


def test_lost_line_scans_backs_off_then_fails_closed():
    p = a_bay(max_retries=1)
    p.manager.dock()
    p.detector.dead_in_phase = DockPhase.ALIGNING
    phases = run(p, done)
    assert p.manager.state is DockState.DOCK_FAILED, phases
    order = [ph for _, ph in phases if ph]
    assert order[:4] == ["turning", "acquiring", "aligning", "backoff"], order
    # The ladder ran a full retry (turn + acquire) before failing closed.
    assert order.count("acquiring") >= 2, order
    # It never reached the stop face driving blind.
    assert p.world.pose[0] < -NECK[0]


def test_a_frozen_picture_stops_the_push_not_overruns():
    """Wheels spin, the observation stands still: the divergence must stop the
    reverse early (well short of the stop face), never push on to the travel cap."""
    p = a_bay(max_retries=0)
    p.manager.dock()
    p.detector.frozen_in_phase = DockPhase.ALIGNING
    phases = run(p, done, max_s=90.0)
    assert p.manager.state is DockState.DOCK_FAILED, phases
    order = [ph for _, ph in phases if ph]
    assert "settling" in order, order            # divergence read as contact, then no charge
    assert p.world.pose[0] < -NECK[0]            # stopped short of the guide


def test_no_voltage_rise_is_a_retry_not_a_dock():
    p = a_bay(max_retries=1, charges=False)
    p.manager.dock()
    phases = run(p, done, max_s=200.0)
    assert p.manager.state is DockState.DOCK_FAILED, phases
    order = [ph for _, ph in phases if ph]
    assert order.count("settling") >= 1, order
    assert not any(p.battery.charging_flags)


def test_feed_and_detector_selection_carry_the_camera_line_source():
    feed = DockObservationFeed()
    ok = feed.ingest({"source": CAMERA_LINE, "visible": True, "stamp": 10.0, "tag_id": None,
                      "x": 0.2, "y": 0.01, "yaw": math.pi, "confidence": 0.8},
                     received_at=10.2, source_now=10.3)
    assert ok
    detector = select_detector(
        DockInstance(id="b", type="bay-line", x=0.0, y=0.0, yaw=0.0),
        DockType(**BAY), feed=feed, clock=lambda: 10.4)
    assert type(detector).__name__ == "FeedDetector"
    detector.start()                    # the manager starts its detector on acquire
    assert detector.relative_pose() is not None
