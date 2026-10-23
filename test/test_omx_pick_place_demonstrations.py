"""Actual-camera world derivation and bounded commands preserve source geometry."""
from pathlib import Path
import hashlib
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'deploy/robot/omx'))


def test_camera_world_preserves_every_original_model_and_plugin(tmp_path):
    from sim_pick_place_demonstrations import camera_world
    source = ROOT / 'integrations/simulation/gazebo/worlds/omx_cell_workcell_sim_aid.sdf'
    camera = ROOT / 'integrations/simulation/gazebo/worlds/omx_pilot_workcell.sdf'
    original = source.read_bytes()
    output = tmp_path / 'camera-world.sdf'
    receipt = camera_world(source, camera, output)
    before = ET.fromstring(original).find('world')
    after = ET.parse(output).getroot().find('world')
    assert after.attrib == before.attrib
    assert [ET.tostring(node) for node in list(after)[:len(before)]] == [ET.tostring(node) for node in before]
    assert len(after.findall("model[@name='workcell_camera']")) == 1
    sensor = after.find("model[@name='workcell_camera']/link/sensor")
    assert sensor.findtext('topic') == '/workcell_camera/image'
    assert sensor.findtext('camera/image/width') == '320'
    assert sensor.findtext('camera/image/height') == '240'
    assert receipt['derived_sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert source.read_bytes() == original
    with pytest.raises(FileExistsError):
        camera_world(source, camera, output)


def test_short_targets_keep_every_planned_waypoint_without_enlarging_steps():
    from sim_pick_place_demonstrations import short_targets
    points = [(0., 0.), (0.07, 0.), (0.07, 0.07), (0.03, 0.07)]
    targets = short_targets(points)
    assert targets[-1] == points[-1]
    assert points[1] in targets and points[2] in targets
    assert all(max(abs(b-a) for a,b in zip(left,right)) <= 0.035 + 1e-12
               for left,right in zip([points[0]] + targets[:-1], targets))


def test_teacher_waypoints_leave_margin_for_the_bounded_action_head():
    from sim_pick_place_demonstrations import short_targets
    points=[(0.,0.),(.07,.04)]
    targets=short_targets(points)
    assert targets[-1]==points[-1]
    assert all(max(abs(b-a) for a,b in zip(left,right))<=.03+1e-12
               for left,right in zip([points[0]]+targets[:-1],targets))


def test_teacher_readback_does_not_record_a_gripper_target_the_head_cannot_reach():
    from sim_pick_place_demonstrations import readback_target
    current={'gripper':.4199}
    desired={'gripper':.3809}
    target=readback_target(current,desired)
    assert target!=desired
    assert 0<current['gripper']-target['gripper']<=.03+1e-12


def test_contact_squeeze_leaves_source_readback_margin_below_the_model_bound():
    from sim_pick_place_teacher import contact_hold_target
    current=.4199
    target=contact_hold_target(current,close=.3804,contact=.4072)
    assert 0<current-target<=.03+1e-12


def test_teacher_readback_accepts_contact_pressure_within_head_support():
    from sim_pick_place_demonstrations import readback_target
    desired={'gripper':.385}
    assert readback_target({'gripper':.416},desired)==desired


@pytest.mark.parametrize('position,expected',[(1.,False),(.416,True)])
def test_teacher_grasp_stops_closing_on_verified_contact_not_the_blocked_close_target(position,expected):
    from sim_pick_place_teacher import grasp_contact_reached
    assert grasp_contact_reached({'arm':.2,'gripper':position},
        {'arm':.2,'gripper':.38},gripper='gripper',close=.3804,contact=.4072,
        arm_tolerance=.02) is expected


@pytest.mark.parametrize('position',[.1,float('nan')])
def test_grasp_contact_cannot_hide_an_unreached_or_invalid_arm_waypoint(position):
    from sim_pick_place_teacher import grasp_contact_reached
    with pytest.raises(RuntimeError,match='arm'):
        grasp_contact_reached({'arm':position,'gripper':.416},
            {'arm':.2,'gripper':.38},gripper='gripper',close=.3804,contact=.4072,
            arm_tolerance=.02)


def test_teacher_place_pose_adds_clearance_without_changing_the_task_goal():
    from dataclasses import dataclass
    from sim_pick_place_teacher import teacher_place_pose
    @dataclass(frozen=True)
    class Pose:
        x: float
        y: float
        z: float
        yaw: float
    goal=Pose(.2075,.0725,.025,.3)
    planned=teacher_place_pose(goal)
    assert (planned.x,planned.y,planned.yaw)==(.2075,.0725,.3)
    assert planned.z==pytest.approx(.030)
    assert goal.z==.025


@pytest.mark.parametrize('roll,pitch',[(0.,0.),(.2,.3),(0.,1.5707963267948966)])
def test_release_clearance_uses_measured_rotated_object_bottom(roll,pitch):
    import math
    from types import SimpleNamespace as NS
    from sim_pick_place_teacher import release_clearance_evidence
    pose=dict(x_m=.2075,y_m=.0725,z_m=.05,roll_rad=roll,pitch_rad=pitch,yaw_rad=.4)
    observation=dict(model_pose_base=pose,observation_id='actual-observation',clock=25.)
    tcp=NS(x=.2074,y=.0726,z=.0501)
    box=NS(length=.04,width=.03,height=.03)
    evidence=release_clearance_evidence(observation,tcp,box,(.2075,.0725,.025))
    half_height=(abs(math.sin(pitch))*.04+abs(math.cos(pitch)*math.sin(roll))*.03
                 +abs(math.cos(pitch)*math.cos(roll))*.03)/2
    assert evidence['object_bottom_z_m']==pytest.approx(.05-half_height)
    assert evidence['support_surface_z_m']==pytest.approx(.01)
    assert evidence['clearance_m']==pytest.approx(.05-half_height-.01)
    assert evidence['observation'] is observation
    assert evidence['tcp_m']==dict(x=tcp.x,y=tcp.y,z=tcp.z)


@pytest.mark.parametrize('height',[.025,.0274,float('nan')])
def test_teacher_refuses_detach_without_measured_clearance(height):
    from types import SimpleNamespace as NS
    from sim_pick_place_teacher import release_clearance_evidence
    observation=dict(model_pose_base=dict(z_m=height,roll_rad=0.,pitch_rad=0.))
    with pytest.raises(RuntimeError,match='measured_release_clearance'):
        release_clearance_evidence(observation,NS(x=0.,y=0.,z=.03),
            NS(length=.04,width=.03,height=.03),(0.,0.,.025))


@pytest.mark.parametrize('fault',[None,'stale','future','contact','observer'])
def test_release_branch_detaches_only_after_fresh_measured_clearance(fault):
    import ast
    from types import SimpleNamespace as NS
    from sim_pick_place_teacher import release_clearance_evidence
    source=ROOT/'deploy/robot/omx/sim_pick_place_teacher.py'
    branch=next(n for n in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
        if isinstance(n,ast.If) and ast.unparse(n.test)=="phase.phase_id == 'release'"
        and any(isinstance(c,ast.Constant) and c.value=='pre_detach_geometry' for c in ast.walk(n)))
    observation=dict(model_pose_base=dict(z_m=.025 if fault=='contact' else .03,
                                          roll_rad=0.,pitch_rad=0.))
    def observe():
        if fault=='observer':raise RuntimeError('independent observation stale')
        return observation
    detaches=[]
    def detach(model):
        detaches.append(model)
        return dict(confirmed=True)
    names=[f'joint{i}' for i in range(1,6)]
    received=9. if fault=='stale' else 10.2 if fault=='future' else 10.
    state=NS(positions=dict.fromkeys(names,0.),sequence=12,received_at=received)
    event={}
    namespace=dict(phase=NS(phase_id='release'),event=event,observe=observe,
        arm=NS(latest_joint_state=state,monotonic=lambda:10.1),profile=NS(max_joint_state_age_s=.5),
        kin=NS(fk=lambda _:NS(x=0.,y=0.,z=.03)),ARM_JOINTS=names,
        recipe=NS(box=NS(length=.04,width=.03,height=.03)),goal=(0.,0.,.025),
        aid=NS(detach=detach),release_clearance_evidence=release_clearance_evidence)
    code=compile(ast.Module(body=[branch],type_ignores=[]),str(source),'exec')
    if fault is not None:
        with pytest.raises(RuntimeError):exec(code,namespace)
        assert detaches==[]
    else:
        exec(code,namespace)
        assert detaches==['infeed_block']
        evidence=event['pre_detach_geometry']
        assert evidence['observation'] is observation
        assert evidence['joint_state']==dict(positions=state.positions,sequence=12,
                                             received_at=10.,checked_owner_s=10.1)


def test_measured_tracking_error_gets_a_bounded_intermediate_without_losing_the_waypoint():
    from sim_pick_place_demonstrations import readback_target
    current={'joint3':.22406642138957977,'gripper_joint_1':.41159433126449585}
    desired={'joint3':.18370857317041256,'gripper_joint_1':.38042608841813563}
    intermediate=readback_target(current,desired)
    assert intermediate != desired
    assert max(abs(intermediate[n]-current[n]) for n in current) == pytest.approx(.03)
    assert all(min(current[n],desired[n]) <= intermediate[n] <= max(current[n],desired[n]) for n in current)
    arrived=dict(intermediate,joint3=intermediate['joint3']+.007,
                 gripper_joint_1=current['gripper_joint_1'])
    corrected=readback_target(arrived,desired)
    assert max(abs(corrected[n]-arrived[n]) for n in arrived)<=.03+1e-12
    assert corrected['gripper_joint_1']<arrived['gripper_joint_1']
    assert desired['joint3']==.18370857317041256


def test_contact_readback_keeps_the_exact_goal_after_supported_intermediates():
    from sim_pick_place_demonstrations import dispatch_readback_target
    current={'gripper':.42}
    commands=[]
    def send(target):
        commands.append(target)
        current.update(target)
    dispatch_readback_target({'gripper':.38},lambda:dict(current),send)
    assert len(commands)==2 and commands[-1]=={'gripper':.38}
    assert commands[0]['gripper']==pytest.approx(.39)


@pytest.mark.parametrize('position',[.405,.4212312996])
def test_teacher_transfer_hold_keeps_bounded_nonzero_contact_squeeze(position):
    from sim_pick_place_teacher import contact_hold_target
    close,contact=.3804260884,.4072
    target=contact_hold_target(position,close=close,contact=contact)
    assert target==max(close,position-.03)
    assert close<=target<position and position-target<=.03+1e-12


@pytest.mark.parametrize('position',[.38,.423,1.,float('nan')])
def test_teacher_transfer_hold_refuses_lost_or_nonfinite_contact(position):
    from sim_pick_place_teacher import contact_hold_target
    with pytest.raises((ValueError,RuntimeError)):
        contact_hold_target(position,close=.3804260884,contact=.4072)


@pytest.mark.parametrize('holding',[False,True])
def test_teacher_dispatch_records_contact_hold_only_when_requested(holding):
    import ast
    from types import SimpleNamespace as NS
    import sim_pick_place_teacher as teacher
    from sim_pick_place_demonstrations import dispatch_readback_target
    source=ROOT/'deploy/robot/omx/sim_pick_place_teacher.py'
    function=next(n for n in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
                  if isinstance(n,ast.FunctionDef) and n.name=='dispatch')
    desired={'joint1':1.46546,'gripper_joint_1':.3804260884}
    actual={'joint1':1.4883,'gripper_joint_1':.4212312996}
    evidence={'position_rad':actual['gripper_joint_1'],'receipt':{'sequence':12}}
    sent=[];checks=[];event={}
    def grip(expect):
        checks.append(expect)
        return evidence,actual['gripper_joint_1']
    namespace=dict(wait_ready=lambda:{'positions':actual},dispatch_once=sent.append,
        dispatch_readback_target=dispatch_readback_target,grip=grip,event=event,
        contact_hold_target=getattr(teacher,'contact_hold_target',None),
        profile=NS(gripper_joint='gripper_joint_1',gripper_close_for_width=lambda _: .3804260884,
                   gripper_contact_for_width=lambda _: .4072),recipe=NS(box=NS(width=.03)))
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),namespace)
    if holding:
        namespace['dispatch'](desired,holding=True)
        assert len(sent)==1 and sent[0]['joint1']==desired['joint1']
        assert sent[0]['gripper_joint_1']==pytest.approx(.3912312996)
        assert max(abs(sent[0][n]-actual[n]) for n in actual)<=.04
        assert event['hold_commands'][0]['evidence'] is evidence and checks==['held']
        assert event['hold_commands'][0]['target']==sent[0]
        assert desired['gripper_joint_1']==.3804260884
    else:
        with pytest.raises(RuntimeError,match='no_progress'):namespace['dispatch'](desired)
        assert checks==[] and event=={}


