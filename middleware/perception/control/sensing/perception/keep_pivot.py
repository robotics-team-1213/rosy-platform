"""Keep mode: a spin in place is not steer flipping (D-507 SIM round 2, root cause 1).

A D-495 junction turn spins the robot in place. The view sweeps and the keeper's
steer sign reverses, so its flipping hold latched; on a ring only one line is
seen afterwards, nothing released the hold, the keeper returned None and CORE
held with camera_line_not_visible until the turn ended unresolved. ROS-free.
"""

#: |odom wz| above half the D-495 turn floor (junction.TURN_MIN_W = 0.3 rad/s) ...
PIVOT_MIN_WZ = 0.15
#: ... while |odom vx| stays under CORE's still bound (junction_still_linear = 0.01 m/s):
#: keep steering always moves forward (1 - 0.65|e| of cruise), so a weave never counts.
PIVOT_MAX_LINEAR = 0.01


def release_flip_on_pivot(keeper, twist) -> bool:
    """Drop the keeper's steer history and flipping hold while fresh odometry
    `twist` (vx, wz) shows a spin in place; None (no fresh odom) changes nothing."""
    if twist is None or abs(twist[1]) <= PIVOT_MIN_WZ or abs(twist[0]) >= PIVOT_MAX_LINEAR:
        return False
    keeper._steer_history.clear()
    keeper._flip_hold = False
    return True
