"""SLAM backend localization status: LOCALIZED only from a fresh map-frame pose; the AMCL assist's answer wins."""
from types import SimpleNamespace as NS

from core.slam_localization import MAX_POSE_AGE_S, slam_localization_provider
from core_common.protocol.localization import LocState, PoseFrame


def state(frame="map", age=0.5, map_id="slam:rosy_45"):
    return NS(pose_sample=lambda: (1.0, 2.0, 0.3, frame, age), map_id=map_id)


def test_fresh_map_frame_pose_is_localized():
    status = slam_localization_provider(state(), None)()
    assert (status.state, status.pose_frame, status.reason) == (LocState.LOCALIZED, PoseFrame.MAP, "slam_tf")


def test_anything_else_is_unknown_on_the_odom_frame():
    for kwargs in ({"frame": "odom"}, {"age": MAX_POSE_AGE_S + 0.1}, {"age": -0.1}, {"map_id": None}):
        status = slam_localization_provider(state(**kwargs), None)()
        assert (status.state, status.pose_frame) == (LocState.UNKNOWN, PoseFrame.ODOM), kwargs


def test_the_regular_assist_status_always_wins():
    sentinel = object()
    assert slam_localization_provider(state(frame="odom"), lambda: sentinel)() is sentinel
