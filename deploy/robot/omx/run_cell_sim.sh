#!/usr/bin/env bash
# Rosy Cell C3: locked OMX-F Gazebo follower in the omx_cell_workcell world, with NO command
# owner. The selected owner runs separately in the same simulation graph (D-403 §8).
# Do not start pilot_sim.server beside another owner. Native hosts use an explicit overlay.
set -eo pipefail
if [[ -e "$HOME/rosy-jobs/site" ]]; then
  echo "OMX simulation refuses a site host (D-571)" >&2
  exit 2
fi
source "${OMX_CELL_ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
source "${OMX_CELL_OVERLAY:-/opt/omx_ws/install}/setup.bash"
set -u
# Path without ".sdf" (the vendor launch appends it). Override only for a recorded variant.
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
world="${OMX_CELL_WORLD:-$repo/integrations/simulation/gazebo/worlds/omx_cell_workcell}"
test -r "$world.sdf"
export ROS_DOMAIN_ID="${OMX_CELL_DOMAIN_ID:-${ROS_DOMAIN_ID:-77}}"
unset ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export GZ_SIM_PHYSICS_ENGINE_PATH=/opt/ros/jazzy/opt/gz_physics_vendor/lib
log_dir="${OMX_CELL_LOG_DIR:-/tmp}"
mkdir -p "$log_dir"
ros2 launch open_manipulator_bringup omx_f_follower_ai_gazebo.launch.py \
  world:="$world" >"$log_dir/rosy-cell-gazebo.log" 2>&1 &
launch_pid=$!
trap 'kill "$launch_pid" 2>/dev/null || true; wait "$launch_pid" 2>/dev/null || true' EXIT
wait "$launch_pid"
