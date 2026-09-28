#!/usr/bin/env bash
# 웍트리의 pilot/web 최신 소스를 /rosy 로 동기화(symlink-install 이라 JS 즉시 반영)
set -e
SRC="/mnt/f/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/pilot-teleop"
for rel in src/hmi/pilot src/hmi/web src/hmi/dashboard; do
  rm -rf "/rosy/$rel"
  tar -C "$SRC" -cf - "$rel" | tar -C "/rosy" -xf -
done
cd /rosy
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select pilot web dashboard 2>&1 | tail -3
echo "SYNC_OK"
