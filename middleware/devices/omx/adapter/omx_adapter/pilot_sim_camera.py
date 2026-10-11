"""SIM-only bootstrap of a camera fingerprint tied to the pinned SDF world."""

from __future__ import annotations

import threading

from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, JointState

from .camera_contract import CameraFrameGate, CameraStreamConfig
from .ros_camera_runtime import RosCameraStreamRuntime


class PilotSimCamera:
    def __init__(self, node, capture, world_sha256: str) -> None:
        self.node = node
        self.capture = capture
        self.world_sha256 = world_sha256
        self.error = None
        self._bootstrap = node.create_subscription(
            CameraInfo, "/workcell_camera/camera_info", self._on_info, qos_profile_sensor_data)
        self._joint_sub = node.create_subscription(
            JointState, "/joint_states", capture.observe_joint_state, qos_profile_sensor_data)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, name="sim-demonstration-writer", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while not self._stop.wait(0.02):
            self._tick()

    def _on_info(self, info) -> None:
        if self.capture.camera is not None:
            return
        if (info.width, info.height) != (320, 240) or info.header.frame_id != "workcell_camera_optical":
            self.error = "simulation camera dimensions or frame identity differ from the selected SDF"
            return
        if info.k[0] <= 0 or info.k[4] <= 0:
            self.error = "simulation camera intrinsics unavailable"
            return
        config = CameraStreamConfig(
            camera_identity=f"gazebo:omx_pilot_workcell:front:{self.world_sha256}",
            optical_frame_id="workcell_camera_optical", calibration_revision=f"sim-sdf:{self.world_sha256}",
            camera_info_sha256=CameraFrameGate.camera_info_fingerprint(info),
            max_frame_age_s=2.0, transform_revision=f"sim-sdf:{self.world_sha256}",
        )
        self.capture.camera = RosCameraStreamRuntime(
            self.node, config, image_topic="/workcell_camera/image",
            camera_info_topic="/workcell_camera/camera_info", pending_pairs=8,
        )
        self.error = None

    def _tick(self) -> None:
        try:
            self.capture.tick()
        except Exception as exc:
            self.error = f"capture failed: {type(exc).__name__}"
            self.capture.request_interrupt("capture_io_or_source_error")
            try:
                self.capture.interrupt("capture_io_or_source_error")
            except Exception:
                pass  # Retry closure; a disk failure must not kill the worker.

    def destroy(self) -> None:
        self._stop.set()
        self._worker.join(timeout=5)
        self.capture.interrupt("server_shutdown")
        self.node.destroy_subscription(self._bootstrap)
        self.node.destroy_subscription(self._joint_sub)
        if self.capture.camera is not None:
            self.capture.camera.destroy()
