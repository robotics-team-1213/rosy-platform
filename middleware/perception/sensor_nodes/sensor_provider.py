"""Control-side sensor provider for CORE's optional sensor adapter (D-126 S1).

This module is the control slice's implementation of the provider port that
``core.bridge.control_sensor_adapter`` consumes.  CORE resolves it through the
``rosy.sensor_provider`` entry point (see ``setup.py``) and never imports
``control`` statically; host tests inject fakes or import this module directly.

Top-level imports stay ROS-free (pure policy + calibration file logic) so the
provider surface is host-testable.  The ROS worker import stays inside
:func:`make_node`, which only runs on a ROS host.
"""

from types import SimpleNamespace
from typing import Any
from collections.abc import Mapping

from .calibration_snapshot import load_calibration_snapshot
from .control.command_gate import CommandPolicy


def make_node(*, parameter_overrides: Mapping[str, Any], sensor_only: bool,
              namespace: str | None = None):
    """Create the absorbed ROS worker only after the profile opts in."""
    from rclpy.parameter import Parameter

    from .safety.node import SafetyNode

    overrides = [Parameter(name, value=value)
                 for name, value in parameter_overrides.items()]
    kwargs: dict[str, Any] = {"parameter_overrides": overrides, "sensor_only": sensor_only}
    if namespace is not None:
        kwargs["namespace"] = namespace
    return SafetyNode(**kwargs)


def make_policy(revision: str):
    """Create the in-process handoff policy CORE binds to its safety manager."""
    return CommandPolicy(revision)


def load_snapshot(path: str, context: Mapping[str, Any], active_generation: str,
                  data_root: str):
    """Load a context-bound, generation-bound calibration snapshot file."""
    return load_calibration_snapshot(path, context, active_generation, data_root)


def make_dock_detector(*, tag_id: int, tag_size_m: float, frame_source,
                       camera_matrix, dist_coeffs, revision: str = "dock-tag-v1",
                       clock=None):
    """Build an ArUco dock detector (DNC-007). The cv2 import stays inside
    this factory so the provider surface imports light on hosts without
    OpenCV — a missing cv2 fails at detector build time, not at import."""
    from .sensing.dock_detector import ArucoDockDetector

    kwargs = dict(frame_source=frame_source, tag_id=tag_id, tag_size_m=tag_size_m,
                  camera_matrix=camera_matrix, dist_coeffs=dist_coeffs,
                  revision=revision)
    if clock is not None:
        kwargs["clock"] = clock
    return ArucoDockDetector(**kwargs)


PROVIDER = SimpleNamespace(
    make_node=make_node,
    make_policy=make_policy,
    load_snapshot=load_snapshot,
    make_dock_detector=make_dock_detector,
)
