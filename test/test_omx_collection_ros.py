"""ROS message binding and independent stop path, without hardware or ROS middleware."""
from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'deploy/robot/omx'))


@pytest.fixture
def inputs():
    module = importlib.import_module('collection_ros_inputs')
    result = module.RosInputs.__new__(module.RosInputs)
    result.profile = dict(joint_names=['j'+str(i) for i in range(6)], normalization=[[-1.,1.]]*6,
                          camera_shapes={r:[1,2,3] for r in ('top','front')},
                          ros=dict(motor_ids=list(range(11,17)), expected_torque=[True]*6))
    result.lock, result.rows, result.fault = threading.RLock(), {}, None
    from collections import OrderedDict
    result.frames = {r:OrderedDict() for r in ('top','front')}
    return result


def header(seconds):
    return NS(stamp=NS(sec=int(seconds), nanosec=int((seconds-int(seconds))*1e9)))


def test_raw_bgr_is_rgb_without_opening_another_camera(inputs):
    message = NS(header=header(time.time()), width=2,height=1,step=8,
                 encoding='bgr8',data=bytes([1,2,3,4,5,6,99,99]))
    inputs.image('top',message)
    assert next(iter(inputs.frames['top'].values()))['data'] == bytes([3,2,1,6,5,4])
    with pytest.raises(ValueError,match='replayed'):
        inputs.image('top',message)


@pytest.mark.parametrize('fault',['order','nonfinite','replay'])
def test_controller_reference_must_be_ordered_finite_and_advancing(inputs,fault):
    msg = NS(header=header(time.time()),joint_names=inputs.profile['joint_names'][:],reference=NS(positions=[0.]*6))
    if fault == 'order': msg.joint_names.reverse()
    if fault == 'nonfinite': msg.reference.positions[2] = float('nan')
    if fault == 'replay': inputs.positions('reference',msg)
    with pytest.raises(ValueError): inputs.positions('reference',msg)


def test_input_snapshot_requires_exact_environment_image_stamp(inputs):
    now = time.time()
    for key in ('joints','reference'):
        inputs.rows[key] = dict(stamp=now,received=time.monotonic(),values=[0.]*6)
    inputs.rows['hardware'] = dict(stamp=now,received=time.monotonic())
    for role in ('top','front'):
        inputs.image(role, NS(header=header(now),width=2,height=1,step=6,encoding='rgb8',data=bytes(6)))
    source = next(iter(inputs.frames['top']))
    env = dict(observations={r:dict(source_stamp=source) for r in ('top','front')})
    assert inputs.snapshot(env)['action'] == [0.,0.,0.,0.,0.,50.]
    env['observations']['top']['source_stamp'] = source-1
    with pytest.raises(KeyError): inputs.snapshot(env)


def test_independent_monitor_requests_hold_without_collection_writer():
    cls = importlib.import_module('collection_ros').RosBackend
    backend = cls.__new__(cls)
    requests=[]
    backend.closed,backend.armed,backend.fault = threading.Event(),True,None
    backend.runtime = NS(owner=NS(preempt=requests.append))
    backend.inputs = NS(verify_publishers=lambda:None)
    backend.verify_processes=lambda:None
    backend.verify_exclusion=lambda:None
    backend.observe=lambda: (_ for _ in ()).throw(ValueError('expired environment'))
    thread=threading.Thread(target=backend.monitor);thread.start();thread.join(timeout=1)
    assert not thread.is_alive() and requests and backend.fault


def test_queue_overflow_revokes_collection_without_waiting_for_storage():
    cls = importlib.import_module('collection_ros').RosBackend
    backend=cls.__new__(cls);backend.events=queue.Queue(maxsize=1);backend.fault=None
    backend.event_lock,backend.facts=threading.Lock(),{}
    @dataclass
    class Event:
        kind:str='fixture'
        command_id:str='fixture-command'
    backend.on_event(Event());backend.on_event(Event())
    assert backend.fault and backend.events.qsize()==1


def test_resource_lock_identity_depends_on_action_and_domain_not_profile_lock_paths():
    module=importlib.import_module('collection_ros')
    assert module.resource_key('/cell/arm/follow_joint_trajectory','42') == module.resource_key(
        '/cell/arm/follow_joint_trajectory','042')
    assert module.resource_key('/cell/arm/follow_joint_trajectory','42') != module.resource_key(
        '/other/arm/follow_joint_trajectory','42')
    with pytest.raises(ValueError): module.resource_key('//cell/arm','42')


def test_expired_acceptance_is_rechecked_by_live_observation():
    module=importlib.import_module('collection_ros')
    from collection_rehearsal import profile,teacher
    from collection_profile import digest
    backend=module.RosBackend.__new__(module.RosBackend)
    backend.profile=profile();backend.profile['enabled']=True;backend.teacher=teacher()
    backend.acceptance=dict(schema='rosy.omx-collection-acceptance.v1',
        profile_sha256=digest(backend.profile),rig_revision=backend.profile['rig_revision'],
        calibration_revision=backend.profile['calibration_revision'],expires_ns=time.time_ns()-1)
    with pytest.raises(ValueError,match='expired'): backend.observe()


def test_rehearsal_cli_exercises_success_and_failures_with_no_hardware(tmp_path):
    result=subprocess.run([sys.executable,str(ROOT/'deploy/robot/omx/collection_cli.py'),
                           'rehearsal-suite','--out',str(tmp_path/'suite')],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report['passed'] and len(report['checks'])==6 and report['real_demonstrations']==0
    assert all(row['hardware_connections']==0 for row in report['checks'])
