"""Launch descriptors select one coherent fixed map bundle without starting Gazebo."""
from pathlib import Path
import os
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize('variant', ['.', 'training-curved', 'invalid'])
def test_actual_ros_multi_map_selector_preserves_default_and_matches_catalog(tmp_path, variant):
    if not Path('/opt/ros/jazzy/setup.bash').exists():
        pytest.skip('Requires installed ROS Jazzy launch')
    script = tmp_path/'variant.py'
    script.write_text("""import importlib.util,sys
from pathlib import Path
root=Path(sys.argv[1]);variant=sys.argv[2]
sys.path[:0]=[str(root/'integrations/simulation/gazebo/launch'),str(root/'middleware/perception'),str(root/'contracts/foundation')]
from launch import LaunchContext
from launch.actions import DeclareLaunchArgument,IncludeLaunchDescription,OpaqueFunction
from launch.utilities import perform_substitutions,normalize_to_list_of_substitutions
from launch_ros.utilities import evaluate_parameters
from world_profiles import profile_for,resolve_world_path
path=root/'integrations/simulation/gazebo/launch/map_v2_fleet_multi_real.launch.py'
spec=importlib.util.spec_from_file_location('variant_launch',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
share=root/'middleware/perception'
mod.get_package_share_directory=lambda name:str(share if name=='control' else root/'integrations/simulation/gazebo')
mod.load_run_spec=lambda _: {'valid':'test-only-descriptors'}
mod.run_spec_overlay=lambda _,ns: ns
mod.observer_steering_law=lambda _: {}
actions=mod.generate_launch_description().entities
arg=next(a for a in actions if isinstance(a,DeclareLaunchArgument) and a.name=='map_variant')
ctx=LaunchContext();arg.execute(ctx)
assert ctx.launch_configurations['map_variant']=='training-curved'
ctx.launch_configurations.update(map_variant=variant,run_spec='test-only',learned_lane_pointer='/test-only/model')
if variant=='invalid':
 try:arg.execute(ctx)
 except RuntimeError:print('invalid rejected before simulation');sys.exit(0)
 raise AssertionError('invalid variant accepted')
for a in tuple(actions):
 if isinstance(a,OpaqueFunction):actions.extend(a.execute(ctx))
include=next(a for a in actions if isinstance(a,IncludeLaunchDescription))
kwargs=dict(include.launch_arguments)
name=perform_substitutions(ctx,normalize_to_list_of_substitutions(kwargs['world_name']))
assert name==('map_v2_fleet_real.world' if variant=='.' else 'map_v2_fleet_curved.world')
original=profile_for('map_v2_fleet_real.world');curved=profile_for('map_v2_fleet_curved.world')
assert all(getattr(original,key)==getattr(curved,key) for key in ['map','inflation_radius','spawn_x','spawn_y','spawn_spacing'])
world=resolve_world_path(profile_for(name),root/'integrations/simulation/gazebo',package_share=lambda _:share)
expected=share/'map/map_v2_fleet'/variant
assert world.resolve()==(expected/'worlds/map_v2_fleet_real.world').resolve() and world.is_file()
observers=[a for a in actions if getattr(a,'_Node__node_executable',None) and perform_substitutions(ctx,normalize_to_list_of_substitutions(a._Node__node_executable))=='line_observer_node']
assert len(observers)==2
for n in observers:
 params={k:v for group in evaluate_parameters(ctx,n._Node__parameters) if isinstance(group,dict) for k,v in group.items()}
 assert Path(params['lane_graph_path']).resolve()==(expected/'lane_graph.yaml').resolve()
 assert params['camera_lane_mode']=='keep' and params['use_sim_time'] is True
assert perform_substitutions(ctx,normalize_to_list_of_substitutions(kwargs['mode']))=='none'
print('world and both observer graphs agree; descriptors only')
""",encoding='utf-8')
    result=subprocess.run(['bash','-c','source /opt/ros/jazzy/setup.bash && exec /usr/bin/python3 "$@"',
        'variant-check',str(script),str(ROOT),variant],env=dict(os.environ,ROS_LOCALHOST_ONLY='1'),
        text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    assert result.returncode==0,result.stdout
