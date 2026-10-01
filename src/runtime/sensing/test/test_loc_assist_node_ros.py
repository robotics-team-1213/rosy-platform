"""D-395 P2-3 node-level checks in isolated ROS Jazzy (skipped on a host without rclpy)."""
import math

import pytest

rclpy = pytest.importorskip('rclpy')

from control.loc_assist_node import LocAssistNode  # noqa: E402
from control.sensing.loc_candidates import PoseCandidate  # noqa: E402

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
