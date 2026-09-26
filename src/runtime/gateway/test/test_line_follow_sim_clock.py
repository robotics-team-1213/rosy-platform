"""Line-follow staleness runs on the node clock under `use_sim_time`.

Gazebo on a loaded host ran at RTF 0.25-0.4, so a 5 Hz sim-time camera frame
arrived every 0.5-0.8 s of *wall* time. Stamped with `time.monotonic()`, every
observation went stale (0.3 s) between frames: CORE HOLDed stop-and-go and could
latch LOST. The bridge now picks one line clock at startup: the ROS clock when
`use_sim_time` is true, `time.monotonic` otherwise (Device unchanged).
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from core.bridge.traffic_gate import line_clock
from core_events.events.bus import EventBus
from core_features.line_follow import (
    LineFollowManager,
    LineFollowMode,
    LineObservation,
)

BRIDGE = Path(__file__).parent.parent / "core" / "bridge" / "ros_bridge.py"


class FakeSim:
    """Sim clock at a fixed real-time factor against a fake wall clock."""

    def __init__(self, rtf: float) -> None:
        self.rtf = rtf
        self.wall = 100.0
        self.sim = 10.0

    def advance_wall(self, seconds: float) -> None:
        self.wall += seconds
        self.sim += seconds * self.rtf

    def ros_now(self) -> float:
        return self.sim


def seen(stamp: float) -> LineObservation:
    return LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=stamp,
                           visible=True, error=0.0, confidence=1.0)


def run_frames(clock, sim: FakeSim, frames: int = 10):
    manager = LineFollowManager(EventBus("rosy_01"), clock=clock)
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    states = []
    for _ in range(frames):
        manager.observe(seen(sim.sim), received_at=clock(), source_now=sim.sim)
        # 5 Hz in sim time = 0.2 s sim = 0.8 s wall at RTF 0.25; tick just
        # before the next frame lands, the worst case for staleness.
        sim.advance_wall(0.75)
        manager.tick(clock())
        states.append(manager.status().state)
    return states


def test_use_sim_time_picks_the_ros_clock():
    sim = FakeSim(rtf=0.25)
    clock = line_clock(True, sim.ros_now)
    assert clock() == sim.sim
    sim.advance_wall(1.0)
    assert clock() == 10.25


def test_without_sim_time_the_line_clock_is_monotonic_itself():
    assert line_clock(False, lambda: 1.0e9) is time.monotonic


def test_sim_clock_keeps_frames_fresh_at_quarter_real_time():
    sim = FakeSim(rtf=0.25)
    states = run_frames(line_clock(True, sim.ros_now), sim)
    assert states == ["TRACKING"] * 10


def test_wall_clock_goes_stale_at_quarter_real_time():
    """The defect, kept as a witness: wall time HOLDs between sim frames."""
    sim = FakeSim(rtf=0.25)
    states = run_frames(lambda: sim.wall, sim)
    assert "TRACKING" not in states


def test_backwards_sim_jump_is_not_fresh():
    sim = FakeSim(rtf=1.0)
    clock = line_clock(True, sim.ros_now)
    manager = LineFollowManager(EventBus("rosy_01"), clock=clock)
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    manager.observe(seen(sim.sim), received_at=clock(), source_now=sim.sim)
    manager.tick(clock())
    assert manager.status().state == "TRACKING"
    sim.sim -= 0.5  # /clock reset or rewind
    decision = manager.tick(clock())
    assert manager.status().state == "HOLD"
    assert manager.status().reason == "observation_stale"
    assert decision.linear == 0.0 and decision.angular == 0.0


def test_bind_clock_moves_mode_change_onto_the_line_clock():
    sim = FakeSim(rtf=0.25)
    manager = LineFollowManager(EventBus("rosy_01"))
    manager.bind_clock(line_clock(True, sim.ros_now))
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    # Loss started at sim 10.0; 2 s sim later it is waiting, not LOST.
    sim.sim += 2.0
    manager.tick(sim.sim)
    assert manager.status().state == "WAITING"
    sim.sim += 1.5
    manager.tick(sim.sim)
    assert manager.status().state == "LOST"


def _function_source(name: str) -> str:
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(BRIDGE.read_text(encoding="utf-8"), node)
    raise AssertionError(f"{name} not found in ros_bridge.py")


def test_line_follow_path_stamps_through_the_line_clock():
    for name in ("_on_line_observation", "_on_road_observation"):
        body = _function_source(name)
        assert "time.monotonic()" not in body, name
        assert "self._line_clock()" in body, name
    tick = _function_source("_tick_line_follow")
    assert "now = self._line_clock()" in tick
    # The only wall read left is the CommandManager stamp: its own
    # select_output() nav timeout compares against time.monotonic().
    monotonic_lines = [line.strip() for line in tick.splitlines()
                       if "time.monotonic()" in line
                       and not line.strip().startswith("#")]
    assert len(monotonic_lines) == 1
    assert "command_now" in monotonic_lines[0]
    init = _function_source("__init__")
    assert "self._svc.line_follow.bind_clock(self._line_clock)" in init
