"""tools/sim/nav_events_probe.py: the D-953 Gazebo bench's verdicts, without ROS."""
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/sim/nav_events_probe.py'


def _module():
    sys.path.insert(0, str(SCRIPT.parent))  # the bench imports its siblings fleet_trips and route_drive
    spec = importlib.util.spec_from_file_location('nav_events_probe', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pause(**over):
    case = dict(goal_post=200, paused=dict(sim_advance_s=0.0), resumed=dict(clock_hz=900.0, cmd_vel_hz=47.4),
                final='ARRIVED')
    case.update(over)
    return case


def test_pause_passes_only_when_sim_time_stops_and_both_streams_return():
    m = _module()
    assert m.pause_ok(_pause())
    assert m.pause_ok(_pause(final='NAVIGATING'))
    assert not m.pause_ok(_pause(paused=dict(sim_advance_s=0.5)))      # pause did not stop the clock
    assert not m.pause_ok(_pause(resumed=dict(clock_hz=0.0, cmd_vel_hz=47.4)))
    assert not m.pause_ok(_pause(resumed=dict(clock_hz=900.0, cmd_vel_hz=0.0)))  # CORE timers did not resume
    assert not m.pause_ok(_pause(final='FAILED'))
    assert not m.pause_ok(_pause(goal_post=409))


def test_a_run_needs_every_expected_case_and_each_one_ok():
    m = _module()
    nav = {k: {'ok': True} for k in ('a_goal', 'b_cancel', 'c_pause')}
    assert m.run_pass(nav, slam=False)
    assert not m.run_pass({}, slam=False)
    assert not m.run_pass({'a_goal': {'ok': True}}, slam=False)        # a case that never ran is not a pass
    assert not m.run_pass(nav | {'c_pause': {'ok': False}}, slam=False)
    assert m.run_pass({'slam': {'ok': True}}, slam=True)
    assert not m.run_pass(nav, slam=True)
