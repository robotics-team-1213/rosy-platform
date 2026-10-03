"""D-395 P2-3 launch contract: where loc_assist_node starts and where it stays off.

Text checks run on the host; the parameter evaluation runs where ROS 2 `launch` imports.
Device default off: the global search is unmeasured on the Pi with the site map
(loc_candidates.py cost note) and CORE does not relay decisions yet (lane B).
"""
import importlib.util
from pathlib import Path

import pytest

SENSING = Path(__file__).resolve().parents[1]
SRC = SENSING.parents[1]
LAUNCH = SENSING / 'launch' / 'loc_assist.launch.py'
HARDWARE = SRC.parent / 'middleware' / 'core' / 'navigation' / 'launch' / 'hardware.launch.py'
GZ_MULTI = SRC.parent / 'integrations' / 'simulation' / 'gazebo' / 'launch' / 'gz_multi.launch.py'
LEGACY = SENSING / 'launch' / 'localization.launch.py'


def text(path):
    return path.read_text(encoding='utf-8')


def test_the_sensing_launch_starts_only_the_node_and_no_motion_output():
    launch = text(LAUNCH)
    assert "executable='loc_assist_node'" in launch
    assert "DeclareLaunchArgument('loc_assist', default_value='true'" in launch
    assert "IfCondition(LaunchConfiguration('loc_assist'))" in launch
    assert 'Twist' not in launch and 'cmd_vel' not in launch


def test_the_entry_point_is_installed():
    assert "'loc_assist_node = control.loc_assist_node:main'" in text(SENSING / 'setup.py')


def test_the_device_hardware_launch_has_it_off_by_default():
    hardware = text(HARDWARE)
    assert 'DeclareLaunchArgument("enable_loc_assist", default_value="false")' in hardware
    assert '"loc_assist.launch.py"' in hardware
    assert 'condition=IfCondition(LaunchConfiguration("enable_loc_assist"))' in hardware
    assert '"map_yaml": LaunchConfiguration("map")' in hardware


def test_gazebo_multi_robot_nav_has_it_on_by_default():
    gz = text(GZ_MULTI)
    assert 'DeclareLaunchArgument("loc_assist", default_value="true"' in gz
    assert '"loc_assist.launch.py"' in gz
    assert '"namespace": ns, "use_sim_time": "true"' in gz


def test_the_legacy_localization_launch_brings_the_node_its_readiness_waits_for():
    legacy = text(LEGACY)
    assert "'loc_assist.launch.py'" in legacy
    assert "executable='localization_node'" in legacy


def test_nav2_keeps_its_initial_pose_setting():
    """The user decides set_initial_pose separately; P2-3 leaves it as it is."""
    params = text(SRC.parent / 'middleware' / 'core' / 'navigation' / 'params' / 'nav2_params.yaml')
    assert 'set_initial_pose: true' in params


def test_localization_node_no_longer_injects_or_scatters_amcl():
    node = text(SENSING / 'control' / 'localization_node.py')
    assert 'create_publisher(PoseWithCovarianceStamped' not in node
    assert "create_client(Empty, 'reinitialize_global_localization')" not in node
    assert "'localization/state'" in node


def test_launch_parameters_evaluate_to_typed_values():
    launch = pytest.importorskip('launch')
    if not hasattr(launch, 'LaunchContext'):
        pytest.skip('`launch` is not ROS 2 launch here')
    from launch_ros.actions import Node
    from launch_ros.utilities import evaluate_parameters
    spec = importlib.util.spec_from_file_location('loc_assist_launch', LAUNCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    description = module.generate_launch_description()
    context = launch.LaunchContext()
    for action in description.entities:
        if isinstance(action, launch.actions.DeclareLaunchArgument):
            action.visit(context)
    node = next(a for a in description.entities if isinstance(a, Node))
    params = evaluate_parameters(context, node._Node__parameters)[0]
    assert params['use_sim_time'] is False and params['search_budget_s'] == 3.0
    assert params['map_yaml'] == '' and params['lane_rules_file'] == ''


def test_the_gazebo_localization_rig_follows_d395_not_the_removed_global_recovery():
    """tools/gz is not CI; this keeps the rig from silently testing what no longer exists."""
    rig = text(SENSING / 'tools' / 'gz' / 'localization_rig.py')
    assert "'recoveries'" not in rig
    assert "component == 'loc_assist'" in rig
    assert "'localization/decision'" in rig and "'/localization/candidates'" in rig