def test_readback_correction_stops_when_actual_motion_makes_no_progress():
    from sim_pick_place_demonstrations import dispatch_readback_target
    commands=[]
    with pytest.raises(RuntimeError,match='no_progress'):
        dispatch_readback_target({'joint':.1},lambda:{'joint':0.},commands.append)
    assert commands==[{'joint':.03}]


def test_readback_correction_never_retries_an_unknown_transport_outcome():
    from sim_pick_place_demonstrations import dispatch_readback_target
    commands=[]
    def send(target):
        commands.append(target)
        raise RuntimeError('actual goal outcome unknown')
    with pytest.raises(RuntimeError,match='outcome unknown'):
        dispatch_readback_target({'joint':.1},lambda:{'joint':0.},send)
    assert commands==[{'joint':.03}]


@pytest.mark.parametrize('points', [[], [(0.,), (float('nan'),)], [(0.,), (0., 1.)]])
def test_malformed_trajectory_is_rejected(points):
    from sim_pick_place_demonstrations import short_targets
    with pytest.raises(ValueError):
        short_targets(points)


def test_demonstrations_use_the_same_protected_native_entry_and_output_scope():
    from native_sim_prepare import run_script
    script = run_script('/candidate', experiment='pick-place-demonstrations')
    assert '/candidate/deploy/robot/omx/sim_pick_place_demonstrations.py' in script
    assert '$OMX_NATIVE_STATE/pick-place' in script
    assert '--approve-isolated-simulation --approve-startup-home' in script


