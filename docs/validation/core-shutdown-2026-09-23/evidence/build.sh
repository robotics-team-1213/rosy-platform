#!/bin/bash
# usage: build.sh <ws-name> <tar> <commit-label>
set -e
WS=/root/$1
rm -rf $WS; mkdir -p $WS
tar -xf "$2" -C $WS
echo "$3" > $WS/COMMIT
source /opt/ros/jazzy/setup.bash
cd $WS
colcon build --symlink-install --packages-up-to core > $WS/build.log 2>&1 || { tail -30 $WS/build.log; exit 1; }
tail -3 $WS/build.log
