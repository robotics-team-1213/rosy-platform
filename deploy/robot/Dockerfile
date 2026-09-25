# syntax=docker/dockerfile:1.7
ARG ROS_IMAGE=ros:jazzy-ros-base

FROM ${ROS_IMAGE} AS runtime-common

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ROS_LOG_DIR=/tmp/ros-logs

# Hub linux/arm64 ros:jazzy-ros-base from 2026-09-16 may ship 0-byte
# CPython and ROS Python sources. The helper no-ops when no 0-byte .py
# files exist (healthy amd64 / native Pi). On a hollow image it
# reinstalls stdlib, then python3-minimal, then owners of remaining
# 0-byte files including /opt/ros.
COPY deploy/robot/restore-hollow-python.sh /tmp/restore-hollow-python.sh
RUN apt-get -o Acquire::Retries=5 update \
    && bash /tmp/restore-hollow-python.sh \
    && rm -f /tmp/restore-hollow-python.sh \
    && apt-get install -y --no-install-recommends \
        ros-jazzy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*

COPY src/devices/pinky_pro/bringup/config/cyclonedds_localhost.xml /etc/rosy/cyclonedds.xml

FROM runtime-common AS core-runtime

COPY deploy/robot/requirements-core.txt /tmp/requirements-core.txt
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get install -y --no-install-recommends \
        python3-pip \
        python3-numpy \
        python3-yaml \
        ros-jazzy-nav2-msgs \
        ros-jazzy-lifecycle-msgs \
        ros-jazzy-rcl-interfaces \
        ros-jazzy-visualization-msgs \
        ros-jazzy-tf2-ros \
    && python3 -m pip install --break-system-packages --no-cache-dir \
        -r /tmp/requirements-core.txt \
    && mkdir -p /var/lib/rosy/.rosy \
    && mkdir -p /host/proc/net /host/etc /host/sys/class/thermal /host/sys/devices/virtual/thermal \
    && chown -R 1000:1000 /var/lib/rosy \
    && rm -rf /var/lib/apt/lists/* /tmp/requirements-core.txt

FROM core-runtime AS core-build

COPY deploy/robot/restore-hollow-toolchain.sh /tmp/restore-hollow-toolchain.sh
RUN apt-get -o Acquire::Retries=5 update \
    && bash /tmp/restore-hollow-toolchain.sh \
    && rm -f /tmp/restore-hollow-toolchain.sh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/rosy_ws
# omx/imu/vision/control belong to optional slices, not this core image.
COPY src/contracts/interfaces ./src/contracts/interfaces
COPY src/runtime/gateway ./src/runtime/gateway
# D-196: CORE reads the robot profile from share/<robot.model>/config.
COPY src/products/pinky_pro ./src/products/pinky_pro
RUN set -eo pipefail \
    && source /opt/ros/jazzy/setup.bash \
    && colcon build --merge-install --packages-up-to core pinky_pro \
    && test -d /opt/rosy_ws/install

FROM core-runtime AS core

COPY --from=core-build /opt/rosy_ws/install /opt/rosy_ws/install
COPY deploy/robot/entrypoint.sh /usr/local/bin/rosy-entrypoint
RUN chmod 0755 /usr/local/bin/rosy-entrypoint
ENV HOME=/var/lib/rosy \
    ROSY_CONFIG=/etc/rosy/rosy.yaml \
    CYCLONEDDS_URI=file:///etc/rosy/cyclonedds.xml
ENTRYPOINT ["/usr/local/bin/rosy-entrypoint"]
CMD ["ros2", "run", "core", "core"]

FROM runtime-common AS io-runtime

COPY deploy/robot/requirements-io.txt /tmp/requirements-io.txt
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get install -y --no-install-recommends \
        python3-pip \
        python3-numpy \
        python3-opencv \
        python3-yaml \
        ros-jazzy-joint-state-publisher \
        ros-jazzy-robot-state-publisher \
        ros-jazzy-tf-transformations \
        ros-jazzy-xacro \
        ros-jazzy-navigation2 \
        ros-jazzy-nav2-bringup \
        ros-jazzy-slam-toolbox \
        ros-jazzy-ros2bag \
        ros-jazzy-rosbag2-storage-mcap \
    && python3 -m pip install --break-system-packages --no-cache-dir \
        -r /tmp/requirements-io.txt \
    && rm -rf /var/lib/apt/lists/* /tmp/requirements-io.txt

FROM io-runtime AS io-build

COPY deploy/robot/restore-hollow-toolchain.sh /tmp/restore-hollow-toolchain.sh
RUN apt-get -o Acquire::Retries=5 update \
    && bash /tmp/restore-hollow-toolchain.sh \
    && apt-get install -y --no-install-recommends git \
    && rm -f /tmp/restore-hollow-toolchain.sh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/rosy_ws
ARG SLLIDAR_COMMIT=34300099fadfc772965962dec837bf436706188f
RUN git clone https://github.com/Slamtec/sllidar_ros2.git src/sllidar_ros2 \
    && cd src/sllidar_ros2 \
    && git checkout --detach ${SLLIDAR_COMMIT} \
    && rm -rf .git
COPY src/contracts/interfaces ./src/contracts/interfaces
COPY src/sim/description ./src/sim/description
COPY src/devices/pinky_pro/bringup ./src/devices/pinky_pro/bringup
COPY src/runtime/navigation ./src/runtime/navigation
COPY src/devices/omx/adapter ./src/devices/omx/adapter
COPY src/products/omx ./src/products/omx
COPY src/runtime/sensing ./src/runtime/sensing
RUN mkdir -p src/sim/description/meshes
RUN set -eo pipefail \
    && source /opt/ros/jazzy/setup.bash \
    && colcon build --merge-install \
        --packages-select sllidar_ros2 interfaces description bringup navigation omx_adapter omx control \
    && test -d /opt/rosy_ws/install

FROM io-runtime AS io

COPY --from=io-build /opt/rosy_ws/install /opt/rosy_ws/install
COPY deploy/robot/entrypoint.sh /usr/local/bin/rosy-entrypoint
RUN chmod 0755 /usr/local/bin/rosy-entrypoint
ENV HOME=/var/lib/rosy \
    CYCLONEDDS_URI=file:///etc/rosy/cyclonedds.xml
ENTRYPOINT ["/usr/local/bin/rosy-entrypoint"]
CMD ["ros2", "launch", "bringup", "bringup_robot.launch.py", \
     "cmd_vel_timeout_s:=0.5", "enable_battery:=false"]
