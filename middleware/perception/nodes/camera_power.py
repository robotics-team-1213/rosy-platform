"""Subject: per-device power policy for camera_detect_node (D-440).

A mixin on CameraDetectNode, like CameraLockMixin: it reads and resets the node's
camera and policy state (_cam, _policy, _locked, _lock_attempts) and uses its
_start_cam/_stop_cam. The decision itself is the ROS-free DevicePowerGate.
CORE publishes the latched `power/devices` board only when the bench switch
(`power.device_policy.enabled`) or a device override is on; without a board the
gate always says "run" and the node behaves as before.
"""
from std_msgs.msg import Bool, String

from .camera_power_gate import DevicePowerGate, ready_report


class CameraPowerMixin:
    def _start_power_gate(self, latched_qos):
        self._power_gate = DevicePowerGate()
        self._camera_ready_reported = None
        self.device_ready_pub = self.create_publisher(String, 'power/device_ready', 10)
        self.create_subscription(String, 'power/devices', self._on_power_devices, latched_qos)

    def _on_power_devices(self, msg):
        change = self._power_gate.update(msg.data)
        if change is None:
            return
        _previous, level = change
        if level == 'off':
            self._stop_cam()
            self.get_logger().info('camera paused by power policy')
        else:
            # A restart re-runs the settle/lock and the warmup gate: frames from a
            # cold sensor are not floor evidence.
            self._locked = None
            self._lock_attempts = 0
            self._policy.reset()
            self._start_cam()
            self.get_logger().info('camera resumed by power policy')
        self._report_camera_ready(False)

    def _report_camera_ready(self, ready):
        if ready == self._camera_ready_reported:
            return
        self._camera_ready_reported = ready
        self.device_ready_pub.publish(String(data=ready_report('camera', ready)))
        self.device_ready_pub.publish(String(data=ready_report('perception', ready)))

    def _power_held(self, plan):
        """True when this tick must not capture: paused (off) or a reduced skip."""
        if plan == 'run':
            return False
        # Paused: blind, so blocked (fail-safe). Reduced skip: hold the last verdict.
        blocked = plan == 'off' or self._policy.blocked or not self._policy.ready
        self.cliff_pub.publish(Bool(data=self._policy.cliff))
        self.block_pub.publish(Bool(data=blocked))
        return True
