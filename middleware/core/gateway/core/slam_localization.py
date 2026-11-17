"""CORE localization status for the SLAM backend: LOCALIZED only while a fresh map-frame pose exists.

slam_toolbox publishes map->odom, so a fresh `map` pose (and a known map id) is the evidence that the robot is
located in its own SLAM map. Anything else is UNKNOWN on the odom frame, and autonomy stays off. A status from the
regular localization assist (AMCL) always wins."""
from __future__ import annotations

from core_common.protocol.localization import LocalizationStatus, LocState, PoseFrame

MAX_POSE_AGE_S = 3.0


def slam_localization_provider(state, raw_provider):
    """Wrap `raw_provider` (may be None): its answer first, else the SLAM TF evidence."""
    def provider():
        status = raw_provider() if raw_provider is not None else None
        if status is not None:
            return status
        _x, _y, _yaw, frame, age_s = state.pose_sample()
        if frame == "map" and 0.0 <= age_s <= MAX_POSE_AGE_S and state.map_id is not None:
            return LocalizationStatus(state=LocState.LOCALIZED, pose_frame=PoseFrame.MAP, reason="slam_tf")
        return LocalizationStatus(state=LocState.UNKNOWN, pose_frame=PoseFrame.ODOM, reason="slam_waiting_tf")
    return provider
