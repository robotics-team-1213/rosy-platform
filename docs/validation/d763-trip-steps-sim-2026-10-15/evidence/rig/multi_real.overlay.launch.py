"""D-676: two camera robots, one selected map world, independent COREs; no motion request."""
import os
import sys

_LAUNCH_DIR = os.path.dirname(os.path.abspath(__file__))
if _LAUNCH_DIR not in sys.path:
    sys.path.insert(0, _LAUNCH_DIR)
from gz_multi_parts import load_run_spec, observer_steering_law, run_spec_overlay

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    gz_share = get_package_share_directory('gz_sim')
    control_share = get_package_share_directory('control')
    actions = [
        DeclareLaunchArgument('map_variant', default_value='training-curved', choices=['.', 'training-curved']),
        DeclareLaunchArgument('run_spec', description='Runner-owned two-robot reservations and CORE overlays'),
        DeclareLaunchArgument('learned_lane_pointer', description='Pinned existing segmentation model pointer'),
        DeclareLaunchArgument('spawn_poses', default_value='-1.26955,0.24255,-1.570796;-1.26955,0.64,-1.570796'),
    ]
    actions.append(OpaqueFunction(function=_observers, kwargs={'control_share': control_share, 'gz_share': gz_share}))
    return LaunchDescription(actions)


def _observers(context, *, control_share, gz_share):
    spec = load_run_spec(LaunchConfiguration('run_spec').perform(context))
    if not spec:
        raise RuntimeError('two-camera launch requires a runner-owned run_spec')
    variant = LaunchConfiguration('map_variant', default='training-curved').perform(context)
    world_name = {'.': 'map_v2_fleet_real.world', 'training-curved': 'map_v2_fleet_curved.world'}[variant]
    map_bundle = PathJoinSubstitution([control_share, 'map', 'map_v2_fleet', variant])
    actions = [
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(gz_share, 'launch', 'gz_multi.launch.py')),
            launch_arguments=dict(robots='2', prefix='rosy', world_name=world_name,
                                  mode='none', headless='true', nominal_camera='true', core='true',
                                  run_spec=LaunchConfiguration('run_spec'),
                                  spawn_poses=LaunchConfiguration('spawn_poses')).items()),
    ]
    for ns in ('rosy_01', 'rosy_02'):
        actions.extend([
            # D-118: dedicated local camera transport; never in gz_multi's parameter bridge.
            Node(package='ros_gz_image', executable='image_bridge', namespace=ns,
                 name='front_image_bridge', arguments=[f'/{ns}/camera/image_raw'],
                 remappings=[(f'/{ns}/camera/image_raw', f'/{ns}/camera/front')], output='screen'),
            Node(package='control', executable='line_observer_node', namespace=ns,
                 name='line_observer_node', output='screen',
                 parameters=[os.path.join(control_share, 'config', 'line_follow.yaml'), {
                     'use_sim_time': True, 'camera_lane_mode': 'keep', 'paint_source': 'learned',
                     'ir_calibration_enabled': True, 'ir_black': [2000.0, 2000.0, 2000.0],
                     'ir_white': [4000.0, 4000.0, 4000.0],
                     'learned_paint_target': 'lane_marking', 'learned_paint_every_n': 1,
                     'crosswalk_uncertainty_enabled': True,
                     'learned_lane_pointer': ParameterValue(LaunchConfiguration('learned_lane_pointer'), value_type=str),
                     'require_camera_controls_stable': False,
                     'camera_ground_source': 'GAZEBO', 'allow_simulation_ground': True,
                     'gazebo_camera_height_m': .06343, 'gazebo_camera_pitch_rad': .13962634015954636,
                     'gazebo_camera_hfov_rad': 1.0334, 'gazebo_camera_max_range_m': .6,
                     'camera_x_offset_m': .03317,
                     'lane_graph_path': PathJoinSubstitution([map_bundle, 'lane_graph.yaml']),
                 }, observer_steering_law(run_spec_overlay(spec, ns))]),
            Node(package='control', executable='road_observer_node', namespace=ns,
                 name='road_observer_node', output='screen',
                 parameters=[os.path.join(control_share, 'config', 'line_follow.yaml'), {
                     'use_sim_time': True, 'map_id': 'map_v2_fleet',
                     'scene_revision': 'road-scene-v1',
                     'rotate_deg': 0, 'require_camera_controls_stable': False,
                     'dashboard_source': 'GAZEBO', 'camera_ground_mode': 'gazebo_pinhole',
                     'allow_simulation_ground': True,
                     'gazebo_camera_height_m': .06343,
                     'gazebo_camera_pitch_rad': .13962634015954636,
                     'gazebo_camera_hfov_rad': 1.0334,
                     'gazebo_camera_max_range_m': .6,
                 }]),
        ])
    return actions
