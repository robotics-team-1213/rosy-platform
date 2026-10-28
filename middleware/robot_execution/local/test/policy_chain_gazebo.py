"""remote_sim-only fixed SIM policy: actual Fleet/auth, SDK, CORE, camera and Gazebo.

No learned checkpoint, Mission admission or physical-device qualification.
"""
from contextlib import ExitStack, contextmanager, closing
from collections import deque
from dataclasses import asdict
import base64
import hashlib
import json
import os
from pathlib import Path
import select
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import uvicorn
from types import SimpleNamespace
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'middleware/devices/omx/adapter'), str(ROOT/'contracts/foundation'),
    str(ROOT/'middleware/robot_execution/local/src'), str(ROOT/'contracts/learning/src'),
    str(ROOT/'contracts/skill/src'), str(ROOT/'operations/fleet'),
    *[str(ROOT/'middleware/core'/part) for part in ('api','gateway','services','events')]]

import rclpy
from omx_adapter.ros_owner_executor import OwnerMultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from controller_manager_msgs.srv import ListControllers
from core_api_web.api.app import create_app
from omx_adapter.action_store import ActionStore
from omx_adapter.command_owner import ArmCommandConfig
from omx_adapter.local_stop import LocalStopController
from omx_adapter.ros_runtime import RosArmCommandRuntime
from rosy.contracts.learning import seal
from rosy.contracts.skill import AttemptIdentity
from rosy.execution.local.omx_policy import CameraSnapshot, owner_binding
from rosy.execution.local.policy_install import InstallBinding, load_policy
from rosy.execution.local.policy_journal import PolicyExecutionJournal
from rosy.execution.local.policy_lease import FleetLeaseConsumer, LeaseScope
from rosy.execution.local.policy_chain import SimPolicyChain
from policy_chain_fixtures import approved_fleet, HttpServer

SHAPE = (3, 24, 32)
TIMING = dict(period_ns=1_000_000_000, max_observation_age_ns=500_000_000, max_action_age_ns=500_000_000)
SDK = r'''
import hashlib, json, sys
from lerobot_robot_rosy_omx import RosyOmx, RosyOmxConfig
def emit(value): print('CHAIN_SDK='+json.dumps(value), flush=True)
emit({'ready':True, 'ros_imported':'rclpy' in sys.modules})
settings=json.loads(sys.stdin.readline())
robot=RosyOmx(RosyOmxConfig(**settings))
robot.connect()
emit({'connected':robot.is_connected})
for line in sys.stdin:
    operation=json.loads(line)
    if operation['op']=='step':
        obs=robot.get_observation()
        target=obs['joint1.pos']+.01
        robot.send_action({'joint1.pos':target})
        emit({'target_rad':target, 'observed_rad':obs['joint1.pos'],
              'rgb_sha256':hashlib.sha256(obs['front'].tobytes()).hexdigest(),
              'rgb_bytes':obs['front'].nbytes, 'ros_imported':'rclpy' in sys.modules})
    elif operation['op']=='reconnect':
        robot.disconnect()
        try: robot.connect()
        except Exception as error:
            emit({'reconnect_refused':True,'error_type':type(error).__name__})
        else: raise AssertionError('closed session reopened')
        break
'''


def until(check, seconds, label):
    deadline = time.monotonic()+seconds
    while not check():
        assert time.monotonic() < deadline, label
        time.sleep(.01)


@contextmanager
def process(args, out, name, **kwargs):
    with (out/(name+'.stderr')).open('wb') as errors:
        child = subprocess.Popen(args, stderr=errors, start_new_session=True, **kwargs)
        try:
            yield child
        finally:
            for sig, timeout in ((signal.SIGINT,5),(signal.SIGTERM,3),(signal.SIGKILL,2)):
                if child.poll() is not None:
                    break
                try:
                    os.killpg(child.pid, sig)  # Only the process group created above.
                    child.wait(timeout)
                except ProcessLookupError:
                    break
                except subprocess.TimeoutExpired:
                    continue
            assert child.poll() is not None, 'own child process did not exit'


