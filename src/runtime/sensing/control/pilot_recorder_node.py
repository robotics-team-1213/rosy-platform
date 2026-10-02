#!/usr/bin/env python3
"""D-411 A: Pilot recording, owned by the camera unit. CORE only asks (SetBool).

Thin wrapper over control.pilot_recording.PilotRecorder. Evidence only: publishes no
command topic. The latched status feeds CORE; the latched active flag turns the camera's
JPEG copy on only while a session runs.
"""
import json
import socket

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String
from std_srvs.srv import SetBool

from core_common.protocol.recording import (
    ACTIVE_TOPIC, FETCHED_TOPIC, PILOT_RECORDING_ROOT, SET_ACTIVE_SERVICE, STATUS_TOPIC)
from . import executor_choice
from .pilot_recording import DEFAULT_QUOTA_BYTES, DEFAULT_RESERVE_BYTES, PilotRecorder

_LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL)
_GIB = 1024 ** 3


class PilotRecorderNode(Node):
    def __init__(self):
        super().__init__('pilot_recorder_node')
        self.declare_parameter('recording_root', PILOT_RECORDING_ROOT)
        self.declare_parameter('quota_gib', DEFAULT_QUOTA_BYTES / _GIB)
        self.declare_parameter('reserve_gib', DEFAULT_RESERVE_BYTES / _GIB)
        namespace = self.get_namespace().strip('/')
        quota = int(float(self.get_parameter('quota_gib').value) * _GIB)
        reserve = int(float(self.get_parameter('reserve_gib').value) * _GIB)
        recorder = dict(device=namespace or socket.gethostname(), namespace=namespace,
                        quota_bytes=quota, log=self.get_logger().warn)
        try:
            self._recorder = PilotRecorder(self.get_parameter('recording_root').value,
                                           reserve_bytes=reserve, **recorder)
        except ValueError as exc:
            # Never smaller than a quarter of the quota, so a small quota still fits.
            fallback = min(DEFAULT_RESERVE_BYTES, quota // 4)
            self.get_logger().error(f'reserve_gib does not fit quota_gib ({exc}); '
                                    f'using a reserve of {fallback} bytes')
            self._recorder = PilotRecorder(self.get_parameter('recording_root').value,
                                           reserve_bytes=fallback, **recorder)
        try:
            # Stops a writer left by a hard-killed predecessor and writes missing manifests.
            self._recorder.recover()
        except OSError as exc:
            self.get_logger().error(f'pilot recording recover failed: {exc}')
        self._status_pub = self.create_publisher(String, STATUS_TOPIC, _LATCHED)
        self._active_pub = self.create_publisher(Bool, ACTIVE_TOPIC, _LATCHED)
        self.create_service(SetBool, SET_ACTIVE_SERVICE, self._on_set_active)
        self.create_subscription(String, FETCHED_TOPIC, self._on_fetched, 5)
        self.create_timer(1.0, self._tick)
        self._publish()

    def _on_set_active(self, request, response):
        ok, detail = self._recorder.start() if request.data else self._recorder.stop('requested')
        response.success = ok
        response.message = json.dumps({'code': '' if ok else detail, 'status': self._recorder.status()})
        self._publish()
        return response

    def _on_fetched(self, msg):
        try:
            recording_id = str(json.loads(msg.data).get('id', ''))
        except (ValueError, AttributeError):
            self.get_logger().warn('fetched notice ignored: not JSON')
            return
        if not self._recorder.mark_fetched(recording_id):
            self.get_logger().warn(f'fetched notice for unknown recording {recording_id!r}')

    def _tick(self):
        reason = self._recorder.tick()
        if reason:
            self.get_logger().info(f'pilot recording finished: {reason}')
        self._publish()

    def _publish(self):
        status = self._recorder.status()
        self._status_pub.publish(String(data=json.dumps(status)))
        self._active_pub.publish(Bool(data=status['state'] in ('recording', 'stopping')))

    def destroy_node(self):
        self._recorder.shutdown()
        super().destroy_node()


def main():
    rclpy.init()
    node = PilotRecorderNode()
    try:
        executor_choice.spin(node, rclpy)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
