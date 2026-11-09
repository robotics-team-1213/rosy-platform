"""ROS message binding and independent stop path, without hardware or ROS middleware."""
from dataclasses import dataclass
import importlib.util
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


def _module(name):
    paths = {'collection_ros': ROOT/'deploy/robot/omx/collection_ros.py',
             'collection_ros_inputs': ROOT/'deploy/robot/omx/collection_ros_inputs.py'}
    spec=importlib.util.spec_from_file_location(name,paths[name])
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def inputs():
    module = _module('collection_ros_inputs')
    result = module.RosInputs.__new__(module.RosInputs)
    result.profile = dict(joint_names=['j'+str(i) for i in range(6)], normalization=[[-1.,1.]]*6,
                          camera_shapes={r:[1,2,3] for r in ('top','front')},
                          ros=dict(motor_ids=list(range(11,17)), expected_torque=[True]*6))
    result.lock, result.rows, result.fault, result.intrinsics = threading.RLock(), {}, None, {}
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
    assert inputs.snapshot(env)['joint_positions'] == [0.]*6
    env['observations']['top']['source_stamp'] = source-1
    with pytest.raises(KeyError): inputs.snapshot(env)


def camera_info(width=2, height=1, k=None):
    return NS(header=NS(frame_id='top_optical'), width=width, height=height, distortion_model='plumb_bob',
              d=[0.]*5, k=k or [1.,0.,1.,0.,1.,.5,0.,0.,1.], r=[1.,0.,0.,0.,1.,0.,0.,0.,1.],
              p=[1.,0.,1.,0.,0.,1.,.5,0.,0.,0.,1.,0.], binning_x=0, binning_y=0)


def test_configured_camera_info_is_required_shape_checked_and_returned(inputs):
    now = time.time()
    inputs.profile['ros']['camera_info_topics'] = {r: f'/{r}/camera_info' for r in ('top','front')}
    for key in ('joints','reference'):
        inputs.rows[key] = dict(stamp=now,received=time.monotonic(),values=[0.]*6)
    inputs.rows['hardware'] = dict(stamp=now,received=time.monotonic())
    for role in ('top','front'):
        inputs.image(role, NS(header=header(now),width=2,height=1,step=6,encoding='rgb8',data=bytes(6)))
    env = dict(observations={r:dict(source_stamp=next(iter(inputs.frames[r]))) for r in ('top','front')})
    with pytest.raises(ValueError, match='camera_info'):
        inputs.snapshot(env)
    with pytest.raises(ValueError, match='layout'):
        inputs.camera_info('top', camera_info(width=4))
    with pytest.raises(ValueError, match='layout'):
        inputs.camera_info('top', camera_info(k=[float('nan')]*9))
    for role in ('top','front'):
        inputs.camera_info(role, camera_info())
    recorded = inputs.snapshot(env)['camera_info']
    assert set(recorded) == {'top','front'} and recorded['top']['k'][2] == 1. and recorded['top']['frame_id'] == 'top_optical'


def test_unconfigured_camera_info_keeps_previous_snapshot_contract(inputs):
    now = time.time()
    for key in ('joints','reference'):
        inputs.rows[key] = dict(stamp=now,received=time.monotonic(),values=[0.]*6)
    inputs.rows['hardware'] = dict(stamp=now,received=time.monotonic())
    for role in ('top','front'):
        inputs.image(role, NS(header=header(now),width=2,height=1,step=6,encoding='rgb8',data=bytes(6)))
    env = dict(observations={r:dict(source_stamp=next(iter(inputs.frames[r]))) for r in ('top','front')})
    assert inputs.snapshot(env)['camera_info'] == {}


def test_independent_monitor_requests_hold_without_collection_writer():
    cls = _module('collection_ros').RosBackend
    backend = cls.__new__(cls)
    requests=[]
    backend.closed,backend.armed,backend.fault = threading.Event(),True,None
    backend.deadline=time.monotonic()+2
    backend.runtime = NS(owner=NS(preempt=requests.append))
    backend.inputs = NS(verify_publishers=lambda:None)
    backend.verify_processes=lambda:None
    backend.verify_exclusion=lambda:None
    backend.observe=lambda: (_ for _ in ()).throw(ValueError('expired environment'))
    thread=threading.Thread(target=backend.monitor);thread.start();thread.join(timeout=1)
    assert not thread.is_alive() and requests and backend.fault


