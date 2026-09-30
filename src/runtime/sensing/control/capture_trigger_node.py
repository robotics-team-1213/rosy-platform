#!/usr/bin/env python3
"""capture_trigger_node — disagreement snapshots for the learning loop (D-373).

Subscribes perception/learned/shadow and capture/request (std_msgs/String, the
operator's note). When control.capture_trigger decides, it leaves a request
file (reason and values) under the recording root and calls the rosbag2
snapshot service (rosbag2_interfaces/srv/Snapshot on /<recorder>/snapshot);
record_session --snapshot turns the dump into one session folder. Every
trigger is logged with its reason. Evidence only: this node never publishes
cmd_vel and nothing in the control path reads it (D-2, D-209)."""

import json
import time
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from rosbag2_interfaces.srv import Snapshot
from std_msgs.msg import String

from . import executor_choice
from .capture_trigger import (DEFAULT_COOLDOWN_S, DEFAULT_DELTA_THRESHOLD, DEFAULT_FRAMES,
                              CaptureTrigger)
from .record_session import DEFAULT_SNAPSHOT_NODE
from .recording import DEFAULT_ROOT, write_snapshot_request


class CaptureTriggerNode(Node):
    def __init__(self):
        super().__init__('capture_trigger_node')
        self._policy = CaptureTrigger(
            delta_threshold=float(self.declare_parameter(
                'delta_threshold', DEFAULT_DELTA_THRESHOLD).value),
            frames=int(self.declare_parameter('frames', DEFAULT_FRAMES).value),
            cooldown_s=float(self.declare_parameter('cooldown_s', DEFAULT_COOLDOWN_S).value))
        self._root = str(self.declare_parameter('recording_root', DEFAULT_ROOT).value)
        service = str(self.declare_parameter(
            'snapshot_service', f'/{DEFAULT_SNAPSHOT_NODE}/snapshot').value)
        self._client = self.create_client(Snapshot, service)
        # Every shadow frame counts toward a streak, so keep a short queue.
        # Literal (== recording.SHADOW_TOPIC, tested) so the D-185 subscription scan resolves it.
        self.create_subscription(String, 'perception/learned/shadow', self._on_shadow, 10)
        self.create_subscription(String, 'capture/request', self._on_request, 10)
        self.get_logger().info(
            f'capture trigger ready: |delta|>={self._policy.delta_threshold} for '
            f'{self._policy.frames} frames, cooldown {self._policy.cooldown_s:.0f}s, '
            f'service {service}, root {self._root}')

    def _on_shadow(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except ValueError:
            return
        decision = self._policy.on_shadow(payload, time.monotonic())
        if decision is not None:
            self._snapshot(decision)

    def _on_request(self, msg: String) -> None:
        self._snapshot(self._policy.on_request(msg.data, time.monotonic()))

    def _snapshot(self, decision) -> None:
        values = json.dumps(decision.values, sort_keys=True)
        self.get_logger().info(f'capture trigger: {decision.reason} {values}')
        try:
            request = write_snapshot_request(self._root, decision.reason, decision.values,
                                             datetime.now(timezone.utc))
        except OSError as exc:
            request = None  # the dump still lands, as an "unrequested" session
            self.get_logger().error(f'snapshot reason not saved: {exc}')
        if not self._client.service_is_ready():
            self.get_logger().warn('snapshot recorder not running; trigger dropped')
            self._forget(request)
            return
        future = self._client.call_async(Snapshot.Request())
        future.add_done_callback(lambda f: self._done(f, decision.reason, request))

    def _done(self, future, reason, request) -> None:
        try:
            ok = bool(future.result().success)
        except Exception as exc:
            self.get_logger().warn(f'snapshot call failed ({reason}): {exc}')
            ok = False
        if ok:
            self.get_logger().info(f'snapshot taken: {reason}')
        else:
            self.get_logger().warn(f'snapshot refused: {reason}')
            self._forget(request)

    @staticmethod
    def _forget(request) -> None:
        if request is not None:
            try:
                request.unlink()
            except OSError:
                pass


def main():
    rclpy.init()
    node = CaptureTriggerNode()
    try:
        executor_choice.spin(node, rclpy)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
