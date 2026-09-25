"""Synthetic unit fixtures only. These are NOT a deployable robot configuration."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import yaml

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('prep',ROOT/'scripts/prepare_sim_params.py')
m=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def fixture() -> dict:
    fp='[[0.06,0.06],[0.06,-0.06],[-0.06,-0.06],[-0.06,0.06]]'
    ctrl={
      'use_sim_time':False,'controller_plugins':['FollowPath'],
      'goal_checker_plugins':['general_goal_checker'],'progress_checker_plugins':['progress_checker'],
      'failure_tolerance':0.3,'costmap_update_timeout':0.3,
      'general_goal_checker':{'plugin':'nav2_controller::SimpleGoalChecker',
                              'xy_goal_tolerance':0.25,'yaw_goal_tolerance':0.25,'stateful':True},
      'progress_checker':{'plugin':'nav2_controller::SimpleProgressChecker',
                          'required_movement_radius':0.5,'movement_time_allowance':10.0},
      'FollowPath':{
        'plugin':'nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController',
        'desired_linear_vel':0.2,'lookahead_dist':0.6,'min_lookahead_dist':0.3,
        'max_lookahead_dist':0.9,'lookahead_time':1.5,'use_velocity_scaled_lookahead_dist':True,
        'rotate_to_heading_angular_vel':1.0,'min_approach_linear_velocity':0.05,
        'regulated_linear_scaling_min_speed':0.05,'use_regulated_linear_velocity_scaling':False,
        'use_cost_regulated_linear_velocity_scaling':True,'cost_scaling_dist':0.6,
        'cost_scaling_gain':1.5,'inflation_cost_scaling_factor':3.0,
        'use_collision_detection':True,'max_allowed_time_to_collision_up_to_carrot':1.0,
        'allow_reversing':False,'use_rotate_to_heading':True,'transform_tolerance':0.2,
        'max_angular_accel':3.2}}
    local={'footprint':fp,'footprint_padding':0.01,'resolution':0.05,
      'plugins':['voxel_layer','inflation_layer'],
      'inflation_layer':{'plugin':'nav2_costmap_2d::InflationLayer','inflation_radius':0.15,'cost_scaling_factor':3.0},
      'voxel_layer':{'enabled':True,'scan':{'marking':True,'clearing':True}}}
    global_={'footprint':fp,'footprint_padding':0.03,'resolution':0.05,'track_unknown_space':True,
      'plugins':['static_layer','inflation_layer'],
      'static_layer':{'plugin':'nav2_costmap_2d::StaticLayer'},
      'inflation_layer':{'plugin':'nav2_costmap_2d::InflationLayer','inflation_radius':0.15,'cost_scaling_factor':3.0}}
    return {
      'amcl':{'ros__parameters':{'use_sim_time':False}},
      'controller_server':{'ros__parameters':ctrl},
      'local_costmap':{'local_costmap':{'ros__parameters':local}},
      'global_costmap':{'global_costmap':{'ros__parameters':global_}},
      'planner_server':{'ros__parameters':{'planner_plugins':['GridBased'],
         'GridBased':{'plugin':'nav2_navfn_planner::NavfnPlanner','tolerance':0.5,'allow_unknown':True}}},
      'velocity_smoother':{'ros__parameters':{'max_velocity':[0.25,0.0,1.5],
         'min_velocity':[-0.25,0.0,-1.5],'max_accel':[2.5,0.0,3.2],
         'max_decel':[-2.5,0.0,-3.2],'velocity_timeout':1.0}},
      'custom_hardware_guard':{'ros__parameters':{'use_sim_time':False,'scan_max_age':0.13}},
    }

class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture();self.map=ROOT/'maps/map_260905.yaml'

    def test_core_values(self):
        out,r=m.prepare(self.base,self.map)
        self.assertEqual(m.get(out,m.C+('general_goal_checker','xy_goal_tolerance')),0.03)
        self.assertEqual(m.get(out,m.P+('GridBased','tolerance')),0.02)
        self.assertEqual(m.get(out,m.L+('resolution',)),0.01)
        self.assertEqual(m.get(out,m.G+('resolution',)),0.005)
        self.assertTrue(r['protected_base_values_unchanged'])

    def test_core_does_not_change_rpp_progress(self):
        out,_=m.prepare(self.base,self.map)
        self.assertEqual(m.get(out,m.C+('FollowPath',)),m.get(self.base,m.C+('FollowPath',)))
        self.assertEqual(m.get(out,m.C+('progress_checker',)),m.get(self.base,m.C+('progress_checker',)))

    def test_base_is_unchanged(self):
        before=copy.deepcopy(self.base)
        m.prepare(self.base,self.map,True,True)
        self.assertEqual(self.base,before)

    def test_smaller_goal_and_resolution_are_preserved(self):
        m.put(self.base,m.C+('general_goal_checker','xy_goal_tolerance'),0.01)
        m.put(self.base,m.P+('GridBased','tolerance'),0.0)
        m.put(self.base,m.L+('resolution',),0.005)
        out,_=m.prepare(self.base,self.map)
        self.assertEqual(m.get(out,m.C+('general_goal_checker','xy_goal_tolerance')),0.01)
        self.assertEqual(m.get(out,m.P+('GridBased','tolerance')),0.0)
        self.assertEqual(m.get(out,m.L+('resolution',)),0.005)

    def test_clock_scope_and_custom_guard_preservation(self):
        out,_=m.prepare(self.base,self.map)
        self.assertIs(m.get(out,m.C+('use_sim_time',)),True)
        self.assertIs(m.get(out,m.L+('use_sim_time',)),True)
        self.assertIs(out['custom_hardware_guard']['ros__parameters']['use_sim_time'],False)

    def test_footprint_padding_inflation_and_watchdogs_preserved(self):
        out,_=m.prepare(self.base,self.map,True,True)
        old=m.leaves(self.base);new=m.leaves(out)
        for p,v in old.items():
            if p[-1] in m.PROTECTED:self.assertEqual(new[p],v,p)

    def test_rpp_cost_consistency(self):
        m.put(self.base,m.L+('inflation_layer','cost_scaling_factor'),4.0)
        out,_=m.prepare(self.base,self.map,True)
        self.assertEqual(m.get(out,m.C+('FollowPath','cost_scaling_dist')),0.15)
        self.assertEqual(m.get(out,m.C+('FollowPath','cost_scaling_gain')),1.0)
        self.assertEqual(m.get(out,m.C+('FollowPath','inflation_cost_scaling_factor')),4.0)

    def test_more_conservative_speed_limits_preserved(self):
        m.put(self.base,m.C+('FollowPath','desired_linear_vel'),0.07)
        m.put(self.base,m.V+('max_velocity',),[0.08,0.0,0.3])
        m.put(self.base,m.V+('min_velocity',),[0.0,0.0,-0.3])
        out,_=m.prepare(self.base,self.map,True)
        self.assertEqual(m.get(out,m.C+('FollowPath','desired_linear_vel')),0.07)
        self.assertEqual(m.get(out,m.V+('max_velocity',)),[0.08,0.0,0.3])
        self.assertEqual(m.get(out,m.V+('min_velocity',)),[0.0,0.0,-0.3])

    def test_progress_timeout_not_overwritten(self):
        m.put(self.base,m.C+('progress_checker','movement_time_allowance'),7.0)
        out,_=m.prepare(self.base,self.map,False,True)
        self.assertEqual(m.get(out,m.C+('progress_checker','required_movement_radius')),0.05)
        self.assertEqual(m.get(out,m.C+('progress_checker','movement_time_allowance')),7.0)

    def test_unsupported_controller_rejected(self):
        m.put(self.base,m.C+('FollowPath','plugin'),'dwb_core::DWBLocalPlanner')
        with self.assertRaises(ValueError):m.prepare(self.base,self.map,True)

    def test_disabled_collision_detection_rejected(self):
        m.put(self.base,m.C+('FollowPath','use_collision_detection'),False)
        with self.assertRaises(ValueError):m.prepare(self.base,self.map,True)

    def test_unsupported_namespaced_layout_rejected(self):
        with self.assertRaises(ValueError):m.prepare({'robot':self.base},self.map)

    def test_unexpected_patch_key_rejected(self):
        with mock.patch.object(m,'read_yaml',return_value={'local_costmap':{'footprint':[]}}):
            with self.assertRaises(ValueError):m.approved_patch('unused.yaml',m.CORE)

    def test_duplicate_yaml_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.yaml';p.write_text('x: 1\nx: 2\n')
            with self.assertRaises(ValueError):m.read_yaml(p)

    def test_nonfinite_number_rejected(self):
        m.put(self.base,m.C+('general_goal_checker','xy_goal_tolerance'),float('nan'))
        with self.assertRaises(ValueError):m.prepare(self.base,self.map)

    def test_cli_acknowledgements_and_new_file_only(self):
        with tempfile.TemporaryDirectory() as d:
            b=Path(d)/'base.yaml';o=Path(d)/'sim.yaml'
            b.write_text(yaml.safe_dump(self.base));h=hashlib.sha256(b.read_bytes()).hexdigest()
            cmd=[sys.executable,str(ROOT/'scripts/prepare_sim_params.py'),'--base',str(b),'--output',str(o)]
            dry=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(dry.returncode,0,dry.stderr);self.assertFalse(o.exists())
            denied=subprocess.run(cmd+['--write'],capture_output=True,text=True)
            self.assertNotEqual(denied.returncode,0);self.assertFalse(o.exists())
            ok=cmd+['--write','--ack-simulation-only','--ack-footprint-reviewed']
            saved=subprocess.run(ok,capture_output=True,text=True)
            self.assertEqual(saved.returncode,0,saved.stderr);self.assertTrue(o.exists())
            self.assertTrue(o.with_suffix('.review.json').exists())
            again=subprocess.run(ok,capture_output=True,text=True)
            self.assertNotEqual(again.returncode,0)
            self.assertEqual(hashlib.sha256(b.read_bytes()).hexdigest(),h)

    def test_rpp_write_requires_lookahead_ack(self):
        with tempfile.TemporaryDirectory() as d:
            b=Path(d)/'base.yaml';o=Path(d)/'sim.yaml';b.write_text(yaml.safe_dump(self.base))
            cmd=[sys.executable,str(ROOT/'scripts/prepare_sim_params.py'),'--base',str(b),
                 '--output',str(o),'--write','--rpp-trial','--ack-simulation-only','--ack-footprint-reviewed']
            p=subprocess.run(cmd,capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0);self.assertFalse(o.exists())

    def test_progress_write_requires_progress_ack(self):
        with tempfile.TemporaryDirectory() as d:
            b=Path(d)/'base.yaml';o=Path(d)/'sim.yaml';b.write_text(yaml.safe_dump(self.base))
            cmd=[sys.executable,str(ROOT/'scripts/prepare_sim_params.py'),'--base',str(b),
                 '--output',str(o),'--write','--progress-trial','--ack-simulation-only','--ack-footprint-reviewed']
            p=subprocess.run(cmd,capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0);self.assertFalse(o.exists())

if __name__=='__main__':
    unittest.main()
