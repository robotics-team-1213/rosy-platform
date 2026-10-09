# D-571 headless Gazebo bench image for any docker host (model PC, site PC).
#
#   git archive HEAD | docker build -t rosy-sim:jazzy -f deploy/sim/Dockerfile -
#
# The context is a git-archive snapshot (committed files only). The image holds ROS 2 Jazzy,
# ros_gz, gz_ros2_control and Nav2 (gz_sim's dependency closure, as in the model PC manifest),
# CORE's pip pins under /opt/rosy-pydeps, and a colcon build of gz_sim and the repo packages it
# needs under /opt/rosy/install. tools/remote/remote_sim.py rebuilds the shipped commit over a
# mount on every run, so an older image still runs new code; rebuild the image when the apt or
# pip lists change. No GUI, no EXPOSE: runs use `--network none` (loopback only).
FROM ros:jazzy-ros-base AS deps
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y -q --no-install-recommends \
      ros-jazzy-ros-gz ros-jazzy-gz-ros2-control ros-jazzy-navigation2 ros-jazzy-nav2-bringup \
      ros-jazzy-slam-toolbox ros-jazzy-rosbag2-storage-mcap ros-jazzy-realtime-tools ros-jazzy-xacro \
      ros-jazzy-robot-state-publisher ros-jazzy-joint-state-publisher \
      python3-opencv python3-numpy python3-pip python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*
COPY deploy/robot/pinky_pro/requirements-core.txt /tmp/requirements-core.txt
RUN pip3 install -q --no-cache-dir --target /opt/rosy-pydeps -r /tmp/requirements-core.txt httpx
ENV PYTHONPATH=/opt/rosy-pydeps \
    GZ_IP=127.0.0.1 \
    ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

FROM deps
WORKDIR /opt/rosy/src
COPY . .
RUN . /opt/ros/jazzy/setup.sh \
    && colcon build --packages-up-to gz_sim --build-base /opt/rosy/build \
         --install-base /opt/rosy/install --log-base /opt/rosy/log \
    && rm -rf /opt/rosy/build /opt/rosy/log
WORKDIR /
CMD ["bash", "-c", ". /opt/rosy/install/setup.bash && ros2 launch gz_sim gz_multi.launch.py robots:=1 headless:=true"]
