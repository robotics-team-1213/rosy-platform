"""D-185 R2: consumers that only keep the newest value subscribe with KEEP_LAST depth 1.

In the loaded rig (2026-09-23) calibration drained a depth-10 FIFO of old decisions after
a stall and rejected each as stale; receipt-stamped topics (motion limits, hazards,
can_reverse) gave old content a fresh receipt time, so an old "no hazard" could look new.
Every handler listed here overwrites its state, so only the newest sample matters.

The scan covers the whole control package: every subscriber of a freshness topic must be
classified below, and a subscription whose topic cannot be resolved statically must be
named, so a new subscriber cannot slip past. DDS queueing itself cannot be exercised on
the host; its effect is judged by the interleaved rig A/B (D-185 rule 2).
"""
import ast

from test.subscription_scan import subscriptions

FRESHNESS_TOPICS = {'safety/decision', 'safety/motion_limits', 'safety/observation', 'safety/can_reverse',
                    'safety/blocked', 'safety/cliff', 'safety/tilt', 'safety/pickup'}
HAZARDS = ('safety/blocked', 'safety/cliff', 'safety/tilt', 'safety/pickup')

LATEST_ONLY = {
    ('startup_calibration_node.py', 'safety/decision'),
    ('startup_calibration_node.py', 'safety/motion_limits'),
    ('startup_calibration_node.py', 'safety/can_reverse'),
    *(('startup_calibration_node.py', topic) for topic in HAZARDS),
    ('wander/node.py', 'safety/observation'),
    ('wander/node.py', 'safety/motion_limits'),
    ('goal_escape.py', 'safety/motion_limits'),
    ('web_node.py', 'safety/decision'),
    ('web_node.py', 'safety/motion_limits'),
}
# Left at depth 10 on purpose: outside the approved R2 scope (follow-up candidates, D-185).
KEEP_DEPTH = {
    *(('wander/node.py', topic) for topic in HAZARDS),
    ('localization_node.py', 'safety/pickup'),
    *(('web_node.py', topic) for topic in (*HAZARDS, 'safety/can_reverse')),
}
# Command streams: several publishers share them and each sample is an event.
COMMANDS = {('wander/node.py', 'cmd_vel_raw'), ('web_node.py', 'cmd_vel_raw')}
# Topic names taken from parameters; none is a freshness topic. safety on_cmd is cmd_in.
UNRESOLVED = {
    ('calib_node.py', 'self.on_ir'), ('control_node.py', 'self.on_odom'),
    ('goal_node.py', 'self.on_map'), ('goal_node.py', 'self.on_odom'),
    ('obstacle_observer_node.py', 'self.on_scan'), ('wander/node.py', 'self.on_odom'),
    ('web_node.py', 'self.on_battery'),
    *(('safety/node.py', f'self.{name}') for name in
      ('on_scan', 'on_us', 'on_ir', 'on_cam_cliff', 'on_cam_block', 'on_imu', 'on_cmd')),
}


def is_int(argument, value=None):
    return (isinstance(argument, ast.Constant) and type(argument.value) is int and
            (value is None or argument.value == value))


def test_latest_only_consumers_subscribe_with_depth_one():
    seen = set()
    for relative, topic, qos, _, line in subscriptions():
        if (relative, topic) in LATEST_ONLY:
            seen.add((relative, topic))
            assert is_int(qos, 1), (relative, topic, line, qos and ast.unparse(qos))
    assert seen == LATEST_ONLY, LATEST_ONLY-seen


def test_every_freshness_subscriber_is_classified():
    for relative, topic, qos, _, line in subscriptions():
        if topic in FRESHNESS_TOPICS:
            assert (relative, topic) in LATEST_ONLY | KEEP_DEPTH, (relative, topic, line, 'unclassified')
        if (relative, topic) in KEEP_DEPTH:
            assert is_int(qos) and qos.value >= 10, (relative, topic, line)


def test_command_streams_keep_their_queue():
    commands = [(relative, topic, qos, line) for relative, topic, qos, callback, line in subscriptions()
                if (relative, topic) in COMMANDS or (relative, callback) == ('safety/node.py', 'self.on_cmd')]
    assert len(commands) == 3, commands
    for relative, topic, qos, line in commands:
        assert is_int(qos) and qos.value >= 10, (relative, topic, line)


def test_unresolved_topics_are_known():
    unresolved = {(relative, callback) for relative, topic, _, callback, _ in subscriptions() if topic is None}
    assert unresolved == UNRESOLVED, (unresolved-UNRESOLVED, UNRESOLVED-unresolved)
