"""Stage-3 parking dock through DockingManager, closed loop on a kinematic
robot (docs/plans/2026-09-23-lane-network-parking-design.md §4).

A parking type (no staging, pose approach, pose settle) is driven by a
detector that reports the wedge tag from the true pose at 5 Hz with a
capture latency, and only where the Gazebo camera sees it whole (the
tag's top leaves the view ~0.1 m before the spot). Odometry is the true
pose; CORE's map pose too (Gazebo). The original dock types keep their
behaviour: test_docking.py runs unchanged.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from core_common.protocol.schemas import DockState
from core_features.docking.database import DockDatabase, DockError, DockInstance, DockType
from core_features.docking.detector import DockObservation
from core_features.docking.manager import DockingConfig, DockingManager, DockPhase

SPOT = (-1.0, 0.0, 0.0)
ENTRY_X = -1.2696
TAG = (-0.74979, 0.0)          # tag centre (build_world: bottom edge -0.78, 25 deg)
OFFSET = TAG[0] - SPOT[0]
DT = 0.05


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class World:
    """True pose, a unicycle driven by the executor's last command."""

    def __init__(self, pose):
        self.pose = tuple(pose)
        self.command = (0.0, 0.0)
        self.goals = []
        self.exemption = []
        self.mark = self.pose

    # DockingExecutor
    def navigate_to(self, pose):
        self.goals.append(pose)

    def cancel_navigation(self):
        pass

    def drive(self, linear, angular):
        self.command = (float(linear), float(angular))

    def stop(self):
        self.command = (0.0, 0.0)

    def set_collision_exemption(self, enabled):
        self.exemption.append(bool(enabled))

    def travelled_m(self):
        return math.dist(self.mark[:2], self.pose[:2])

    def reset_odometry_mark(self):
        self.mark = self.pose

    def odometry_pose(self):
        return self.pose

    def step(self, dt=DT):
        v, w = self.command
        x, y, yaw = self.pose
        mid = yaw + w * dt / 2
        self.pose = (x + v * dt * math.cos(mid), y + v * dt * math.sin(mid), yaw + w * dt)


class TagCamera:
    """5 Hz frames, visible while the base is within the camera's reach of
    the whole tag (x >= -1.105 and |bearing| < 30 deg); an observation is
    available LATENCY_S after capture and stamped with its capture time.
    `bias_y` corrupts y (a reseat test)."""

    PERIOD_S = 0.2
    LATENCY_S = 0.1

    def __init__(self, world, clock):
        self.world, self.clock = world, clock
        self.started = False
        self.frames = []
        self.bias_y = 0.0

    def start(self, dock=None):
        self.started = True

    def stop(self):
        self.started = False

    def capture(self):
        x, y, yaw = self.world.pose
        c, s = math.cos(yaw), math.sin(yaw)
        dx, dy = TAG[0] - x, TAG[1] - y
        tx, ty = c * dx + s * dy, -s * dx + c * dy
        seen = x >= -1.105 and abs(math.atan2(ty, tx)) < math.radians(30)
        # The dock axis (+x, yaw 0) seen from the robot.
        obs = DockObservation(x=tx, y=ty + self.bias_y, yaw=math.atan2(-s, c),
                              confidence=0.9, at=self.clock())
        self.frames.append((self.clock(), obs if seen else None))

    def relative_pose(self):
        if not self.started:
            return None
        ready = [f for f in self.frames if f[0] + self.LATENCY_S <= self.clock()]
        if not ready or ready[-1][1] is None:
            return None
        at, obs = ready[-1]
        return obs if self.clock() - at <= 0.6 else None


PARKING = dict(name="parking", detector="observation", tag_id=7, tag_size_m=0.05,
               staging=False, approach="pose", settle="pose", tag_offset_m=OFFSET,
               acquire_creep_m=0.20, backoff_m=0.10, undock_distance_m=0.27,
               undock_turn_rad=math.pi / 2, max_retries=3)


def a_parking(pose, *, line_follow=False, **type_kwargs):
    clock = Clock()
    world = World(pose)
    camera = TagCamera(world, clock)
    db = DockDatabase.empty()
    db.add_type(DockType(**dict(PARKING, **type_kwargs)))
    db.add(DockInstance(id="parking", type="parking", x=SPOT[0], y=SPOT[1], yaw=SPOT[2]))
    events = []
    manager = DockingManager(
        database=db, safety=SimpleNamespace(estop=False), config=DockingConfig(),
        clock=clock, detector_factory=lambda dock, dock_type: camera,
        capability_provider=lambda: True,
        events=SimpleNamespace(publish=lambda t, **kw: events.append((t, kw.get("data")))),
        pose_provider=lambda: world.pose,
        line_follow_active_provider=lambda: line_follow)
    manager.executor = world
    return SimpleNamespace(manager=manager, world=world, camera=camera, clock=clock,
                           events=events)


def run(p, until, max_s=120.0):
    """Tick at 20 Hz with 5 Hz frames until `until(manager)` or max_s."""
    phases = []
    t0 = p.clock.now
    k = 0
    while p.clock.now - t0 < max_s:
        if k % 4 == 0:
            p.camera.capture()
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


def error(pose):
    return (math.dist(pose[:2], SPOT[:2]),
            abs(math.degrees(math.atan2(math.sin(pose[2] - SPOT[2]), math.cos(pose[2] - SPOT[2])))))


