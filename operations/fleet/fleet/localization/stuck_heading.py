"""D-607 pure heading evidence; manoeuvre geometry is checked separately before REALIGN."""

import math


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def reassess(pose, view, *, now, map_id, map_version):
    """Compare the allowed lane direction with the exact trusted pose used by the monitor."""
    if (pose is None or pose.state != "LOCALIZED" or not map_id or pose.map_id != map_id
            or not _finite(pose.age_s) or not 0 <= pose.age_s <= 2.0
            or not _finite(pose.anchor_age_s) or not 0 <= pose.anchor_age_s <= 1.5
            or not _finite(pose.yaw) or not _finite(pose.odom_stamp)):
        return {"status": "pose_untrusted"}
    view = view or {}
    back = view.get("return") or {}
    if (map_version is None or view.get("map_version") != map_version
            or view.get("pose_state") != "LOCALIZED" or view.get("pose_source") != "map_pose"
            or view.get("heading_source") != "pose" or not _finite(view.get("at"))
            or not 0 <= now - view["at"] <= 2.0
            or back.get("pose_stamp") != pose.odom_stamp
            or not _finite(back.get("lane_heading_deg"))):
        return {"status": "lane_sample_untrusted"}
    turn = (back["lane_heading_deg"] - math.degrees(pose.yaw) + 180.0) % 360.0 - 180.0
    return {"status": "heading_compared", "turn_deg": round(turn, 2),
            "pose_stamp": pose.odom_stamp, "edge_id": back.get("edge_id"),
            "map_version": map_version, "turn_spot": back.get("turn_spot") is True}
