#!/usr/bin/env bash
set -eo pipefail
source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"
source /opt/omx_ws/install/setup.bash
exec "$@"