def sdk_message(child):
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        assert select.select([child.stdout], [], [], max(0, deadline-time.monotonic()))[0], 'SDK response deadline'
        line = child.stdout.readline()
        assert line, 'SDK exited before response'
        if line.startswith('CHAIN_SDK='):
            return json.loads(line.removeprefix('CHAIN_SDK='))
    raise AssertionError('SDK response deadline')


def sdk_send(child, message):
    child.stdin.write(json.dumps(message)+'\n')
    child.stdin.flush()


class Camera:
    def __init__(self, node, monotonic, calibration, *, name='front', identity='sim-workcell-camera',
                 topic='/workcell_camera/image', shape=None, max_age_ns=None):
        # Defaults keep this probe's single 32x24 camera; policy_chain_vla_gazebo.py passes its own (D-866 P0).
        self.node, self.clock, self.calibration = node, monotonic, calibration
        self.name, self.identity = name, identity
        self.shape = SHAPE if shape is None else tuple(shape)
        self.max_age_ns = TIMING['max_observation_age_ns'] if max_age_ns is None else max_age_ns
        self._lock, self._latest, self._stamp = threading.Lock(), None, -1
        self.accepted, self.rejected, self.captures = 0, 0, []
        self.subscription = node.create_subscription(Image, topic, self.receive, qos_profile_sensor_data)

    def receive(self, message):
        stamp = message.header.stamp.sec*1_000_000_000+message.header.stamp.nanosec
        received_at_ns = int(self.clock()*1e9)
        now = self.node.get_clock().now().nanoseconds
        raw = bytes(message.data)
        with self._lock:
            shape, age = self.shape, self.max_age_ns
            if (message.encoding != 'rgb8' or (message.height,message.width) != shape[1:]
                    or message.step != shape[2]*3 or len(raw) != shape[1]*shape[2]*3
                    or stamp <= self._stamp or not 0 <= now-stamp <= age
                    or not 0 <= int(self.clock()*1e9)-received_at_ns+now-stamp <= age):
                self.rejected += 1
                return
            camera = CameraSnapshot(self.name,self.identity,self.calibration,shape,
                received_at_ns-(now-stamp),hashlib.sha256(raw).hexdigest())
            self._latest, self._stamp = (raw,camera), stamp
            self.accepted += 1

    @contextmanager
    def capture(self):
        with self._lock:
            if self._latest is None:
                raise PermissionError('no original Gazebo camera frame')
            raw, camera = self._latest
            self.captures.append(dict(frame_sha256=camera.frame_sha256, received_at_ns=camera.received_at_ns,
                                      source_stamp_ns=self._stamp, shape=self.shape))
            yield raw, camera

    def current(self):
        # A watchdog holding the session lock must not wait for the capture lock.
        latest = self._latest
        return () if latest is None else (latest[1],)


def installation(out, runtime, calibration):
    root = out/'fixed-sim-policy'
    root.mkdir()
    blob = b'SIM fixed +0.01 rad proposals; NOT trained weights or model evaluation'
    (root/'fixture.txt').write_bytes(blob)
    ref = dict(path='fixture.txt', bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest())
    owner = owner_binding(runtime.owner)
    cameras = [dict(name='front',identity='sim-workcell-camera',calibration_sha256=calibration,
                   source_shape=list(SHAPE),model_shape=list(SHAPE),color='rgb',scale=1/255)]
    declared = dict(profile='omx_joint_target_v1',robot_type='omx_sim_ros',environment='sim',
        device_profile_revision='sim-omx-chain-1',camera_profile_revision='sim-camera-32x24')
    doc = seal(dict(schema='rosy.policy-artifact/1', **declared, files=[ref], normalization=ref,
        evaluations=[ref], joint_names=['joint1'], cameras=cameras, owner=owner,
        observation=dict(names=['joint1'],units=['rad'],shape=[1]),
        action=dict(names=['joint1'],units=['rad'],semantics='absolute_joint_position_target_rad',limits=[[-.1,.1]]),
        timing=TIMING, failure_mode='hold', reset_events=['stop','hold','lease_change','episode_change'],
        dataset_revisions=[ref['sha256']],tool_revision='explicit-fixed-SIM-fixture'))
    (root/'policy-artifact.json').write_text(json.dumps(doc))
    binding = InstallBinding(policy_revision=doc['revision'], **declared, owner=owner, cameras=cameras,
        normalization_sha256=ref['sha256'],action_names=('joint1',),action_limits=((-0.1,0.1),),timing=TIMING)
    return load_policy(root,binding)


