"""Where an external call lands after CORE (D-74). ROS-free.

Work commands (TaskKind) become internal ROS (and then drivers).
Queries, identity, tokens, and Host Agent stay in CORE.
"""

from __future__ import annotations

import enum

from core_common.domain.tasks import TaskKind


class CommandSink(str, enum.Enum):
    """Internal destination. Not a public ROS API."""

    ROS = "ros"
    CORE = "core"


# TaskKind is the only REST work surface. Each sinks through CORE into ROS
# (Twist / Nav2 action / dock). UART and dock HTTP are behind that ROS path,
# not a second public command bus.
TASK_SINKS: dict[TaskKind, CommandSink] = {
    TaskKind.MOVE: CommandSink.ROS,
    TaskKind.NAVIGATE: CommandSink.ROS,
    TaskKind.RETURN_HOME: CommandSink.ROS,
    TaskKind.FOLLOW: CommandSink.ROS,
    TaskKind.DOCK: CommandSink.ROS,
}

TASK_ROS_INTERFACE: dict[TaskKind, str] = {
    TaskKind.MOVE: "geometry_msgs/Twist cmd_vel",
    TaskKind.NAVIGATE: "nav2_msgs/action/NavigateToPose",
    TaskKind.RETURN_HOME: "nav2_msgs/action/NavigateToPose",
    TaskKind.FOLLOW: "nav2_msgs/action/NavigateToPose",
    TaskKind.DOCK: "rosy docking + cmd_vel",
}

# Prefixes that must not be translated into ROS commands.
CORE_LOCAL_PREFIXES: tuple[str, ...] = (
    "/api/v1/system",
    "/api/v1/host",
    "/api/v1/logs",
    "/api/v1/events",
    "/api/v1/diagnostics",
)

# REST prefixes that *are* work commands (must have a TaskKind sink).
WORK_PREFIXES: tuple[str, ...] = (
    "/api/v1/control",
    "/api/v1/teleop",
    "/api/v1/navigation",
    "/api/v1/swarm",
    "/api/v1/docking",
    "/api/v1/safety",
)


def sink_for(kind: TaskKind) -> CommandSink:
    return TASK_SINKS[kind]
