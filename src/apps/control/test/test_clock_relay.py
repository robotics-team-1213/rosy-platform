"""D-185 R6: the rig can relay Gazebo's /clock at a bounded rate instead of every physics step.

Gazebo publishes /clock on every 1 ms physics step: 1324 messages in 5 s of wall time at
about 0.3x real time (2026-09-24), and every rig node wakes for each one. ros_gz_bridge 1.0.22
has no rate option; gz-transport's throttled subscription (SubscribeOptions.msgs_per_sec) does.
RIG_CLOCK_HZ is opt-in; unset keeps the bridge's per-step /clock.
"""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from tools.gz.clock_relay import relay_rate, to_ros_clock

ROOT = Path(__file__).resolve().parents[1]


def test_relay_rate_accepts_positive_integers_only():
    assert relay_rate('100') == 100 and relay_rate(' 25 ') == 25
    for bad in ('0', '-5', '2.5', 'fast', ''):
        with pytest.raises(ValueError):
            relay_rate(bad)


def test_gazebo_sim_time_maps_to_ros_clock_exactly():
    class RosClock:
        def __init__(self):
            self.clock = NS(sec=None, nanosec=None)
    gz = NS(sim=NS(sec=3, nsec=250000000))
    ros = to_ros_clock(gz, RosClock)
    assert (ros.clock.sec, ros.clock.nanosec) == (3, 250000000)


def test_rig_script_swaps_the_bridge_clock_for_the_relay_only_when_asked():
    script = (ROOT/'tools/gz/run_track260905.sh').read_text()
    assert "'/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock'" in script  # default: bridged per step
    assert 'RIG_CLOCK_HZ' in script
    relay = next(line for line in script.splitlines() if 'clock_relay.py' in line)
    assert '8>&-' in relay and '9>&-' in relay and relay.rstrip().endswith('pids+=($!)')
