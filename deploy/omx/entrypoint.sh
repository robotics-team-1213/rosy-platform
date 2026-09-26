#!/usr/bin/env bash
set -eo pipefail
unset ROS_LOCALHOST_ONLY
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
source /opt/omx_ws/install/setup.bash
exec "$@"
