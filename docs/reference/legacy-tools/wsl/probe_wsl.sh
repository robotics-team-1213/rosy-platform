#!/usr/bin/env bash
# 일회성 WSL 환경 점검(무인 커밋 대상 아님)
echo "=pwd="; pwd
echo "=ros="; ls /opt/ros 2>/dev/null
echo "=gz="; command -v gz && gz sim --version 2>/dev/null | head -1
command -v gazebo >/dev/null && gazebo --version 2>/dev/null | head -1
echo "=install="; ls install 2>/dev/null | head -8
echo "=src pkgs="; ls src 2>/dev/null
echo "=pkg check="; source /opt/ros/jazzy/setup.bash 2>/dev/null; ros2 pkg list 2>/dev/null | grep -cE "^(ros_gz|gz_sim_vendor)"
echo "=rmw="; ros2 doctor 2>/dev/null | head -0; dpkg -l | grep -c cyclonedds
