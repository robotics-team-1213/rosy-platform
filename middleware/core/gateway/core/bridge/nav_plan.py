"""Request a Nav2 path without starting a controller action."""

import math
import threading
import time


class PathPlanningError(RuntimeError):
    pass


def _await_result(future, deadline):
    done = threading.Event()
    future.add_done_callback(lambda _: done.set())
    remaining = deadline - time.monotonic()
    if remaining <= 0.0 or not done.wait(remaining):
        raise PathPlanningError("Nav2 planner timed out")
    try:
        return future.result()
    except Exception as exc:
        raise PathPlanningError("Nav2 planner transport failed") from exc


def compute_path(client, goal, *, timeout_s):
    """Wait for one planner result across goal acceptance and path computation."""
    if not client.wait_for_server(timeout_sec=0.0):
        raise PathPlanningError("Nav2 planner unavailable")
    deadline = time.monotonic() + timeout_s
    handle = _await_result(client.send_goal_async(goal), deadline)
    if handle is None or not handle.accepted:
        raise PathPlanningError("Nav2 planner rejected the request")
    reply = _await_result(handle.get_result_async(), deadline)
    # rclpy action wrapper uses action_msgs/GoalStatus.STATUS_SUCCEEDED (4).
    if reply is None or reply.status != 4 or reply.result.error_code != 0:
        raise PathPlanningError("Nav2 failed to compute a path")
    path = reply.result.path
    frame = goal.goal.header.frame_id
    if not path.poses or path.header.frame_id != frame:
        raise PathPlanningError("Nav2 path missing or in a different frame")
    for stamped in path.poses:
        position, orientation = stamped.pose.position, stamped.pose.orientation
        if stamped.header.frame_id not in ("", frame) or not all(math.isfinite(value) for value in (
                position.x, position.y, position.z, orientation.x, orientation.y, orientation.z, orientation.w)):
            raise PathPlanningError("Nav2 returned an invalid path pose")
    return path
