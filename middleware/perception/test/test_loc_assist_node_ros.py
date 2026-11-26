"""D-395 P2-3 node-level checks in isolated ROS Jazzy (skipped on a host without rclpy)."""
import json
import math
import time
from concurrent.futures import Future

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


def test_candidate_search_can_cross_the_budget_without_crashing(node):
    budget = node.p('search_budget_s')
    for elapsed in (budget + 0.1, budget - 0.1, budget + 0.1):
        node.search = Future()
        node.search.set_result(([], [], None, node.generation, elapsed, [], None))
        node.finish_search(node.now())


def test_camera_subscription_is_skipped_when_ground_is_disabled(node):
    assert camera_topics(node) == []


def test_the_camera_subscription_exists_only_outside_localized(node):
    from rclpy.parameter import Parameter
    node.set_parameters([
        Parameter('camera_ground_source', value='NOMINAL'),
        Parameter('allow_nominal_ground', value=True),
    ])
    node.sync_camera()
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
    assert not node.core.search_due(node.now(), ODOM)
    node.on_odom(Odometry())
    time.sleep(.6)
    node.on_odom(Odometry())                    # still for 0.6 s, and the twist is fresh
    assert node.core.search_due(node.now(), ODOM)


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


def test_unmoved_odometry_with_new_scan_geometry_retires_the_old_candidate(node):
    from control.sensing.loc_state import LocState
    from loc_world import MOUNT, field, scan

    node.field = field()
    clock = [BASE_S]
    node.now = lambda: clock[0]
    published = []
    node.publish = published.extend
    node.tf.set_transform_static(
        transform(node.tf.frame_prefix + 'base_link', 'laser', 0., (MOUNT.x, MOUNT.y, MOUNT.yaw)),
        'test',
    )
    node.core.on_twist(BASE_S - 1., 0., 0.)
    node.core.search_started(BASE_S, ODOM, scan_stamp=BASE_S)
    node.core.search_finished(BASE_S, ODOM, [PoseCandidate(-1.26, .49, -math.pi / 2, .97, 'slot:A')])
    ranges, angles = scan((.86, -.52, math.pi), beams=640)
    for t in (BASE_S + 6., BASE_S + 7.1, BASE_S + 8.2):
        clock[0] = t
        node.core.on_twist(t, 0., 0.)
        node.on_scan(laser_scan(t - .1, ranges, angles))
    assert node.core.machine.state is LocState.SUSPECT and node.core.machine.request_id is None
    assert node.core.search_due(clock[0], ODOM)
    assert all(kind != 'inject' for kind, _ in published)


def test_window_rejects_mismatched_delayed_or_replayed_delivery(node, monkeypatch):
    now_ns = time.monotonic_ns()
    node.grid_id = "occupancy:0123456789ab"
    monkeypatch.setattr(node.core, "search_window_ready", lambda now: True)
    payload = {
        "window": {"expected_map_grid_id": node.grid_id, "center": {"x": 0.2, "y": 0.0, "yaw": 0.0}},
        "issued_ns": now_ns,
    }

    def send(row):
        node.on_search_window(String(data=json.dumps(row)))

    send({**payload, "issued_ns": now_ns - 2_000_000_000})
    send({**payload, "window": {**payload["window"], "expected_map_grid_id": "occupancy:aaaaaaaaaaaa"}})
    assert node.window is None
    send(payload)
    assert node.window == ((0.2, 0.0, 0.0), now_ns)
    node.window = None
    send(payload)
    assert node.window is None


def test_window_worker_preserves_global_rivals(node, monkeypatch):
    from control import loc_assist_node

    first = PoseCandidate(.1, .2, .3, .95, "global")
    rival = PoseCandidate(.8, .9, -2.8, .94, "global")
    global_result = [first, rival]
    monkeypatch.setattr(loc_assist_node, "search", lambda *args, **kwargs: (global_result, [], None))
    monkeypatch.setattr(loc_assist_node, "window_candidate",
                        lambda *args: pytest.fail("a scoped hint tried to replace global rivals"))
    result = loc_assist_node.search_job(node.stopping, None, node.generation, None, None, (), (), (),
                                       .076, None, .90, ((), ()), window=(ODOM, time.monotonic_ns()))
    assert result[0] == global_result


def test_window_candidate_requires_a_new_fresh_scan_stamp(node, monkeypatch):
    from sensor_msgs.msg import LaserScan

    now = node.now()
    node.scan = LaserScan()
    node.scan.header.stamp = rclpy.time.Time(seconds=now - .1).to_msg()
    stamp = rclpy.time.Time.from_msg(node.scan.header.stamp).nanoseconds * 1e-9
    candidate = PoseCandidate(.2, .0, .0, .95, "window")
    monkeypatch.setattr(node.core, "search_window_ready", lambda now: True)
    monkeypatch.setattr(node, "scan_mount", lambda scan: pytest.fail("replayed scan tried to verify a window"))
    assert node.confirm_window_candidate(candidate, (stamp, time.monotonic_ns()), now, node.generation) == ([], [])


def test_injection_check_and_recheck_candidates_pass_localized_true(node, monkeypatch):
    from control.sensing.localization import MapAgreement
    from loc_world import MOUNT, field, scan

    calls = []
    orig_explain = MapAgreement.explain
    orig_robust = MapAgreement.robust_score
    monkeypatch.setattr(MapAgreement, "explain", lambda self, s, r, a, localized=False: (
        calls.append(("explain", localized)), orig_explain(self, s, r, a, localized=localized))[1])
    monkeypatch.setattr(MapAgreement, "robust_score", lambda self, s, r, a, localized=False: (
        calls.append(("robust", localized)), orig_robust(self, s, r, a, localized=localized))[1])

    truth = (.86, -.52, math.pi)
    ns = node.tf.frame_prefix
    node.tf.set_transform_static(transform(ns + 'base_link', 'laser', 0., (MOUNT.x, MOUNT.y, MOUNT.yaw)), 'test')
    node.field = field()
    ranges, angles = scan(truth, beams=640)
    core = node.core
    core.search_started(BASE_S, ODOM)
    core.search_finished(BASE_S, ODOM, [PoseCandidate(*truth, .97, 'slot:B')])
    node.recheck_candidates(BASE_S + .5, BASE_S, laser_scan(BASE_S, ranges, angles))
    assert ("robust", True) in calls

    calls.clear()
    machine = run_injection(node, truth, truth)
    assert machine.state.name == "LOCALIZED"
    assert ("explain", True) in calls