@pytest.mark.parametrize('script',['sim_pick_place_teacher.py','sim_pick_place_policy.py'])
def test_simulation_actor_is_detected_as_a_second_owner(tmp_path,script):
    from cell_sim_tools import refuse_second_owner
    process = tmp_path / '4001'
    process.mkdir()
    (process / 'cmdline').write_bytes(('python3\0/deploy/robot/omx/'+script+'\0').encode())
    (process / 'environ').write_bytes(b'ROSY_OMX_ROS_NAMESPACE=/omx_01\0')
    with pytest.raises(RuntimeError, match='4001'):
        refuse_second_owner(proc_root=tmp_path, namespace='/omx_01')
    refuse_second_owner(proc_root=tmp_path, namespace='/omx_02')


def test_teacher_delivers_each_owner_event_once_to_the_existing_facade():
    import ast
    from types import SimpleNamespace
    source = ROOT / 'deploy/robot/omx/sim_pick_place_teacher.py'
    callback = next(node for node in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
                    if isinstance(node, ast.FunctionDef) and node.name == 'on_event')
    delivered = []
    capture = SimpleNamespace(on_goal_event=delivered.append)
    facade = SimpleNamespace(capture=capture, on_goal_event=capture.on_goal_event)
    namespace = {'facade': facade}
    exec(compile(ast.Module(body=[callback], type_ignores=[]), str(source), 'exec'), namespace)
    event = object()
    namespace['on_event'](event)
    assert delivered == [event]


