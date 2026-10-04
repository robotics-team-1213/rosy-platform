#!/usr/bin/env python3
"""Prepare (never activate) a simulation-only copy of a reviewed Jazzy Nav2 YAML.

Scoped to the plugin IDs and layout used in the supplied documentation.
No shell commands, ROS publishers, network operations, or in-place edits occur.
Use --write with explicit acknowledgements to save a NEW file. Without --write,
only a change report is printed. Acknowledgements are not technical interlocks.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any
import yaml

ROOT = Path(__file__).resolve().parents[1]
C = ('controller_server', 'ros__parameters')
L = ('local_costmap', 'local_costmap', 'ros__parameters')
G = ('global_costmap', 'global_costmap', 'ros__parameters')
P = ('planner_server', 'ros__parameters')
V = ('velocity_smoother', 'ros__parameters')
CORE = {
 C+('general_goal_checker','xy_goal_tolerance'),
 C+('general_goal_checker','yaw_goal_tolerance'), L+('resolution',),
 G+('resolution',), G+('track_unknown_space',),
 P+('GridBased','tolerance'), P+('GridBased','allow_unknown'),
}
RPP_NAMES = {
 'desired_linear_vel','use_velocity_scaled_lookahead_dist','lookahead_dist',
 'min_lookahead_dist','max_lookahead_dist','lookahead_time',
 'rotate_to_heading_angular_vel','min_approach_linear_velocity',
 'regulated_linear_scaling_min_speed','use_regulated_linear_velocity_scaling',
 'use_cost_regulated_linear_velocity_scaling','cost_scaling_gain',
}
RPP = {C+('FollowPath',n) for n in RPP_NAMES} | {V+('max_velocity',), V+('min_velocity',)}
PROGRESS = {C+('progress_checker','required_movement_radius')}
PROTECTED = {
 'footprint','footprint_padding','robot_radius','inflation_radius','cost_scaling_factor',
 'use_collision_detection','max_allowed_time_to_collision_up_to_carrot',
 'transform_tolerance','failure_tolerance','costmap_update_timeout','velocity_timeout',
 'movement_time_allowance','max_accel','max_decel','max_angular_accel',
 'enabled','marking','clearing','obstacle_min_range','obstacle_max_range',
 'raytrace_min_range','raytrace_max_range','observation_persistence',
 'expected_update_rate','source_timeout','stop_distance','scan_max_age',
}
STANDARD_NODES = {
 'amcl','bt_navigator','controller_server','planner_server','smoother_server',
 'behavior_server','waypoint_follower','velocity_smoother','map_server','map_saver',
}

class StrictLoader(yaml.SafeLoader):
    pass

def unique_mapping(loader: StrictLoader, node: Any, deep: bool=False) -> dict:
    loader.flatten_mapping(node)
    result = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in result:
            raise ValueError(f'Duplicate YAML key: {key!r}; resolve it explicitly.')
        result[key] = loader.construct_object(v, deep=deep)
    return result

StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)

def read_yaml(path: Path) -> dict:
    value = yaml.load(path.read_text(encoding='utf-8'), Loader=StrictLoader)
    if not isinstance(value, dict):
        raise ValueError(f'Expected a YAML mapping: {path}')
    return value

def leaves(value: dict, prefix: tuple=()) -> dict[tuple, Any]:
    out = {}
    for k, v in value.items():
        if not isinstance(k, str):
            raise ValueError('Only string YAML keys are supported.')
        p = prefix+(k,)
        if isinstance(v, dict):
            out.update(leaves(v,p))
        else:
            out[p] = v
    return out

def get(data: dict, path: tuple) -> Any:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            raise ValueError('Missing required base parameter: '+'.'.join(path))
        data = data[key]
    return data

def put(data: dict, path: tuple, value: Any) -> None:
    for key in path[:-1]:
        child = data.setdefault(key,{})
        if not isinstance(child,dict):
            raise ValueError('Expected mapping for '+key)
        data = child
    data[path[-1]] = value

def number(value: Any, label: str, allow_zero: bool=False) -> float:
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number.')
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f'{label} must be positive'+(' or zero.' if allow_zero else '.'))
    return float(value)

def require_plugin(base: dict, path: tuple, expected: str) -> None:
    if get(base,path+('plugin',)) != expected:
        raise ValueError(f'Unsupported plugin at {".".join(path)}; expected {expected}. '
                         'Do not copy these values to a different controller/planner.')

def check_layout(base: dict, use_rpp: bool, use_progress: bool) -> None:
    for p in [C,L,G,P]:
        if not isinstance(get(base,p),dict):
            raise ValueError('Unsupported parameter layout.')
    require_plugin(base,C+('general_goal_checker',),'nav2_controller::SimpleGoalChecker')
    require_plugin(base,P+('GridBased',),'nav2_navfn_planner::NavfnPlanner')
    if 'general_goal_checker' not in get(base,C+('goal_checker_plugins',)):
        raise ValueError('general_goal_checker is not an active goal checker ID.')
    if 'GridBased' not in get(base,P+('planner_plugins',)):
        raise ValueError('GridBased is not an active planner ID.')
    for p in [L,G]:
        block=get(base,p)
        if 'footprint' not in block and 'robot_radius' not in block:
            raise ValueError('Explicit reviewed footprint or robot_radius is required.')
        if 'footprint' in block:
            poly=block['footprint']
            poly=yaml.safe_load(poly) if isinstance(poly,str) else poly
            if not isinstance(poly,list) or len(poly)<3:
                raise ValueError('Footprint must contain at least three XY points.')
            for point in poly:
                if not isinstance(point,(list,tuple)) or len(point)!=2 or not all(
                    isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in point):
                    raise ValueError('Invalid footprint coordinates.')
        if 'robot_radius' in block:
            number(block['robot_radius'],'robot_radius')
        if 'footprint_padding' in block:
            number(block['footprint_padding'],'footprint_padding',True)
    if get(base,G).get('rolling_window',False):
        raise ValueError('This map profile expects a non-rolling global costmap.')
    if 'static_layer' not in get(base,G+('plugins',)):
        raise ValueError('A global static_layer must be active for this reference-map profile.')
    require_plugin(base,G+('static_layer',),'nav2_costmap_2d::StaticLayer')
    if use_rpp:
        require_plugin(base,C+('FollowPath',),
            'nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController')
        if get(base,C+('controller_plugins',)) != ['FollowPath']:
            raise ValueError('RPP trial expects exactly one active controller ID: FollowPath.')
        if get(base,C+('FollowPath','use_collision_detection')) is not True:
            raise ValueError('Collision detection must already be explicitly enabled in the base.')
        number(get(base,C+('FollowPath','max_allowed_time_to_collision_up_to_carrot')),
               'collision prediction time')
        if get(base,C+('FollowPath','allow_reversing')) is not False:
            raise ValueError('This trial profile expects allow_reversing=false; review manually.')
        if get(base,C+('FollowPath','use_rotate_to_heading')) is not True:
            raise ValueError('This trial profile expects use_rotate_to_heading=true.')
        if 'inflation_layer' not in get(base,L+('plugins',)):
            raise ValueError('Active local inflation_layer is required for cost regulation.')
        require_plugin(base,L+('inflation_layer',),'nav2_costmap_2d::InflationLayer')
        if get(base,L+('inflation_layer',)).get('enabled',True) is not True:
            raise ValueError('Local inflation_layer must not be disabled.')
        get(base,V)
    if use_progress:
        require_plugin(base,C+('progress_checker',),'nav2_controller::SimpleProgressChecker')
        if 'progress_checker' not in get(base,C+('progress_checker_plugins',)):
            raise ValueError('progress_checker is not an active progress checker ID.')
        number(get(base,C+('progress_checker','movement_time_allowance')),'progress timeout')

def approved_patch(name: str, allowed: set[tuple]) -> dict[tuple,Any]:
    patch=leaves(read_yaml(ROOT/'config'/name))
    if set(patch) != allowed:
        raise ValueError(f'Unexpected/missing patch keys in {name}; manual review is required.')
    return patch

def prepare(base: dict, map_path: Path, use_rpp: bool=False, use_progress: bool=False) -> tuple[dict,dict]:
    check_layout(base,use_rpp,use_progress)
    meta=read_yaml(map_path)
    if meta.get('mode')!='trinary' or meta.get('origin')!=[-1.5,-0.75,0.0]:
        raise ValueError('This profile expects the delivered world-aligned trinary map.')
    if meta.get('resolution')!=0.005:
        raise ValueError('This profile expects the delivered 0.005 m reference map.')
    if meta.get('negate')!=0 or meta.get('occupied_thresh')!=0.65 or meta.get('free_thresh')!=0.196:
        raise ValueError('Map pixel interpretation differs from this reviewed bundle.')
    if not (map_path.parent/meta['image']).is_file():
        raise ValueError('Map image referenced by YAML does not exist.')
    out=copy.deepcopy(base)
    initial=leaves(base)
    patch=approved_patch('nav2_sim_core.patch.yaml',CORE)
    caps={C+('general_goal_checker','xy_goal_tolerance'),C+('general_goal_checker','yaw_goal_tolerance'),
          L+('resolution',),P+('GridBased','tolerance')}
    for p,value in patch.items():
        if p in caps:
            value=min(number(get(base,p),'.'.join(p),p[-1]=='tolerance'),float(value))
        put(out,p,value)
    for node in STANDARD_NODES:
        if node in out:
            params=out[node].get('ros__parameters')
            if not isinstance(params,dict):
                raise ValueError(f'{node}.ros__parameters must be a mapping.')
            params['use_sim_time']=True
    for p in [L,G]:
        put(out,p+('use_sim_time',),True)
    put(out,('map_server','ros__parameters','use_sim_time'),True)
    put(out,('map_server','ros__parameters','yaml_filename'),str(map_path.resolve()))
    if use_rpp:
        rp=approved_patch('nav2_sim_rpp_trial.patch.yaml',RPP)
        capped={'desired_linear_vel','rotate_to_heading_angular_vel','min_approach_linear_velocity',
                'regulated_linear_scaling_min_speed','cost_scaling_gain'}
        for p,value in rp.items():
            if p[-1] in capped:
                value=min(number(get(base,p),'.'.join(p)),float(value))
            elif p[-1] in ('max_velocity','min_velocity'):
                old=get(base,p)
                if not isinstance(old,list) or len(old)!=3:
                    raise ValueError('Velocity smoother limits must have [vx,vy,wz].')
                if any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) for x in old):
                    raise ValueError('Velocity limits must be finite numbers.')
                if p[-1]=='max_velocity':
                    if any(x<0 for x in old): raise ValueError('Expected non-negative max_velocity.')
                    value=[min(float(a),float(b)) for a,b in zip(old,value)]
                else:
                    if any(x>0 for x in old): raise ValueError('Expected non-positive min_velocity.')
                    value=[max(float(a),float(b)) for a,b in zip(old,value)]
            put(out,p,value)
        radius=number(get(base,L+('inflation_layer','inflation_radius')),'local inflation radius')
        factor=number(get(base,L+('inflation_layer','cost_scaling_factor')),'local inflation factor')
        olddist=number(get(base,C+('FollowPath','cost_scaling_dist')),'RPP cost scaling distance')
        put(out,C+('FollowPath','cost_scaling_dist'),min(olddist,radius))
        put(out,C+('FollowPath','inflation_cost_scaling_factor'),factor)
        desired=get(out,C+('FollowPath','desired_linear_vel'))
        for name in ['min_approach_linear_velocity','regulated_linear_scaling_min_speed']:
            p=C+('FollowPath',name)
            put(out,p,min(get(out,p),desired))
    if use_progress:
        for p,value in approved_patch('nav2_sim_progress_trial.patch.yaml',PROGRESS).items():
            put(out,p,min(number(get(base,p),'.'.join(p)),float(value)))
    final=leaves(out)
    for p,value in initial.items():
        if p[-1] in PROTECTED and final.get(p)!=value:
            raise ValueError('Protected value would change: '+'.'.join(p))
    changes=[{'path':'.'.join(p),'before':initial.get(p),'after':v}
             for p,v in final.items() if p not in initial or initial[p]!=v]
    report={
        'status':'SIMULATION_CANDIDATE_ONLY','rpp_trial':use_rpp,'progress_trial':use_progress,
        'protected_base_values_unchanged':True,'changes':changes,
        'limitations':[
            'No actual robot geometry, stopping distance or hardware isolation was measured.',
            'No Gazebo, ROS or Nav2 runtime execution was performed by this script.',
            'Only existing standard Nav2 node blocks and map_server use_sim_time are set here.',
            'Custom guards, robot_state_publisher, SLAM, bridge and launch-time overrides need separate review.',
            'Output is a merged copy; source YAML and project safety files are never edited.',
        ]}
    return out,report

def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base',type=Path,required=True)
    ap.add_argument('--map',type=Path,default=ROOT/'maps/map_260905.yaml')
    ap.add_argument('--output',type=Path)
    ap.add_argument('--rpp-trial',action='store_true')
    ap.add_argument('--progress-trial',action='store_true')
    ap.add_argument('--write',action='store_true')
    ap.add_argument('--ack-simulation-only',action='store_true')
    ap.add_argument('--ack-footprint-reviewed',action='store_true')
    ap.add_argument('--ack-lookahead-reviewed',action='store_true')
    ap.add_argument('--ack-progress-reviewed',action='store_true')
    args=ap.parse_args()
    if args.write:
        if args.output is None: ap.error('--output is required with --write.')
        if not(args.ack_simulation_only and args.ack_footprint_reviewed):
            ap.error('Writing requires --ack-simulation-only and --ack-footprint-reviewed.')
        if args.rpp_trial and not args.ack_lookahead_reviewed:
            ap.error('RPP trial requires --ack-lookahead-reviewed before writing.')
        if args.progress_trial and not args.ack_progress_reviewed:
            ap.error('Progress trial requires --ack-progress-reviewed before writing.')
        if args.output.resolve()==args.base.resolve() or args.output.exists():
            ap.error('Refusing to overwrite an existing file. Select a NEW output path.')
        if args.output.with_suffix('.review.json').exists():
            ap.error('Review report already exists; select a NEW output path.')
    out,report=prepare(read_yaml(args.base),args.map,args.rpp_trial,args.progress_trial)
    report.update(base_sha256=hashlib.sha256(args.base.read_bytes()).hexdigest(),
                  base_path=str(args.base.resolve()),map_path=str(args.map.resolve()),
                  saved=False)
    if args.write:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as f:
            f.write('# SIMULATION CANDIDATE ONLY. Hardware approval and runtime validation: NOT PROVIDED.\n')
            f.write(yaml.safe_dump(out,sort_keys=False,allow_unicode=True))
        report['saved']=True
        report['output_sha256']=hashlib.sha256(args.output.read_bytes()).hexdigest()
        with args.output.with_suffix('.review.json').open('x',encoding='utf-8') as f:
            json.dump(report,f,indent=2,ensure_ascii=False)
    print(json.dumps(report,indent=2,ensure_ascii=False))

if __name__=='__main__':
    try:
        main()
    except (OSError,ValueError,KeyError,TypeError,yaml.YAMLError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        raise SystemExit(1)
