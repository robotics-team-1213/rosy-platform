"""Helper mixin and sensor/profile utilities for LineObserverNode."""

from __future__ import annotations

import math

import cv2
import yaml
from sensor_msgs.msg import CompressedImage, LaserScan
from std_msgs.msg import String, UInt16MultiArray

from .calibrated_values import calibrated
from .sensing.perception.drivable.drivable_keep import scan_summary
from .sensing.perception.lane_containment import geometry_error
from .sensing.perception.learned.paint_motion import mask_homography, warp_mask
from perception_runtime.perception.lane import (
    IRLineCalibration,
    detect_ir_line,
)
from perception_runtime.perception.lane_keep_lines import (
    HORIZON_MARGIN_PX,
    drop_small_components,
)


def load_nominal_camera_profile(node):
    """Load and calibrate the nominal camera profile and its geometry error bounds."""
    path = str(node.get_parameter('nominal_camera_profile_path').value)
    try:
        with open(path, encoding='utf-8') as handle:
            profile = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        node.get_logger().warning(
            f'nominal camera profile unreadable ({exc}); no NOMINAL ground',
            throttle_duration_sec=5.0,
        )
        profile = {}
    override = {
        key: float(node.get_parameter(f'camera_{key}_override').value)
        for key in ('pitch_rad', 'height_m')
    }
    override = {k: v for k, v in override.items() if math.isfinite(v)}
    profile, source, intervals = calibrated(
        'camera_profile',
        profile,
        static_source=path or 'no profile file',
        override=override,
        with_intervals=True,
    )
    bands = {
        k: float(node.get_parameter(f'camera_{k}_override').value)
        for k in ('pitch_uncertainty_rad', 'height_uncertainty_m')
    }
    ground_error = geometry_error(
        profile,
        intervals,
        overridden=override,
        override_bounds=(
            bands if all(map(math.isfinite, bands.values())) else None
        ),
    )
    node.get_logger().info(
        f'camera profile from {source}; geometry error {ground_error}'
    )
    return profile, ground_error


def build_ir_calibration(node) -> tuple[IRLineCalibration | None, str | None]:
    """Construct IRLineCalibration from node parameters when enabled."""
    if not bool(node.get_parameter('ir_calibration_enabled').value):
        return None, None
    calibration = IRLineCalibration(
        black=tuple(node.get_parameter('ir_black').value),
        white=tuple(node.get_parameter('ir_white').value),
        min_span=float(node.get_parameter('ir_min_span').value),
    )
    return calibration, calibration.revision


def encode_debug_overlay_msg(header, image) -> CompressedImage | None:
    """JPEG-encode a rendered debug overlay into a CompressedImage message."""
    ok, data = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        return None
    out = CompressedImage()
    out.header = header
    out.format = 'jpeg; overlay=lane-debug-v1'
    out.data = data.tobytes()
    return out


class LineObserverHelpersMixin:
    """Profile loading, paint motion homography, and auxiliary subscription callbacks."""

    def _nominal_profile(self):
        if self._nominal_profile_cache is None:
            self._nominal_profile_cache, self._ground_error = (
                load_nominal_camera_profile(self)
            )
        return self._nominal_profile_cache

    def _stamp(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_route_context(self, msg: String) -> None:
        self._route_context_input.receive(msg.data)

    def _on_ir(self, msg: UInt16MultiArray) -> None:
        observation = None
        if self._ir_calibration is not None:
            try:
                observation = detect_ir_line(
                    list(msg.data),
                    self._ir_calibration,
                    min_white=float(self.get_parameter('ir_min_white').value),
                    min_contrast=float(
                        self.get_parameter('ir_min_contrast').value
                    ),
                )
            except ValueError as exc:
                self.get_logger().warning(f'invalid IR line sample: {exc}')
        self._publish('IR_LINE', observation)

    def destroy_node(self):
        if self._paint_worker is not None:
            self._paint_worker.close()
        return super().destroy_node()

    def _paint_motion(self, ground):
        """motion(mask, src_stamp, dst_stamp) for the paint worker (D-570)."""
        cut = max(0, int(math.ceil(ground.horizon_row)) + HORIZON_MARGIN_PX)

        def motion(mask, src_stamp, dst_stamp):
            src = self._odom_history.pose_at(src_stamp)
            dst = self._odom_history.pose_at(dst_stamp)
            if src is None or dst is None:
                return 'no_odom'
            moved = mask_homography(
                ground,
                self._lane_keeper._x_offset,
                src,
                dst,
                mask.shape,
                cut,
                max_dxy_m=float(
                    self.get_parameter('learned_paint_max_dxy_m').value
                ),
                max_dyaw_rad=float(
                    self.get_parameter('learned_paint_max_dyaw_rad').value
                ),
            )
            if isinstance(moved, str):
                return moved
            homography, dxy, dyaw = moved
            return (
                drop_small_components(warp_mask(mask, homography, cut)),
                dxy,
                dyaw,
            )

        return motion

    def _on_scan(self, msg: LaserScan) -> None:
        ahead, side, front = scan_summary(
            msg.ranges,
            msg.angle_min,
            msg.angle_increment,
            msg.range_min,
            msg.range_max,
        )
        stamp = (
            float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
        )
        self._wall_ahead = (ahead, stamp, side, front)

    def _on_camera_controls(self, msg: String) -> None:
        summary = str(msg.data)
        self._camera_controls_stable = summary.startswith(
            'exposure='
        ) or summary.startswith('v4l2 exposure=')


__all__ = [
    "LineObserverHelpersMixin",
    "build_ir_calibration",
    "encode_debug_overlay_msg",
    "load_nominal_camera_profile",
]