def test_queue_overflow_revokes_collection_without_waiting_for_storage():
    cls = _module('collection_ros').RosBackend
    backend=cls.__new__(cls);backend.events=queue.Queue(maxsize=1);backend.fault=None
    backend.event_lock,backend.facts=threading.Lock(),{}
    @dataclass
    class Event:
        kind:str='fixture'
        command_id:str='fixture-command'
    backend.on_event(Event());backend.on_event(Event())
    assert backend.fault and backend.events.qsize()==1


@pytest.mark.parametrize('extra_client', [None, ('omx_action_events_other', '/cell'),
                                         ('owned_action_events', '/other')])
def test_exclusion_allows_only_the_exact_runtime_owned_action_client(monkeypatch, extra_client):
    from types import ModuleType

    action = '/cell/arm/trajectory'
    owned = ('owned_action_events', '/cell')
    server = ('vendor', '/cell')
    nodes = [('owner', '/cell'), owned, server]
    if extra_client is not None:
        nodes.append(extra_client)
    graph = ModuleType('rclpy.action.graph')
    graph.get_action_client_names_and_types_by_node = lambda node, name, ns: (
        [(action, [])] if (name, ns) != server else [])
    graph.get_action_server_names_and_types_by_node = lambda node, name, ns: (
        [(action, [])] if (name, ns) == server else [])
    for name in ('rclpy', 'rclpy.action'):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.setitem(sys.modules, 'rclpy.action.graph', graph)
    cls = _module('collection_ros').RosBackend
    backend = cls.__new__(cls)
    backend.profile = dict(ros=dict(trajectory_action=action,
                                    action_server=dict(node_name=server[0], node_namespace=server[1])))
    backend.node = NS(get_name=lambda:'owner', get_namespace=lambda:'/cell',
                      get_node_names_and_namespaces=lambda:nodes)
    backend.runtime = NS(action_port=NS(client_node_identity=owned))
    if extra_client is None:
        backend.verify_exclusion()
    else:
        with pytest.raises(ValueError, match='another action owner/client'):
            backend.verify_exclusion()


def test_resource_lock_identity_depends_on_action_and_domain_not_profile_lock_paths():
    module=_module('collection_ros')
    assert module.resource_key('/cell/arm/follow_joint_trajectory','42') == module.resource_key(
        '/cell/arm/follow_joint_trajectory','042')
    assert module.resource_key('/cell/arm/follow_joint_trajectory','42') != module.resource_key(
        '/other/arm/follow_joint_trajectory','42')
    with pytest.raises(ValueError): module.resource_key('//cell/arm','42')


def test_expired_acceptance_is_rechecked_by_live_observation():
    module=_module('collection_ros')
    from collection_rehearsal import profile,teacher
    from collection_profile import digest
    backend=module.RosBackend.__new__(module.RosBackend)
    backend.profile=profile();backend.profile['enabled']=True;backend.teacher=teacher()
    backend.acceptance=dict(schema='rosy.omx-collection-acceptance.v1',
        profile_sha256=digest(backend.profile),rig_revision=backend.profile['rig_revision'],
        calibration_revision=backend.profile['calibration_revision'],expires_ns=time.time_ns()-1)
    with pytest.raises(ValueError,match='expired'): backend.observe()


def test_success_requires_matching_native_current_command_events():
    module=_module('collection_ros')
    backend=module.RosBackend.__new__(module.RosBackend)
    backend.runtime=NS(action_port=NS(last_handle=NS(done=lambda:True,succeeded=lambda:True,status=4)))
    class Owner:
        state='active'
        def poll(self):
            self.state='ready'
            return NS(accepted=True)
    backend.runtime.owner=Owner()
    backend.event_lock,backend.command_id=threading.Lock(),'command'
    backend.facts={'command':{'GOAL_ACCEPTED':dict(goal_id='first'),
                              'TERMINAL_RESULT':dict(goal_id='other',status=4,result_code=0)}}
    with pytest.raises(ValueError,match='evidence'): backend.terminal()
    backend.facts['command']['TERMINAL_RESULT']['goal_id']='first'
    assert backend.terminal()['succeeded'] is True
    assert backend.runtime.owner.state=='ready'


