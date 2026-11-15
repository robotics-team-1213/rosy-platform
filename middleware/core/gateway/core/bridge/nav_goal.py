"""core.bridge.nav_goal — NavGoalSpec -> Nav2 action goal (D-1009). Needs the ROS messages.

A spec with `via` poses (a route leg that has pass points) becomes NavigateThroughPoses, so Nav2 drives
through them without stopping; any other spec stays NavigateToPose. Split out of ros_bridge.py (size ratchet).
"""

import math

from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateThroughPoses, NavigateToPose


def pose_stamped(spec, stamp) -> PoseStamped:
    pose = PoseStamped()
    pose.header.frame_id = spec.frame
    pose.header.stamp = stamp
    pose.pose.position.x = spec.x
    pose.pose.position.y = spec.y
    pose.pose.orientation.z = math.sin(spec.yaw / 2.0)
    pose.pose.orientation.w = math.cos(spec.yaw / 2.0)
    return pose


def build(spec, stamp):
    """`(goal, through_poses)` for the spec."""
    if spec.via:
        goal = NavigateThroughPoses.Goal()
        goal.poses = [pose_stamped(p, stamp) for p in (*spec.via, spec)]
        return goal, True
    goal = NavigateToPose.Goal()
    goal.pose = pose_stamped(spec, stamp)
    return goal, False
