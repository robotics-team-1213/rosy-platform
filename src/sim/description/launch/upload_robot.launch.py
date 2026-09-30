import os
from os import environ

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, Shutdown
from launch.substitutions import LaunchConfiguration, Command, TextSubstitution
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
from launch.substitutions import PathJoinSubstitution, PythonExpression

def generate_launch_description():
    ld = LaunchDescription()

    namespace_arg = DeclareLaunchArgument("namespace", default_value="")
    is_sim = DeclareLaunchArgument("is_sim", default_value="false")
    cam_tilt_deg = DeclareLaunchArgument("cam_tilt_deg", default_value="0")
    camera_width = DeclareLaunchArgument("camera_width", default_value="1280")
    camera_height = DeclareLaunchArgument("camera_height", default_value="720")
    camera_update_rate = DeclareLaunchArgument(
        "camera_update_rate", default_value="10")
    # Real-profile sims (D-364 5) set the real robot's camera geometry.
    camera_hfov = DeclareLaunchArgument("camera_hfov", default_value="1.1519")
    cam_mount_z = DeclareLaunchArgument("cam_mount_z", default_value="0.0495")

    namespace = PythonExpression([
        "'", LaunchConfiguration('namespace'), "' + ('/' if '", LaunchConfiguration('namespace'), "' != '' else '')"
    ])

    rsp_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        namespace=LaunchConfiguration('namespace'),
        parameters=[{
            'ignore_timestamp': False,
            "use_sim_time": LaunchConfiguration('is_sim'),
            'robot_description':
                Command([
                    'xacro ',
                    '"',
                    PathJoinSubstitution([
                        get_package_share_directory('description'),
                        'urdf/robot.urdf.xacro',
                    ]),
                    '"',
                    ' namespace:=', namespace,
                    ' is_sim:=', LaunchConfiguration('is_sim'),
                    ' cam_tilt_deg:=', LaunchConfiguration('cam_tilt_deg'),
                    ' camera_width:=', LaunchConfiguration('camera_width'),
                    ' camera_height:=', LaunchConfiguration('camera_height'),
                    ' camera_update_rate:=', LaunchConfiguration(
                        'camera_update_rate'),
                    ' camera_hfov:=', LaunchConfiguration('camera_hfov'),
                    ' cam_mount_z:=', LaunchConfiguration('cam_mount_z'),
                ]),
            'frame_prefix': [namespace],
        }]
    )

    jsp_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        namespace=LaunchConfiguration('namespace'),
        parameters=[{
            "source_list": ['joint_states'],
            "rate": 20.0,
            "use_sim_time": LaunchConfiguration('is_sim'),
        }],
        remappings=[
            ('/robot_descrption', 'robot_descrpition'),
        ],
        output='screen'
    )

    ld.add_action(namespace_arg)
    ld.add_action(is_sim)
    ld.add_action(cam_tilt_deg)
    ld.add_action(camera_width)
    ld.add_action(camera_height)
    ld.add_action(camera_update_rate)
    ld.add_action(camera_hfov)
    ld.add_action(cam_mount_z)
    ld.add_action(rsp_node)
    ld.add_action(jsp_node)

    return ld