def test_native_demo_batch_is_explicit_bounded_and_does_not_change_default_g2():
    from native_sim_prepare import run_script
    script = run_script('/candidate', experiment='pick-place-demonstrations', episodes=3)
    assert '--episodes 3' in script
    for experiment, count in [('g2', 2), ('pick-place', 2), ('pick-place-demonstrations', 4),
                              ('pick-place-demonstrations', True)]:
        with pytest.raises(ValueError):
            run_script('/candidate', experiment=experiment, episodes=count)


def test_batch_preserves_failed_attempt_and_stops_before_the_next_episode(tmp_path, monkeypatch):
    import json
    import sim_pick_place_demonstrations as demo
    calls = []
    def episode(path):
        calls.append(path.name)
        path.mkdir()
        success = len(calls) == 1
        (path/'result.json').write_text(json.dumps({'attempts': 1, 'successes': int(success),
            'cleanup_verified': True, 'result': 'PASS' if success else 'HOLD'}))
        return 0 if success else 1
    monkeypatch.setattr(demo, 'episode', episode)
    output = tmp_path/'batch'
    assert demo.run(output, episodes=3) == 1
    result = json.loads((output/'result.json').read_text())
    assert calls == ['episode-1', 'episode-2']
    assert result['attempts'] == 2 and result['successes'] == 1
    assert len(result['episodes']) == 2


