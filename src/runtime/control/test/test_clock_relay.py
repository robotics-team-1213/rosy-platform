"""D-185 R6: the rig can relay Gazebo's /clock at a bounded rate instead of every physics step.

Gazebo publishes /clock on every 1 ms physics step: 1324 messages in 5 s of wall time at
about 0.3x real time (2026-09-24), and every rig node wakes for each one. ros_gz_bridge 1.0.22
has no rate option; gz-transport's throttled subscription (SubscribeOptions.msgs_per_sec) does.
RIG_CLOCK_HZ is opt-in; unset keeps the bridge's per-step /clock.
"""
from pathlib import Path
from types import SimpleNamespace as NS

import re
import subprocess
import sys

import pytest

from tools.gz.clock_relay import MIN_HZ_PER_RTF, relay_rate, to_ros_clock

ROOT = Path(__file__).resolve().parents[1]


def test_relay_rate_accepts_positive_integers_only():
    assert relay_rate('100') == 100 and relay_rate(' 25 ', realtime_factor=.3) == 25
    for bad in ('0', '-5', '2.5', 'fast', ''):
        with pytest.raises(ValueError):
            relay_rate(bad)


def test_relay_rate_keeps_the_sim_time_step_at_most_20_ms():
    # One relayed message covers about RTF/Hz of sim time. Strict freshness checks
    # (safety 0 <= age <= .2, lidar_guard >= -.05) need that step well under the 50 ms tick.
    assert MIN_HZ_PER_RTF == 50
    assert relay_rate('50') == 50 and relay_rate('15', realtime_factor=.3) == 15
    with pytest.raises(ValueError, match='at least 50'):
        relay_rate('49')
    with pytest.raises(ValueError, match='at least 100'):
        relay_rate('99', realtime_factor=2.)


def test_check_mode_validates_without_ros_so_the_script_fails_before_the_locks():
    run = lambda *args: subprocess.run([sys.executable, str(ROOT/'tools/gz/clock_relay.py'), '--check', *args],
                                       capture_output=True, text=True)
    assert run('100', '1.0').returncode == 0
    bad = run('fast', '1.0')
    assert bad.returncode == 2 and 'RIG_CLOCK_HZ' in bad.stderr


def test_gazebo_sim_time_maps_to_ros_clock_exactly():
    class RosClock:
        def __init__(self):
            self.clock = NS(sec=None, nanosec=None)
    gz = NS(sim=NS(sec=3, nsec=250000000))
    ros = to_ros_clock(gz, RosClock)
    assert (ros.clock.sec, ros.clock.nanosec) == (3, 250000000)


def test_rig_script_swaps_the_bridge_clock_for_the_relay_only_when_asked():
    script = (ROOT/'tools/gz/run_track260905.sh').read_text()
    # Default: the bridge keeps the legacy four topics in order; the per-step /clock is
    # appended only inside the unset branch, and the relay starts only in the other one.
    swap = re.search(r'\nbridged=\((.*?)\)\n.*?\nif \[\[ -z "\$\{RIG_CLOCK_HZ:-\}" \]\]; then\n(.*?)\nelse\n(.*?)\nfi\n',
                     script, re.S)
    assert swap, 'bridged array + RIG_CLOCK_HZ branch'
    assert re.findall(r"'([^']+)'", swap.group(1)) == [
        '/lidar/scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan',
        '/odometry_gt@nav_msgs/msg/Odometry[gz.msgs.Odometry',
        '/model/pinky/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist']
    assert swap.group(2).strip() == "bridged+=('/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock')"
    relay = swap.group(3)
    assert 'clock_relay.py' in relay and '/clock@' not in relay
    assert '8>&-' in relay and '9>&-' in relay and relay.rstrip().endswith('pids+=($!)')
    assert script.count('/clock@rosgraph_msgs') == 1
    # A bad rate fails before the partition and Gazebo locks are taken, and the manifest names the clock.
    assert script.index('clock_relay.py --check') < script.index('exec 9>')
    assert "'clock_hz':" in script