def prove(out, runtime, camera, controllers, calibration):
    with ExitStack() as stack:
        python = Path(os.environ.get('ROSY_OMX_LEROBOT_PYTHON',
            str(Path.home()/'rosy-test/venvs/omx-lerobot-0.4.4/bin/python')))
        assert python.is_file(), 'existing dedicated LeRobot 0.4.4 environment required'
        env = dict(os.environ, PYTHONPATH=str(ROOT/'integrations/robots/omx/src'))
        child = stack.enter_context(process([str(python),'-u','-c',SDK],out,'sdk',
            env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True))
        assert sdk_message(child) == dict(ready=True,ros_imported=False)
        future = None
        def ready():
            nonlocal future
            if future is None and controllers.service_is_ready():
                future = controllers.call_async(ListControllers.Request())
            if future is not None and future.done():
                result, future = future.result(), None
                return (any(c.name == 'arm_controller' and c.state == 'active' for c in result.controller)
                    and runtime.action_port.server_is_ready() and runtime.latest_joint_state is not None
                    and camera.accepted >= 2)
            return False
        until(ready,60,'vendor controller, advancing joint state and real camera required')
        assert runtime._node.count_subscribers('/leader/joint_trajectory') == 0
        policy = installation(out,runtime,calibration)
        cfg = runtime.owner.config
        fence_db = out/'stop.sqlite3'
        ActionStore(fence_db)
        fence = LocalStopController(fence_db,workcell_id=cfg.workcell_id,instance_id=cfg.instance_id)
        fence.rearm(authority_epoch=1,dispatch_generation=1,operator_confirmed=True,fleet_fence_current=lambda *_:True)
        identity = AttemptIdentity('sim-local-mission','step','action','attempt',cfg.workcell_id,cfg.instance_id,'a'*64,1,1)
        fleet = stack.enter_context(approved_fleet(out/'fleet', workcell_id=cfg.workcell_id,
            instance_id=cfg.instance_id,policy_revision=policy.recheck()['revision'],
            rig_revision='sim-rig-32x24',calibration_revision=cfg.calibration_revision))
        scope = LeaseScope(identity,'sim-episode',policy.recheck()['revision'],runtime.owner.session_id,
            fleet.window['window_id'],'sim-rig-32x24',cfg.calibration_revision,fleet.scope)
        preparation = {}
        began = runtime.monotonic()
        closed_services = SimpleNamespace(arm_policy=None,safety=SimpleNamespace(estop=False,estop_listeners=[]))
        closed_app = create_app({},closed_services)
        uvicorn.Config(closed_app,log_level='warning',lifespan='off').load()
        preparation['closed_core_preparation_seconds'] = runtime.monotonic()-began
        for label, operation in (
            ('stdlib_process',lambda:subprocess.run([sys.executable,'-I','-S','-c',
                'import json, sys; from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener'],
                timeout=.2,check=True)),
            ('prepared_fleet_state',lambda:fleet.admin('GET',
                '/api/fleet/workcells/'+cfg.workcell_id+'/policy'))):
            began = runtime.monotonic()
            try:
                operation()
            except Exception as error:
                preparation[label+'_error_type'] = type(error).__name__
            preparation[label+'_seconds'] = runtime.monotonic()-began
        (out/'preparation-timing.json').write_text(json.dumps(preparation,indent=2))
        exchanges = []
        def request(method, path, body=None):
            began = runtime.monotonic()
            row = dict(method=method,path=path)
            try:
                value = fleet.device(method,path,body)
                row['times'] = {key:value[key] for key in ('now_ns','issued_ns','expires_ns') if key in value}
                return value
            except Exception as error:
                row['error_type'] = type(error).__name__
                raise
            finally:
                row['elapsed_s'] = runtime.monotonic()-began
                exchanges.append(row)
                (out/'exchanges.json').write_text(json.dumps(exchanges,indent=2))
        consumer = FleetLeaseConsumer(scope,request=request,monotonic=runtime.monotonic)
        journal = PolicyExecutionJournal(out/'execution.sqlite3')
        admission = dict(owner=runtime.owner.recovery_state(), environment=policy.recheck()['environment'],
            camera_count=len(policy.recheck()['cameras']), owner_clock=runtime.owner_clock,
            same_clock=runtime.monotonic is consumer.monotonic, allowed_owners=cfg.allowed_owners,
            policy_matches=policy.recheck()['revision'] == scope.policy_revision,
            owner_matches=scope.owner_session_id == runtime.owner.session_id,
            calibration_matches=scope.calibration_revision == cfg.calibration_revision,
            binding_present=runtime._policy_binding is not None)
        (out/'admission.json').write_text(json.dumps(admission,indent=2))
        print('OMX_POLICY_CHAIN_ADMISSION='+json.dumps(admission),flush=True)
        chain = stack.enter_context(SimPolicyChain(policy=policy,runtime=runtime,fence=fence,consumer=consumer,
            journal=journal,owner_identity=lambda:dict(simulation=True,workcell_id=cfg.workcell_id,
                instance_id=cfg.instance_id,profile='sim-omx-chain-1'),camera_current=camera.current,
            capture=camera.capture,principal='sim-sdk',installed_rig_revision='sim-rig-32x24',enabled=True))
        def remember_session():
            (out/'session-close.json').write_text(json.dumps(dict(hold_reason=chain.session.hold_reason,
                owner=runtime.owner.recovery_state(),camera_accepted=camera.accepted,
                camera_age_ns=int(runtime.monotonic()*1e9)-camera.current()[0].received_at_ns),indent=2))
        stack.callback(remember_session)
        initial_wire = consumer._wire
        credential = secrets.token_urlsafe(32)
        token_file = out/'sdk.private'
        token_file.touch(mode=0o600, exist_ok=False)
        token_file.write_text(credential)
        config = dict(auth=dict(tokens=[dict(id='sim-sdk',role='operator',sha256=hashlib.sha256(credential.encode()).hexdigest())]))
        services = SimpleNamespace(config=config,arm_policy=chain.port,safety=SimpleNamespace(estop=False,estop_listeners=[]))
        began = runtime.monotonic()
        app = create_app(config,services)
        preparation['bound_core_app_seconds'] = runtime.monotonic()-began
        assert chain.port.stop in services.safety.estop_listeners
        commands, observations = [], []
        async def traced(scope, receive, send):
            status = None
            async def delivered(message):
                nonlocal status
                if message['type'] == 'http.response.start':
                    status = message['status']
                if message['type'] == 'http.response.body' and message.get('body'):
                    body = json.loads(message['body'])
                    if status is not None and status >= 400:
                        diagnostic = dict(path=scope.get('path'),status=status,response=body,
                            hold_reason=chain.session.hold_reason, owner=runtime.owner.recovery_state(),
                            camera_accepted=camera.accepted,camera_rejected=camera.rejected,
                            camera_age_ns=int(runtime.monotonic()*1e9)-camera.current()[0].received_at_ns)
                        (out/'core-refusal.json').write_text(json.dumps(diagnostic,indent=2))
                        print('OMX_POLICY_CHAIN_CORE_REFUSAL='+json.dumps(diagnostic),flush=True)
                    if scope.get('path') == '/api/v1/arm/actions' and body.get('accepted') is True:
                        commands.append(body['command_id'])
                    elif scope.get('path') == '/api/v1/arm/observations' and 'observation_id' in body:
                        raw = base64.b64decode(body['camera']['rgb_base64'])
                        observations.append(dict(observation_id=body['observation_id'],
                            rgb_sha256=hashlib.sha256(raw).hexdigest(),source=camera.captures[-1]))
                await send(message)
            await app(scope,receive,delivered)
        began = runtime.monotonic()
        core = stack.enter_context(HttpServer(traced))
        preparation['bound_core_server_start_seconds'] = runtime.monotonic()-began
        (out/'preparation-timing.json').write_text(json.dumps(preparation,indent=2))
        sdk_send(child,dict(url=core.url,token_file=str(token_file),policy_revision=scope.policy_revision,
            joint_names=['joint1'],camera_height=SHAPE[1],camera_width=SHAPE[2]))
        assert sdk_message(child) == dict(connected=True)
        sdk_send(child,dict(op='step'))
        first = sdk_message(child)
        assert first['ros_imported'] is False and first['rgb_bytes'] == 2304 and len(commands) == 1
        assert first['rgb_sha256'] == observations[-1]['rgb_sha256'] == observations[-1]['source']['frame_sha256']
        until(lambda:any(e['kind']=='TERMINAL_RESULT' for e in journal.read(commands[0])['events']),6,'first terminal')
        assert journal.read(commands[0])['events'][-1]['status'] == 4
        time.sleep(1)
        measured = runtime.latest_joint_state.positions['joint1']
        assert measured-first['observed_rad'] > .007 and abs(measured-first['target_rad']) < .003
        assert consumer._wire[0] > initial_wire[0], 'actual same-lease renewal required during movement'
        with closing(sqlite3.connect(fleet.db)) as db:
            row = db.execute('SELECT lease_id, issued_ns, expires_ns FROM fleet_policy_lease').fetchall()
        assert len(row) == 1 and row[0][0] == chain.session.lease.lease_id and row[0][1] > initial_wire[0]
        sdk_send(child,dict(op='step'))
        second = sdk_message(child)
        assert len(commands) == 2 and second['rgb_sha256'] == observations[-1]['source']['frame_sha256']
        until(lambda:runtime.latest_joint_state.positions['joint1']-second['observed_rad'] > .002,3,'in-motion revoke')
        handle = runtime.action_port.last_handle
        assert not handle.done(), 'revocation must happen during this actual goal'
        fleet.operator('POST',fleet.base+'/windows/'+scope.window_id+'/close',
                       dict(operator_confirmed=True,reason='SIM in-motion revocation'))
        revoked_at = time.monotonic()
        until(lambda:handle.done(),3,'exact owned goal cancel terminal')
        cancelled_at = time.monotonic()
        assert handle.status == 5 and handle.cancel_acknowledged is True
        assert chain.session.hold_reason and runtime.owner.state == 'hold'
        record = journal.read(commands[1])
        assert sum(e['kind']=='TERMINAL_RESULT' for e in record['events']) == 1
        assert record['events'][-1]['status'] == 5
        samples, deadline = [], time.monotonic()+1
        while time.monotonic() < deadline:
            state = runtime.latest_joint_state
            if not samples or samples[-1][0] != state.sequence:
                samples.append((state.sequence,state.positions['joint1'],time.monotonic(),state.received_at))
            time.sleep(.01)
        window = [p for _,p,t,_ in samples if t >= deadline-.3]
        (out/'stop-readback.json').write_text(json.dumps(dict(samples=samples,deadline_s=deadline,
            window_count=len(window),spread_rad=max(window)-min(window) if window else None,
            first_sdk=first,first_readback_rad=measured,second_sdk=second,
            first_command_id=commands[0],cancel_command_id=commands[1],cancel_goal_id=record['driver_goal_id'],
            cancel_status=handle.status,cancel_ack=handle.cancel_acknowledged,
            cancellation_observed_after_revoke_s=cancelled_at-revoked_at,
            owner=runtime.owner.recovery_state()),indent=2))
        assert len(window) >= 3 and max(window)-min(window) < .001
        sdk_send(child,dict(op='reconnect'))
        reconnect = sdk_message(child)
        assert reconnect['reconnect_refused'] is True
        assert not fence.is_open(authority_epoch=1,dispatch_generation=1)
        proof = dict(scope='fixed SIM episode; no learned model, Mission admission or physical motion',
            policy_revision=scope.policy_revision,window_id=scope.window_id,lease=asdict(chain.session.lease),
            server_delivery_marker='not_connected',device_received=True,actual_auth=True,
            initial_fleet_issued_ns=initial_wire[0],renewed_fleet_issued_ns=row[0][1],
            camera_topic='/workcell_camera/image',camera_accepted=camera.accepted,camera_rejected=camera.rejected,
            observations=observations,first_sdk=first,first_readback_rad=measured,
            first_goal=journal.read(commands[0])['driver_goal_id'],cancel_command_id=commands[1],
            cancel_goal_id=record['driver_goal_id'],cancel_status=handle.status,cancel_ack=handle.cancel_acknowledged,
            cancellation_observed_after_revoke_s=cancelled_at-revoked_at,
            owner_state=runtime.owner.state,hold_reason=chain.session.hold_reason,
            final_window_samples=len(window),final_spread_rad=max(window)-min(window),reconnect=reconnect)
        (out/'chain-result.json').write_text(json.dumps(proof,indent=2))
        child.wait(3)
        assert child.returncode == 0
        return proof


