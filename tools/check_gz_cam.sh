#!/usr/bin/env bash
source /opt/ros/jazzy/setup.bash 2>/dev/null
source /rosy/install/setup.bash 2>/dev/null
echo "==gz topic info=="
timeout 6 gz topic -i -t /rosy_01/camera/image_raw 2>&1 | head -8
echo "==cam bridge log=="
tail -5 /tmp/rosy_cam_bridge.log 2>/dev/null
echo "==world camera sensor?=="
timeout 5 gz sim -l 2>/dev/null | head -3 || true
