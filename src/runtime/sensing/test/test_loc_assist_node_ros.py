"""D-395 P2-3 node-level checks in isolated ROS Jazzy (skipped on a host without rclpy)."""
import json
import math

import pytest

rclpy = pytest.importorskip('rclpy')

from control.loc_assist_node import LocAssistNode  # noqa: E402
from control.sensing.loc_candidates import PoseCandidate  # noqa: E402
from std_msgs.msg import String  # noqa: E402

ODOM = (0., 0., 0.)


@pytest.fixture
def node():
    rclpy.init(args=['--ros-args', '-r', '__ns:=/rosy_loc_test'])
    made = LocAssistNode()
    yield made
    made.stopping.set()
    made.pool.shutdown(wait=False, cancel_futures=True)
    made.destroy_node()
    rclpy.shutdown()


def camera_topics(node):
    return [s.topic_name for s in node.subscriptions if s.topic_name.endswith('camera/front')]


def test_the_camera_subscription_exists_only_outside_localized(node):
    assert camera_topics(node) == ['/rosy_loc_test/camera/front']
    core = node.core
    core.search_started(0., ODOM)
    core.search_finished(0., ODOM, [PoseCandidate(-1.26, .49, -math.pi / 2, .97, 'slot:A')])
    request = core.machine.request_id
    core.on_decision(1., {'decision': {'request_id': request, 'source': 'candidate', 'candidate_index': 0,
                                       'cues': ['slot']}, 'received_s': 1.})
    t = 1.1
    while t < 4.7:
        core.on_fit(t, .95)
        t = round(t + .1, 6)
    assert core.machine.autonomy_allowed
    node.sync_camera()
    assert camera_topics(node) == []
    core.on_suspect(5., {'reason': 'fleet_monitor'})
    node.sync_camera()
    assert camera_topics(node) == ['/rosy_loc_test/camera/front']


def test_the_node_feeds_the_namespaced_odom_twist_to_the_settle_gate(node):
    from nav_msgs.msg import Odometry
    assert [s.topic_name for s in node.subscriptions if s.topic_name.endswith('/odom')] == \
        ['/rosy_loc_test/odom']
    turning = Odometry()
    turning.twist.twist.angular.z = .3
    node.on_odom(turning)
    now = node.now()
    assert not node.core.search_due(now + .6, ODOM)
    node.on_odom(Odometry())
    assert node.core.search_due(node.now() + .6, ODOM)


def test_a_stop_between_the_paint_load_and_the_search_skips_the_search():
    import threading
    from control.loc_assist_node import search_job
    stopping = threading.Event()
    stopping.set()
    # field None: reaching the search would raise.
    found, objects, mask, generation, elapsed, notes, paint_map = search_job(
        stopping, '/no/such/bundle', 7, None, None, [], [], [], .1, None, .9)
    assert (found, objects, mask, generation, paint_map) == ([], [], None, -1, None)
    assert len(notes) == 1 and 'no paint map' in notes[0]


# --- S1 finding 1: the 3 s check scored scans through a stale map->odom ----------
#: Gazebo S1 bench (2026-10-02, X:\DevTemp\rosy-d395-f1\base_b\probe_r1.txt): AMCL
#: stamps map->odom at scan stamp + transform_tolerance (1.0 s in nav2_params.yaml,
#: 0.3 s on the device). A lookup at the scan stamp therefore returns the correction
#: AMCL had ~1 s earlier, so for ~1 s after /initialpose the check scored the
#: pre-injection pose (fit 0.013-0.019) and failed at settle 0.5 s.
TOLERANCE_S, SCAN_S, BASE_S = 1., .1, 1000.


def transform(parent, child, stamp_s, pose):
    from geometry_msgs.msg import TransformStamped
    t = TransformStamped()
    t.header.frame_id, t.child_frame_id = parent, child
    t.header.stamp = rclpy.time.Time(seconds=stamp_s).to_msg()
    t.transform.translation.x, t.transform.translation.y = pose[0], pose[1]
    t.transform.rotation.z, t.transform.rotation.w = math.sin(pose[2] / 2), math.cos(pose[2] / 2)
    return t


def laser_scan(stamp_s, ranges, angles):
    from sensor_msgs.msg import LaserScan
    msg = LaserScan()
    msg.header.frame_id = 'laser'
    msg.header.stamp = rclpy.time.Time(seconds=stamp_s).to_msg()
    msg.angle_min, msg.angle_increment = float(angles[0]), float(angles[1] - angles[0])
    msg.angle_max = float(angles[-1])
    msg.range_min, msg.range_max = .02, 3.5
    msg.ranges = [float(r) if math.isfinite(r) else math.inf for r in ranges]
    return msg


def run_injection(node, truth, injected):
    """Robot still at `truth`; AMCL starts elsewhere and jumps to `injected` on the
    first scan after /initialpose, broadcasting map->odom stamped TOLERANCE_S ahead."""
    from loc_world import MOUNT, field, scan
    node.field = field()
    clock = [BASE_S]
    node.now = lambda: clock[0]
    ns = node.tf.frame_prefix
    node.tf.set_transform_static(transform(ns + 'base_link', 'laser', 0., (MOUNT.x, MOUNT.y, MOUNT.yaw)), 'test')
    ranges, angles = scan(truth, beams=640)
    odom_base = truth                       # odom = map origin; only map->odom carries AMCL's guess
    core = node.core
    core.search_started(BASE_S, ODOM)
    core.search_finished(BASE_S, ODOM, [PoseCandidate(*injected, .97, 'slot:B')])
    inject_k, amcl = 10, (-.4, .3, 1.)        # AMCL's unseeded guess: map->base far from truth
    for k in range(60):
        t = BASE_S + k * SCAN_S
        clock[0] = t
        if k == inject_k:
            node.on_decision(String(data=json.dumps({'decision': {
                'request_id': core.machine.request_id, 'source': 'candidate', 'candidate_index': 0,
                'cues': ['slot']}, 'received_s': t})))
        elif k > inject_k:                  # AMCL applies /initialpose on its next scan
            # map->odom = injected (base) composed with the inverse of odom->base
            c, s = math.cos(injected[2] - odom_base[2]), math.sin(injected[2] - odom_base[2])
            amcl = (injected[0] - (c * odom_base[0] - s * odom_base[1]),
                    injected[1] - (s * odom_base[0] + c * odom_base[1]), injected[2] - odom_base[2])
        node.tf.set_transform(transform(ns + 'odom', ns + 'base_link', t, odom_base), 'test')
        node.tf.set_transform(transform('map', ns + 'odom', t + TOLERANCE_S, amcl), 'test')
        node.on_scan(laser_scan(t, ranges, angles))
        if core.machine.check is None and k > inject_k:
            break
    return core.machine


def test_a_correct_injection_passes_although_amcl_stamps_its_correction_ahead(node):
    from control.sensing.loc_state import LocState
    truth = (.86, -.52, math.pi)
    machine = run_injection(node, truth, truth)
    assert machine.state is LocState.LOCALIZED, machine.reason


def test_a_wrong_injection_is_still_rejected(node):
    from control.sensing.loc_state import LocState
    truth = (.86, -.52, math.pi)
    machine = run_injection(node, truth, (.56, -.52, math.pi))    # 30 cm off
    assert machine.state is LocState.SUSPECT and machine.reason == 'inject_rejected'
    assert node.core.fit < .85
