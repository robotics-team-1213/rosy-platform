"""D-620: resolve a paired robot's next signal from Fleet's existing map and traffic cache."""
from fleet.guide.situation import lane_context


def signal_for(robot_id, *, traffic, poses, site_maps):
    ahead = traffic.signal_ahead(robot_id)
    if ahead is not None:
        return traffic.junction_signal(robot_id)
    pose, active = poses.arbitrated_pose(robot_id), site_maps.active()
    if (pose is None or active is None or pose.state not in ('LOCALIZED', 'DEGRADED')
            or pose.age_s is None or not 0 <= pose.age_s <= 2.0
            or pose.x is None or pose.y is None or pose.yaw is None):
        return dict(lamp='unknown', may_enter=False, reason='pose_unknown')
    lane = lane_context(active[2], pose.x, pose.y, pose.yaw, {})
    if (lane is None or abs(lane['lateral_m']) > lane['width_m']/2
            or abs(lane['heading_err_deg']) > 90 or lane['next_place']['distance_m'] > .6):
        return dict(lamp='unknown', may_enter=False, reason='approach_unknown')
    return traffic.junction_signal(robot_id, lane['arc_id'])
