#!/usr/bin/env bash
# Join the Fleet UDS grant/stop path to the locked vendor Gazebo ActionServer.
# Run only in the isolated development image with no network or device grants.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /opt/omx_ws/install/setup.bash
set -u

test -r /repo/middleware/apps/device/omx/adapter/test/test_omx_fleet_ros_actionserver.py || {
  echo "read-only /repo checkout is required" >&2
  exit 2
}
mount_options=$(findmnt -n -o OPTIONS --target /repo)
if ! grep -Eq '(^|,)ro(,|$)' <<<"$mount_options"; then
  echo "vendor simulation probe requires /repo to be mounted read-only" >&2
  exit 2
fi
for network_interface in /sys/class/net/*; do
  if [[ "${network_interface##*/}" != "lo" ]]; then
    echo "vendor simulation probe requires a network-none container" >&2
    exit 2
  fi
done
if [[ -d /dev/serial/by-id ]] \
  || compgen -G '/dev/ttyACM*' >/dev/null \
  || compgen -G '/dev/ttyUSB*' >/dev/null \
  || compgen -G '/dev/ttyS*' >/dev/null \
  || compgen -G '/dev/video*' >/dev/null; then
  echo "vendor simulation probe refuses serial or video device grants" >&2
  exit 2
fi

export PYTHONPATH="/repo/contracts/foundation:/repo/operations/fleet:/repo/operations/fleet/test:/repo/middleware/apps/device/omx/adapter:${PYTHONPATH:-}"
export PYTHONDONTWRITEBYTECODE=1
# This synchronous rclpy test owns its executor; launch_testing hooks are not
# used. Their autoload collection can import unrelated sibling HTTP tests.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
unset PYTEST_PLUGINS PYTEST_ADDOPTS
vendor_test="/repo/middleware/apps/device/omx/adapter/test/test_omx_fleet_ros_actionserver.py::test_fleet_mission_reaches_ros_goal_once_without_claiming_semantic_completion[generation-change]"
collection_log="/tmp/rosy-fleet-vendor-collection.log"
# Prove actual pytest collection before starting Gazebo, not just module import.
python3 -m pytest "$vendor_test" --collect-only -q -p no:cacheprovider \
  --basetemp "/tmp/rosy-fleet-vendor-collection-$$" | tee "$collection_log"
grep -Eq '^1 test collected' "$collection_log" || {
  echo "vendor probe requires exactly one collected test" >&2
  exit 2
}
export OMX_FLEET_VENDOR_SIM_ACTION=/arm_controller/follow_joint_trajectory
export OMX_FLEET_VENDOR_SIM_JOINT_STATES=/joint_states
export OMX_FLEET_VENDOR_SIM_STARTUP_TIMEOUT_S=180
export ROS_DOMAIN_ID="${OMX_PROBE_DOMAIN_ID:-76}"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export GZ_SIM_PHYSICS_ENGINE_PATH=/opt/ros/jazzy/opt/gz_physics_vendor/lib

ros2 launch open_manipulator_bringup omx_f_follower_ai_gazebo.launch.py \
  >/tmp/rosy-fleet-vendor-launch.log 2>&1 &
launch_pid=$!
cleanup() {
  kill "$launch_pid" 2>/dev/null || true
  wait "$launch_pid" 2>/dev/null || true
}
trap cleanup EXIT

if ! python3 -m pytest \
  "$vendor_test" -x -s -q -p no:cacheprovider \
  --basetemp "/tmp/rosy-fleet-vendor-pytest-$$"; then
  tail -n 80 /tmp/rosy-fleet-vendor-launch.log >&2
  exit 1
fi
