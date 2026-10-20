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


def test_measured_tracking_error_gets_a_bounded_intermediate_without_losing_the_waypoint():
    from sim_pick_place_demonstrations import readback_target
    current={'joint3':.22406642138957977,'gripper_joint_1':.41159433126449585}
    desired={'joint3':.18370857317041256,'gripper_joint_1':.38042608841813563}
    intermediate=readback_target(current,desired)
    assert intermediate != desired
    assert max(abs(intermediate[n]-current[n]) for n in current) == pytest.approx(.035)
    assert all(min(current[n],desired[n]) <= intermediate[n] <= max(current[n],desired[n]) for n in current)
    arrived=dict(intermediate,joint3=intermediate['joint3']+.007,
                 gripper_joint_1=current['gripper_joint_1'])
    assert readback_target(arrived,desired)==desired
    assert desired['joint3']==.18370857317041256


def test_contact_readback_within_original_admission_bound_keeps_the_exact_goal():
    from sim_pick_place_demonstrations import readback_target
    assert readback_target({'gripper':.42},{'gripper':.38})=={'gripper':.38}


def test_readback_correction_stops_when_actual_motion_makes_no_progress():
    from sim_pick_place_demonstrations import dispatch_readback_target
    commands=[]
    with pytest.raises(RuntimeError,match='no_progress'):
        dispatch_readback_target({'joint':.1},lambda:{'joint':0.},commands.append)
    assert commands==[{'joint':.035}]


def test_readback_correction_never_retries_an_unknown_transport_outcome():
    from sim_pick_place_demonstrations import dispatch_readback_target
    commands=[]
    def send(target):
        commands.append(target)
        raise RuntimeError('actual goal outcome unknown')
    with pytest.raises(RuntimeError,match='outcome unknown'):
        dispatch_readback_target({'joint':.1},lambda:{'joint':0.},send)
    assert commands==[{'joint':.035}]


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
        verify_released_object=verify_released_object)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    evidence = namespace['grip']('held')
    assert evidence['observation']['received_at'] == 20.
    assert evidence['checked_owner_s'] == 20.1 and evidence['max_age_s'] == .5
    assert evidence['receipt']['sequence'] == evidence['observation']['sequence'] == 12
    assert evidence['observation']['object_present'] is True
    arm.monotonic = lambda: 20.6
    with pytest.raises(GripperReadbackError, match='stale'):
        namespace['grip']('held')
