"""ROS-free bridge seam for atomic line and traffic-policy application."""

import time
from typing import Callable, Optional

from core_features.command.manager import Twist


def line_clock(use_sim_time: bool,
               ros_now: Callable[[], float]) -> Callable[[], float]:
    """The one clock the line/road evidence path stamps and ticks with.

    Under `use_sim_time` camera frames arrive at sim-time rate, so staleness is
    judged in sim seconds; a slow Gazebo (RTF < 1) must not age evidence by wall
    time. Otherwise it is `time.monotonic` itself, so the Device is unchanged.
    """
    return ros_now if use_sim_time else time.monotonic


def apply_line_candidate(line_follow, traffic_policy, command,
                         line_decision, now: float,
                         command_now: Optional[float] = None) -> bool:
    """Apply only when both line and road evidence revisions remain current.

    `now` is the line clock; `command_now` stamps the CommandManager, whose
    nav timeout runs on `time.monotonic` (defaults to `now`).
    """
    stamp = now if command_now is None else command_now
    result = {"applied": False}

    def apply_line(current) -> None:
        traffic_decision = traffic_policy.gate(
            current.linear, current.angular, now)

        def apply_traffic(gated) -> None:
            command.set_nav_twist(
                Twist(linear=gated.linear, angular=gated.angular),
                now=stamp,
            )
            result["applied"] = True

        traffic_policy.apply_if_current(traffic_decision, apply_traffic)

    line_follow.apply_if_current(line_decision, apply_line)
    return result["applied"]