def test_rehearsal_cli_exercises_success_and_failures_with_no_hardware(tmp_path):
    result=subprocess.run([sys.executable,str(ROOT/'deploy/robot/omx/collection_cli.py'),
                           'rehearsal-suite','--out',str(tmp_path/'suite')],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report['passed'] and len(report['checks'])==7 and report['real_demonstrations']==0
    assert all(row['hardware_connections']==0 for row in report['checks'])


# Arm move lock: a move sent through the adapter is a session to the nightly reboot and the host reboot gate.
def _held_elsewhere(root):
    code = ("import fcntl,sys,time;h=open(sys.argv[1]+'/session.lock','a');fcntl.flock(h,fcntl.LOCK_EX);"
            "print('ok',flush=True);time.sleep(30)")
    proc = subprocess.Popen([sys.executable, '-c', code, str(root)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == 'ok'
    return proc


def test_collection_takes_the_cell_session_lock_and_frees_it_on_close(tmp_path, monkeypatch):
    import fcntl
    monkeypatch.setenv('ROSY_OMX_HOME', str(tmp_path / 'omx'))
    monkeypatch.setenv('HOME', str(tmp_path))  # session_lock's busy marker lives under ~/rosy-jobs
    module = _module('collection_ros')
    held = module.acquire_move_lock()
    other = open(tmp_path / 'omx' / 'session.lock', 'a')
    with pytest.raises(BlockingIOError):  # a reboot gate, a session or the updater sees it held
        fcntl.flock(other, fcntl.LOCK_SH | fcntl.LOCK_NB)
    with pytest.raises(ValueError, match='no collection'):  # a second mover is refused, not queued
        module.acquire_move_lock()
    cls = module.RosBackend
    backend = cls.__new__(cls)
    backend.closed, backend.runtime, backend.supervisor, backend.executor = threading.Event(), None, None, None
    backend.thread, backend.node, backend.guard, backend.move_lock = None, None, None, held
    backend.rclpy = NS(ok=lambda: False)
    module.MOVE_SETTLE_S = 0.0
    backend.close()
    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # released by close
    other.close()


def test_collection_refuses_to_move_while_a_session_holds_the_cell(tmp_path, monkeypatch):
    monkeypatch.setenv('ROSY_OMX_HOME', str(tmp_path / 'omx'))
    monkeypatch.setenv('HOME', str(tmp_path))
    (tmp_path / 'omx').mkdir()
    proc = _held_elsewhere(tmp_path / 'omx')
    try:
        with pytest.raises(ValueError, match='no collection'):
            _module('collection_ros').acquire_move_lock()
    finally:
        proc.kill()
        proc.wait()


def test_lock_dies_with_the_process(tmp_path, monkeypatch):
    """A crashed mover must not leave the cell locked (flock on an fd), nor free while it lives."""
    monkeypatch.setenv('ROSY_OMX_HOME', str(tmp_path / 'omx'))
    monkeypatch.setenv('HOME', str(tmp_path))
    (tmp_path / 'omx').mkdir()
    proc = _held_elsewhere(tmp_path / 'omx')
    proc.kill()
    proc.wait()
    _module('collection_ros').acquire_move_lock().close()


def test_the_backend_takes_the_lock_before_anything_can_move():
    source = (ROOT/'deploy/robot/omx/collection_ros.py').read_text(encoding='utf-8')
    init = source.split('def __init__', 1)[1].split('def verify_processes', 1)[0]
    assert init.index('acquire_move_lock()') < init.index('RosArmCommandRuntime(')
    assert init.index('acquire_move_lock()') < init.index('rclpy.init()')


def test_every_hardware_runtime_user_takes_the_move_lock():
    """A new real-arm path built on RosArmCommandRuntime must lock too; sim and no-goal users are listed here."""
    no_arm_moves = {'g2_owner.py', 'probe_cell_transfer.py', 'run_cell_owner.py', 'run_hardware_owner.py',
                    'sim_pick_place_policy.py', 'sim_pick_place_teacher.py'}  # sim, or the owner that refuses goals
    found = {p.name for p in (ROOT/'deploy/robot/omx').glob('*.py')
             if 'RosArmCommandRuntime(' in p.read_text(encoding='utf-8')}
    movers = found - no_arm_moves
    assert movers == {'collection_ros.py'}, f'new RosArmCommandRuntime user needs the arm move lock: {movers}'


def test_exempt_runtime_users_really_cannot_move_hardware_and_direct_movers_stay_children():
    omx = ROOT/'deploy/robot/omx'
    assert 'refuses hardware device grants' in (omx/'run_cell_owner.py').read_text(encoding='utf-8')
    assert 'owner_clock="sim"' in (omx/'g2_owner.py').read_text(encoding='utf-8')
    # bimanual_native has no lock of its own: record_session (which holds session.lock) must stay its only launcher.
    users = {p.name for p in omx.glob('*.py') if p.name != 'bimanual_native.py'
             and 'bimanual_native' in p.read_text(encoding='utf-8')}
    assert users == {'record_session.py'}
    assert 'session_lock(' in (omx/'record_session.py').read_text(encoding='utf-8')
