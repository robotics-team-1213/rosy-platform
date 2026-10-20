"""An external, hardware-free vendor peer for the native owner regression."""
from contextlib import contextmanager
import multiprocessing
import threading
import time
from uuid import uuid4

import rclpy
from control_msgs.action import FollowJointTrajectory
from rclpy.action import ActionServer, CancelResponse
from rclpy.executors import MultiThreadedExecutor, SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import JointState


def _serve(action_name, state_topic, ready, stop, publications, scenario, received, cancelled):
    rclpy.init()
    node = Node("omx_external_vendor")
    publisher = node.create_publisher(JointState, state_topic, 10)

    def publish_states():
        while not stop.is_set():
            message = JointState()
            message.name, message.position = ["joint1"], [0.0]
            message.header.stamp = node.get_clock().now().to_msg()
            publisher.publish(message)
            now = time.monotonic()
            with publications.get_lock():
                count, gap, previous = publications[:]
                publications[:] = [count + 1, max(gap, now - previous) if count else 0, now]
            stop.wait(0.03 if scenario == "timeout" else 0.01)

    def execute(goal_handle):
        received.set()
        if scenario == "timeout":
            time.sleep(1.2)
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                cancelled.set()
            else:
                goal_handle.succeed()
            result = FollowJointTrajectory.Result()
            result.error_code = FollowJointTrajectory.Result.SUCCESSFUL
            return result
        for _ in range(40):
            feedback = FollowJointTrajectory.Feedback()
            feedback.joint_names = ["joint1"]
            goal_handle.publish_feedback(feedback)
            time.sleep(0.02)
        goal_handle.succeed()
        result = FollowJointTrajectory.Result()
        result.error_code = FollowJointTrajectory.Result.SUCCESSFUL
        return result

    server = ActionServer(node, FollowJointTrajectory, action_name, execute_callback=execute,
                          cancel_callback=lambda _goal: CancelResponse.ACCEPT)
    executor = (MultiThreadedExecutor(num_threads=2) if scenario == "timeout"
                else SingleThreadedExecutor())
    executor.add_node(node)
    source = threading.Thread(target=publish_states, daemon=True)
    source.start()
    ready.set()
    deadline = time.monotonic() + 30
    parent = multiprocessing.parent_process()
    try:
        while not stop.is_set() and parent.is_alive() and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.02)
            # Let the synthetic server worker and publisher run between readiness checks.
            time.sleep(0)
    finally:
        stop.set()
        source.join(timeout=2)
        executor.shutdown()
        server.destroy()
        node.destroy_node()
        rclpy.try_shutdown()


@contextmanager
def _external_vendor(scenario):
    # Forking a live DDS context is unsafe. Spawn a fresh interpreter instead.
    context = multiprocessing.get_context("spawn")
    ready, stop = context.Event(), context.Event()
    received, cancelled = context.Event(), context.Event()
    publications = context.Array("d", [0, 0, 0])
    prefix = "/test/omx/flood_" + uuid4().hex
    action_name, state_topic = prefix + "/trajectory", prefix + "/joint_states"
    peer = context.Process(target=_serve,
                           args=(action_name, state_topic, ready, stop, publications,
                                 scenario, received, cancelled),
                           daemon=True)
    peer.start()
    try:
        assert ready.wait(10), "external vendor failed to initialize"
        assert peer.is_alive(), f"external vendor exited: {peer.exitcode}"
        yield action_name, state_topic, publications, received, cancelled
    finally:
        stop.set()
        peer.join(timeout=5)
        if peer.is_alive():
            peer.terminate()
            peer.join(timeout=3)
        assert peer.exitcode == 0, f"external vendor did not shut down cleanly: {peer.exitcode}"


@contextmanager
def external_feedback_vendor():
    with _external_vendor("feedback") as peer:
        yield peer[:3]


@contextmanager
def external_timeout_vendor():
    with _external_vendor("timeout") as peer:
        yield peer