def test_gripper_evidence_keeps_raw_observation_and_its_actual_owner_clock_check():
    import ast
    from types import SimpleNamespace as NS
    sys.path.insert(0, str(ROOT/'middleware/devices/omx/adapter'))
    from omx_adapter.gripper_contract import (
        GripperObservation, GripperReadbackError, verify_held_object, verify_released_object)
    from sim_policy_trial_evidence import contact_held
    source = ROOT/'deploy/robot/omx/sim_pick_place_teacher.py'
    function = next(node for node in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
                    if isinstance(node, ast.FunctionDef) and node.name == 'grip')
    arm = NS(latest_joint_state=NS(positions={'gripper_joint_1': .42}, sequence=12, received_at=20.),
             monotonic=lambda: 20.1)
    namespace = dict(arm=arm, profile=NS(gripper_joint='gripper_joint_1', gripper_open=1.,
        gripper_close_for_width=lambda _: .38, gripper_contact_for_width=lambda _: .42,
        max_joint_state_age_s=.5), recipe=NS(box=NS(width=.03)),
        config=NS(workcell_id='omx_cell_sim', instance_id='omx_cell_sim_01'),
        GripperObservation=GripperObservation, verify_held_object=verify_held_object,
        verify_released_object=verify_released_object,contact_held=contact_held)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    evidence,position = namespace['grip']('held')
    assert evidence['observation']['received_at'] == 20.
    assert evidence['checked_owner_s'] == 20.1 and evidence['max_age_s'] == .5
    assert evidence['receipt']['sequence'] == evidence['observation']['sequence'] == 12
    assert evidence['observation']['object_present'] is True
    sys.path.insert(0,str(ROOT/'contracts/learning/src'))
    from rosy.contracts.learning.sim_object_truth import _gripper_evidence
    identity=_gripper_evidence(dict(hold_evidence=evidence,hold_receipt=evidence['receipt'],
        started_owner_s=19.,ended_owner_s=21.),'hold')
    assert identity==('omx_cell_sim','omx_cell_sim_01','omx-sim-width-matched-position-v2',1)
    assert position==.42
    arm.monotonic = lambda: 20.6
    with pytest.raises(GripperReadbackError, match='stale'):
        namespace['grip']('held')
