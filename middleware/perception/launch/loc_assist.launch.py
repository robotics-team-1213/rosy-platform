"""D-395 fleet-assisted localization robot node (P2-3); sensing only, no motion output.

Publishes localization/state, localization/candidates, localization/result and,
only for a decision CORE relayed, initialpose. AMCL and map_server come from
the including launch. `map_yaml` lets the node find the map bundle's
lane_rules.yaml (reference squares); without it the search is global only.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('loc_assist', default_value='true', choices=['true', 'false']),
        DeclareLaunchArgument('namespace', default_value=''),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('map_yaml', default_value=''),
        DeclareLaunchArgument('lane_rules_file', default_value=''),
        DeclareLaunchArgument('search_budget_s', default_value='3.0'),
        Node(package='control', executable='loc_assist_node', namespace=LaunchConfiguration('namespace'),
             output='screen', respawn=True, respawn_delay=1.0,
             condition=IfCondition(LaunchConfiguration('loc_assist')),
             parameters=[{
                 'use_sim_time': LaunchConfiguration('use_sim_time'),
                 'map_yaml': LaunchConfiguration('map_yaml'),
                 'lane_rules_file': LaunchConfiguration('lane_rules_file'),
                 'search_budget_s': LaunchConfiguration('search_budget_s'),
             }]),
    ])