@pytest.mark.parametrize("dy", [-0.02, 0.0, 0.02])
@pytest.mark.parametrize("dyaw_deg", [-5.0, 0.0, 5.0])
def test_from_the_tour_end_it_parks_within_tolerance(dy, dyaw_deg):
    """The tour ends on west:f at the entry heading +y. Entry errors of
    +-20 mm and +-5 deg end parked well inside 20 mm / 5 deg."""
    p = a_parking((ENTRY_X, dy, math.pi / 2 + math.radians(dyaw_deg)))
    p.manager.dock()
    phases = run(p, done)
    assert p.manager.state is DockState.DOCKED, phases
    position, heading = error(p.world.pose)
    assert position <= 0.010 and heading <= 2.0, (p.world.pose, phases)
    assert p.world.goals == []                      # no Nav2 staging
    order = [ph for _, ph in phases if ph]
    for a, b in zip(["turning", "acquiring", "approaching", "aligning", "settling"],
                    ["acquiring", "approaching", "aligning", "settling", None]):
        assert a in order
    assert order.index("turning") < order.index("acquiring") < order.index("approaching") \
        < order.index("aligning") < order.index("settling")


def test_at_the_spot_a_dock_command_confirms_without_driving_away():
    p = a_parking(SPOT)
    p.manager.dock()
    run(p, done, max_s=20.0)
    assert p.manager.state is DockState.DOCKED
    assert math.dist(p.world.pose[:2], SPOT[:2]) < 0.004


def test_undocking_reverses_to_the_entry_and_turns_onto_the_lane():
    p = a_parking(SPOT)
    p.manager.dock()
    run(p, done, max_s=20.0)
    p.manager.undock()
    assert p.manager.state is DockState.UNDOCKING
    phases = run(p, done, max_s=60.0)
    assert p.manager.state is DockState.UNDOCKED, phases
    x, y, yaw = p.world.pose
    assert x == pytest.approx(ENTRY_X, abs=0.01)    # 0.27 m back, the wall is at -1.4025
    assert x - 0.075 > -1.4025 + 0.04
    assert abs(y) < 0.005
    assert yaw == pytest.approx(math.pi / 2, abs=math.radians(1.5))
    assert ("UNDOCKING", "turning") in phases


def test_a_tag_never_seen_creeps_only_so_far_then_fails():
    p = a_parking((ENTRY_X, 0.0, 0.0), max_retries=1)
    p.camera.capture = lambda: p.camera.frames.append((p.clock(), None))
    p.manager.dock()
    xs = []
    run(p, lambda m: xs.append(p.world.pose[0]) or done(m), max_s=200.0)
    assert p.manager.state is DockState.DOCK_FAILED
    # A retry backs off 0.10 m and creeps again; however often, never past
    # the spot on the map.
    assert max(xs) <= SPOT[0] - 0.04
    assert min(xs) - 0.075 > -1.4025                # the backoff never reaches the wall
    assert p.world.goals == []


def test_a_settle_out_of_tolerance_reseats_and_then_parks():
    p = a_parking((ENTRY_X, 0.0, math.pi / 2))
    p.manager.dock()
    biased = {"done": False}

    def until(manager):
        if manager.phase is DockPhase.SETTLING and not biased["done"]:
            p.camera.bias_y = 0.03                  # the settle frame reads 30 mm off
        if manager.phase is DockPhase.BACKOFF:
            biased["done"] = True
            p.camera.bias_y = 0.0
        return done(manager)

    run(p, until, max_s=200.0)
    assert biased["done"]
    assert any(t == "docking.reseat" for t, _ in p.events)
    assert p.manager.state is DockState.DOCKED
    assert error(p.world.pose)[0] <= 0.010


def test_line_follow_must_be_off_before_docking_drives():
    p = a_parking((ENTRY_X, 0.0, math.pi / 2), line_follow=True)
    with pytest.raises(DockError) as exc:
        p.manager.dock()
    assert exc.value.code == "LINE_FOLLOW_ACTIVE"
    assert p.manager.state is DockState.UNDOCKED


def test_a_parking_run_asks_for_the_fast_tick_an_original_dock_does_not():
    p = a_parking((ENTRY_X, 0.0, math.pi / 2))
    assert not p.manager.fast_tick
    p.manager.dock()
    assert p.manager.fast_tick
    p.manager.cancel()
    assert not p.manager.fast_tick
    db = DockDatabase.empty()
    db.add_type(DockType(name="rosy_v1", detector="simulated"))
    db.add(DockInstance(id="d", type="rosy_v1"))
    original = DockingManager(database=db, safety=SimpleNamespace(estop=False),
                              capability_provider=lambda: True)
    original.dock()
    assert not original.fast_tick


def test_the_clock_can_be_rebound_to_the_sim_clock():
    p = a_parking(SPOT)
    sim = [5.0]
    p.manager.bind_clock(lambda: sim[0])
    p.manager.dock()
    assert p.manager.phase is not None
    assert p.manager._phase_since == 5.0


def test_a_parking_type_needs_its_offset_and_a_pose_approach():
    with pytest.raises(ValueError):
        DockType(**dict(PARKING, tag_offset_m=None))
    with pytest.raises(ValueError):
        DockType(**dict(PARKING, approach="bearing"))    # pose settle needs a pose approach
    original = DockType(name="rosy_v1", detector="simulated")
    assert (original.staging, original.approach, original.settle,
            original.undock_turn_rad) == (True, "bearing", "agent", 0.0)
