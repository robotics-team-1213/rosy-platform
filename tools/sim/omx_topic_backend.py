#!/usr/bin/env python3
"""D-866 P2 shared simulator layer: the OMX ros2_control graph any topic-driven simulator plugs into.

A simulator adapter (MuJoCo, Isaac, ...) only publishes SIM_STATES (sensor_msgs/JointState for every URDF joint),
applies SIM_COMMANDS, and publishes /clock and the top/front cameras. This starts the vendor OMX-F description on
topic_based_ros2_control with the vendor controller config and arm constraints, so the owner sees the same
/joint_states and /arm_controller/follow_joint_trajectory as on Gazebo (gz_ros2_control) and the real cell.

Run with ROS, the OMX overlay and the topic_based_ros2_control overlay sourced:
  python3 tools/sim/omx_topic_backend.py --out DIR      # blocks; prints OMX_TOPIC_BACKEND_READY
"""
import argparse
from contextlib import ExitStack
from pathlib import Path
import re
import subprocess
import sys

SIM_STATES, SIM_COMMANDS = '/sim/joint_states', '/sim/joint_commands'
HARDWARE = ('<hardware><plugin>topic_based_ros2_control/TopicBasedSystem</plugin>'
            f'<param name="joint_commands_topic">{SIM_COMMANDS}</param>'
            f'<param name="joint_states_topic">{SIM_STATES}</param>'
            # Always send the command, so a held target keeps reaching the simulator.
            '<param name="trigger_joint_command_threshold">-1</param></hardware>')


def with_topic_hardware(urdf):
    """Swap the vendor mock hardware for the topic bridge; joints, limits and interfaces stay the vendor's.

    The vendor block also declares the Dynamixel registers as <gpio> (dxl11..16); only the real driver exports
    them, and ros2_control refuses a hardware that leaves declared interfaces unexported, so they are dropped.
    """
    out, count = re.subn(r'<hardware>.*?</hardware>', HARDWARE, urdf, flags=re.S)
    if count != 1:
        raise ValueError('expected exactly one vendor <hardware> block')
    out = re.sub(r'<gpio.*?</gpio>', '', out, flags=re.S)
    return re.sub(r'(<ros2_control[^>]*?)is_async="true"', r'\1is_async="false"', out)


def description():
    from ament_index_python.packages import get_package_share_directory
    xacro = Path(get_package_share_directory('open_manipulator_description'))/'urdf/omx_f/omx_f.urdf.xacro'
    urdf = subprocess.run(['xacro', str(xacro), 'use_mock_hardware:=true', 'config_type:=omx_f_follower_ai'],
                          check=True, capture_output=True, text=True).stdout
    return with_topic_hardware(urdf)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    from ament_index_python.packages import get_package_share_directory
    import yaml
    config = Path(get_package_share_directory('open_manipulator_bringup'))/'config/omx_f_follower_ai'
    args.out.mkdir(parents=True, exist_ok=True)
    urdf = description()
    (args.out/'omx_f_topic.urdf').write_text(urdf)
    rsp = args.out/'robot_state_publisher.yaml'
    rsp.write_text(yaml.safe_dump({'robot_state_publisher': {'ros__parameters': {
        'robot_description': urdf, 'use_sim_time': True}}}))
    sim_time = ['--ros-args', '-p', 'use_sim_time:=true']
    with ExitStack() as stack:
        def start(name, argv):
            log = stack.enter_context((args.out/(name+'.log')).open('wb'))
            child = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
            stack.callback(lambda: (child.terminate(), child.wait(10)))
            return child
        start('robot_state_publisher', ['ros2', 'run', 'robot_state_publisher', 'robot_state_publisher',
                                        '--ros-args', '--params-file', str(rsp)])
        manager = start('ros2_control_node', ['ros2', 'run', 'controller_manager', 'ros2_control_node', *sim_time,
                                              '--params-file', str(config/'hardware_controller_manager.yaml')])
        # Same order and constraints as the vendor Gazebo launch (omx_f_follower_ai_gazebo.launch.py).
        for name, extra in (('joint_state_broadcaster', []),
                            ('arm_controller', ['--param-file', str(config/'gazebo_arm_controller_constraints.yaml')])):
            spawner = subprocess.run(['ros2', 'run', 'controller_manager', 'spawner', name, *extra, *sim_time],
                                     capture_output=True, text=True, timeout=120)
            (args.out/f'spawner-{name}.log').write_text(spawner.stdout+spawner.stderr)
            if spawner.returncode:
                raise SystemExit(f'spawner {name} failed; see spawner-{name}.log')
        print('OMX_TOPIC_BACKEND_READY', flush=True)
        manager.wait()
    sys.exit(manager.returncode or 0)


if __name__ == '__main__':
    main()
