# Development/workcell image only. This is not the signed Pi product image.
# open_manipulator and its companion repositories are fetched from stack.lock.yaml.
FROM ros:jazzy-ros-base

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV ROS_DISTRO=jazzy \
    ROS_DOMAIN_ID=30 \
    ROS_LOCALHOST_ONLY=0 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      git python3-yaml python3-rosdep python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/* \
    && rosdep update

WORKDIR /opt/omx_ws
COPY stack.lock.yaml /opt/omx_ws/stack.lock.yaml
COPY fetch_sources.py /usr/local/bin/fetch_omx_sources.py
RUN python3 /usr/local/bin/fetch_omx_sources.py /opt/omx_ws/stack.lock.yaml /opt/omx_ws/src
COPY patches/omx-f-gazebo-headless.patch /tmp/omx-f-gazebo-headless.patch
RUN git -C /opt/omx_ws/src/open_manipulator apply --check /tmp/omx-f-gazebo-headless.patch \
    && git -C /opt/omx_ws/src/open_manipulator apply /tmp/omx-f-gazebo-headless.patch

RUN apt-get update \
    && source /opt/ros/${ROS_DISTRO}/setup.bash \
    && rosdep install \
      --from-paths \
        src/open_manipulator/open_manipulator_bringup \
        src/open_manipulator/open_manipulator_description \
        src/open_manipulator/ros2_controller/om_joint_trajectory_command_broadcaster \
        src/dynamixel_hardware_interface \
        src/dynamixel_interfaces \
        src/DynamixelSDK/ros/dynamixel_sdk \
        src/DynamixelSDK/ros/dynamixel_sdk_custom_interfaces \
        src/robotis_interfaces \
      --ignore-src --rosdistro ${ROS_DISTRO} -r -y \
      --skip-keys "rviz2 realsense2_description joint_state_publisher_gui" \
    && colcon build --merge-install --install-base /opt/omx_ws/install \
      --packages-select \
        open_manipulator_bringup \
        open_manipulator_description \
        om_joint_trajectory_command_broadcaster \
        dynamixel_hardware_interface dynamixel_interfaces \
        dynamixel_sdk dynamixel_sdk_custom_interfaces robotis_interfaces

# D-117: workstation ROS graphs use the same RMW implementation as Rosy OS.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ros-jazzy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*

ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

COPY entrypoint.sh /usr/local/bin/omx-entrypoint
RUN chmod 0755 /usr/local/bin/omx-entrypoint
ENTRYPOINT ["/usr/local/bin/omx-entrypoint"]
# An interactive, inert shell is the default. No vendor launch or motion starts.
CMD ["bash"]