def main():
    out = Path(os.environ['OUT']).resolve()
    assert out.is_dir() and os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') == 'LOCALHOST'
    thread_limits = {key:'1' for key in ('LP_NUM_THREADS','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')}
    os.environ.update(thread_limits)
    relative_group = next(line.removeprefix('0::') for line in
                          Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
    cpu_group = Path('/sys/fs/cgroup')/relative_group.lstrip('/')
    (out/'cpu-profile.json').write_text(json.dumps(dict(thread_limits=thread_limits,
        cpu_max=(cpu_group/'cpu.max').read_text(),cpu_before=(cpu_group/'cpu.stat').read_text(),
        started_monotonic_s=time.monotonic()),indent=2))
    original = ROOT/'integrations/simulation/gazebo/worlds/omx_pilot_workcell.sdf'
    world = ET.fromstring(original.read_bytes())
    world.find('./world/physics/max_step_size').text = '0.002'
    image = world.find('.//sensor/camera/image')
    image.find('width').text, image.find('height').text = str(SHAPE[2]), str(SHAPE[1])
    world_file = out/'chain-world.sdf'
    ET.ElementTree(world).write(world_file,encoding='utf-8',xml_declaration=True)
    calibration = hashlib.sha256(world_file.read_bytes()).hexdigest()
    (out/'world-source.json').write_text(json.dumps(dict(
        source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),variant_sha256=calibration,
        camera_shape=SHAPE,physics_step_s=.002,thread_limits=thread_limits,
        scope='explicit low-resolution SIM recording variant')))
    env = dict(os.environ,OMX_CELL_WORLD=str(world_file.with_suffix('')),OMX_CELL_LOG_DIR=str(out),
               OMX_CELL_DOMAIN_ID=os.environ['ROS_DOMAIN_ID'])
    with ExitStack() as stack:
        stack.enter_context(process(['bash','deploy/robot/omx/run_cell_sim.sh'],out,'vendor',env=env))
        stack.enter_context(process(['ros2','run','ros_gz_bridge','parameter_bridge',
            '/workcell_camera/image@sensor_msgs/msg/Image[gz.msgs.Image'],out,'camera-bridge'))
        rclpy.init()
        node = Node('omx_policy_chain_'+uuid4().hex[:8],parameter_overrides=[Parameter('use_sim_time',value=True)])
        cfg = ArmCommandConfig(enabled=True,workcell_id='sim_policy_cell',instance_id='sim_policy_arm',
            joint_names=('joint1',),position_limits={'joint1':(-.1,.1)},allowed_owners=('learned_policy',),
            calibration_revision='sim-cal-'+calibration[:12],velocity_limits={'joint1':.1},
            acceleration_limits={'joint1':1.},max_start_state_tolerances={'joint1':.001},
            max_joint_state_age_s=.5,max_goal_duration_s=1.5,action_timeout_s=4.)
        runtime = RosArmCommandRuntime(node,cfg,poll_period_s=.01,owner_clock='steady')
        intake_trace = deque(maxlen=2000)
        intake = runtime._joint_state_intake
        snapshot = intake.snapshot
        def traced_snapshot(*args,**kwargs):
            entry = dict(callback_s=time.monotonic(),previous_stamp_ns=intake._last_stamp_ns,
                         previous_received_at=intake._last_received_at,**kwargs)
            try:
                value = snapshot(*args,**kwargs)
                entry.update(sequence=value.sequence,adjusted_received_at=value.received_at)
                return value
            except Exception as error:
                entry['rejected'] = str(error)[:200]
                raise
            finally:
                intake_trace.append(entry)
        intake.snapshot = traced_snapshot
        camera = Camera(node,runtime.monotonic,calibration)
        controllers = node.create_client(ListControllers,'/controller_manager/list_controllers')
        # The product owner executor; the stock one starved the lease renewal thread (D-866 P0 lesson,
        # docs/solutions/runtime-errors/stock-rclpy-executor-starves-sim-lease-renewal-2026-10-25.md).
        executor = OwnerMultiThreadedExecutor(num_threads=4)
        executor.add_node(node)
        errors, passed = [], []
        def work():
            try:
                passed.append(prove(out,runtime,camera,controllers,calibration))
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=work,name='sim-policy-chain-probe')
        worker.start()
        try:
            while worker.is_alive():
                executor.spin_once(timeout_sec=.1)  # CORE ROS executor stays on the main thread.
            worker.join()
        finally:
            runtime._timer.cancel()
            stopped = executor.shutdown(timeout_sec=5)
            drained = threading.Event()
            def drain():
                executor._executor.shutdown(wait=True)  # Existing native fixture pattern, pinned Jazzy only.
                drained.set()
            drainer = threading.Thread(target=drain,daemon=True)
            drainer.start()
            workers_stopped = drained.wait(5)
            (out/'teardown.json').write_text(json.dumps(dict(executor_stopped=stopped,
                workers_stopped=workers_stopped, primary_error=repr(errors[0]) if errors else None,
                cpu_after=(cpu_group/'cpu.stat').read_text(),finished_monotonic_s=time.monotonic(),
                remaining_thread_stacks={} if workers_stopped else {
                    str(ident):traceback.format_stack(frame) for ident,frame in sys._current_frames().items()}),indent=2))
            if not (stopped and workers_stopped):  # Do not destroy live entities; keep the probe's failure as the cause.
                raise AssertionError('own executor/workers did not drain') from (errors[0] if errors else None)
            (out/'joint-intake.json').write_text(json.dumps(list(intake_trace),indent=2))
            runtime.destroy()
            node.destroy_node()
            rclpy.try_shutdown()
        if errors:
            raise errors[0]
        # PASS only after a clean teardown and child exit, so a grep for PASS cannot count a failed cleanup.
        print('OMX_POLICY_CHAIN_GAZEBO_PASS='+json.dumps(passed[0]),flush=True)
        print('OMX_POLICY_CHAIN_EXIT_OK',flush=True)


if __name__ == '__main__':
    main()
