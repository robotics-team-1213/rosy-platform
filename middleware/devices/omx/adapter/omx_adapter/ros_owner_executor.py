"""Yield owner worker turns on Jazzy; rclpy 7.1.12 had no explicit handoff.
Pool/groups/cadence/shutdown stay inherited. Native tests cover the protected
spin hook; recheck it when changing the supported ROS distribution.
"""
import time

from rclpy.executors import MultiThreadedExecutor


class OwnerMultiThreadedExecutor(MultiThreadedExecutor):
    def __init__(self, *args, **kwargs):
        if not callable(getattr(MultiThreadedExecutor, "_spin_once_impl", None)):
            raise RuntimeError("OMX owner requires the ROS 2 Jazzy executor spin hook")
        super().__init__(*args, **kwargs)

    def _spin_once_impl(self, *args, **kwargs):
        result = super()._spin_once_impl(*args, **kwargs)
        time.sleep(0)
        return result
