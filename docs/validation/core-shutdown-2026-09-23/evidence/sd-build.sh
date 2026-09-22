set -e
D=/mnt/x/DevTemp/claude/f--Dev-Control-Robot-ROS-Rosy/f5d7f4f5-10d1-4f53-ad01-e313c901b10c/scratchpad/shutdown
W=/opt/rosy_sdtest/current
rm -rf /opt/rosy_sdtest; mkdir -p $W
tar -xf $D/after-src.tar -C $W
echo "$1" > $W/COMMIT
source /opt/ros/jazzy/setup.bash
cd $W
colcon build --base-paths src --merge-install --install-base install --packages-up-to core > $W/build.log 2>&1 || { tail -20 $W/build.log; exit 1; }
tail -2 $W/build.log; ls -l $W/install/lib/core/core; systemctl is-system-running || true
