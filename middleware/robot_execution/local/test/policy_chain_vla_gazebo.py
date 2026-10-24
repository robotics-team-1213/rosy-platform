"""D-866 P0, remote_sim only: a SmolVLA checkpoint through the D-854 runner, CORE HTTP and the OMX owner in Gazebo.

Six joints and two cameras (front, plus a top camera added to the world variant). Motion quality is not judged;
the base model is untrained. The probe proves the execution contract on the VLA path: both frames bound, a
stale action refused, stop and in-motion lease withdrawal ending in HOLD, and reconnects refused.
"""
from collections import deque
from dataclasses import replace
from contextlib import ExitStack, contextmanager, closing
import argparse
import copy
import gc
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import uvicorn
from uuid import uuid4
import xml.etree.ElementTree as ET

import policy_chain_gazebo as base
from policy_chain_gazebo import ROOT, process, until

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from controller_manager_msgs.srv import ListControllers
from core_api_web.api.app import create_app
from omx_adapter.action_store import ActionStore
from omx_adapter.local_stop import LocalStopController
from omx_adapter.pose_plan import CellPlanningProfile
from omx_adapter.ros_runtime import RosArmCommandRuntime
from rosy.contracts.learning import seal
from rosy.contracts.skill import AttemptIdentity
from rosy.execution.local.omx_policy import owner_binding
from rosy.execution.local.policy_install import InstallBinding, load_policy
from rosy.execution.local.policy_journal import PolicyExecutionJournal
from rosy.execution.local.policy_lease import FleetLeaseConsumer, LeaseScope
from rosy.execution.local.policy_chain import SimPolicyChain
from policy_chain_fixtures import approved_fleet, HttpServer

SHAPE = (3, 240, 320)
CAMERA_HZ = 5  # Halves the parent's per-frame copy/hash work and Gazebo's render pauses; observation age is 3 s.
# Contract timing, not a performance claim: headless Gazebo on the lab PCs renders cameras on the CPU (EGL falls
# back to software), so a SmolVLA step there took ~0.5 s (2026-10-25). Observation age stays above action age so a
# late action reaches the action-age check itself; latency is measured GPU-exclusively instead (D-866 §4).
TIMING = dict(period_ns=1_500_000_000, max_observation_age_ns=3_000_000_000, max_action_age_ns=2_000_000_000)
CAMERAS = (('front', '/front_camera/image_raw'), ('top', '/top_camera/image_raw'))
RIG = 'sim-rig-vla-p0'
MAX_STEP_RAD, PRELUDE_STEPS, STALE_DELAY_S, JOINT_STATE_AGE_S = .04, 3, 2.5, 1.0
TASK = 'pick up the cube and place it on the pallet'


def emit_line(child):
    deadline = time.monotonic()+600
    while time.monotonic() < deadline:
        line = child.stdout.readline()
        assert line, 'VLA child exited before replying'
        if line.startswith('VLA_CHILD='):
            return json.loads(line.removeprefix('VLA_CHILD='))
    raise AssertionError('VLA child reply deadline')


def vla_world(out):
    """omx_pilot_workcell with its camera renamed to front and a second, overhead top camera."""
    original = ROOT/'integrations/simulation/gazebo/worlds/omx_pilot_workcell.sdf'
    world = ET.fromstring(original.read_bytes())
    world.find('./world/physics/max_step_size').text = '0.002'
    front = world.find(".//model[@name='workcell_camera']")
    top = copy.deepcopy(front)
    top.set('name', 'top_camera')
    top.find('pose').text = '0.12 0 0.75 0 1.5707963 0'
    for model, (name, topic) in zip((front, top), CAMERAS):
        sensor = model.find('.//sensor')
        sensor.find('topic').text = topic
        sensor.find('gz_frame_id').text = name+'_camera_optical'
        sensor.find('camera/camera_info_topic').text = topic.rsplit('/', 1)[0]+'/camera_info'
        sensor.find('update_rate').text = str(CAMERA_HZ)
        image = sensor.find('camera/image')
        image.find('width').text, image.find('height').text = str(SHAPE[2]), str(SHAPE[1])
    world.find('./world').append(top)
    path = out/'vla-world.sdf'
    ET.ElementTree(world).write(path, encoding='utf-8', xml_declaration=True)
    variant = hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'world-source.json').write_text(json.dumps(dict(source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
        variant_sha256=variant, cameras=dict(CAMERAS), camera_shape=SHAPE, physics_step_s=.002,
        scope='D-866 P0 SIM variant; the committed top/front world belongs to the backend conformance step')))
    return path, variant


class Rig:
    """Both cameras, captured together in installed order (core_arm_policy._frames)."""

    def __init__(self, node, monotonic, calibration):
        self.cameras = [base.Camera(node, monotonic, calibration, name=name, identity='gazebo-vla-p0:'+name,
                                    topic=topic, shape=SHAPE, max_age_ns=TIMING['max_observation_age_ns'])
                        for name, topic in CAMERAS]

    @contextmanager
    def capture(self):
        with ExitStack() as stack:
            yield tuple(stack.enter_context(camera.capture()) for camera in self.cameras)

    def current(self):
        snapshots = [camera.current() for camera in self.cameras]
        return () if any(not s for s in snapshots) else tuple(s[0] for s in snapshots)

    @property
    def accepted(self):
        return min(camera.accepted for camera in self.cameras)


def installation(out, runtime, calibration, cfg, checkpoint):
    root = out/'vla-sim-policy'
    root.mkdir()
    blob = json.dumps(checkpoint, sort_keys=True).encode()
    (root/'checkpoint.json').write_bytes(blob)
    ref = dict(path='checkpoint.json', bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest())
    owner = owner_binding(runtime.owner)
    names = list(cfg.joint_names)
    limits = [list(cfg.position_limits[n]) for n in names]
    cameras = [dict(name=name, identity='gazebo-vla-p0:'+name, calibration_sha256=calibration,
                    source_shape=list(SHAPE), model_shape=list(SHAPE), color='rgb', scale=1/255) for name, _ in CAMERAS]
    declared = dict(profile='omx_joint_target_v1', robot_type='omx_sim_ros', environment='sim',
                    device_profile_revision='sim-omx-vla-p0', camera_profile_revision='sim-camera-320x240-front-top')
    doc = seal(dict(schema='rosy.policy-artifact/1', **declared, files=[ref], normalization=ref, evaluations=[ref],
        joint_names=names, cameras=cameras, owner=owner,
        observation=dict(names=names, units=['rad']*len(names), shape=[len(names)]),
        action=dict(names=names, units=['rad']*len(names), semantics='absolute_joint_position_target_rad', limits=limits),
        timing=TIMING, failure_mode='hold', reset_events=['stop', 'hold', 'lease_change', 'episode_change'],
        dataset_revisions=[ref['sha256']], tool_revision='D-866-P0-sim-probe'))
    (root/'policy-artifact.json').write_text(json.dumps(doc))
    binding = InstallBinding(policy_revision=doc['revision'], **declared, owner=owner, cameras=cameras,
        normalization_sha256=ref['sha256'], action_names=tuple(names), action_limits=tuple(map(tuple, limits)),
        timing=TIMING)
    return load_policy(root, binding)


def scenario(case, out, runtime, rig, controllers, calibration):
    cfg = runtime.owner.config
    assert len(cfg.joint_names) == 6, cfg.joint_names
    checkpoint_dir = os.environ['ROSY_VLA_CHECKPOINT']
    python = Path(os.environ.get('ROSY_POLICY_GPU_PYTHON',
                                 str(Path.home()/'rosy-test/venvs/policy-latency-gpu/bin/python')))
    assert python.is_file(), 'GPU policy environment required'
    with ExitStack() as stack:
        # The lab disk's fsync stalls pushed a lease POST past the 0.25 s transport bound; SIM stores live in RAM
        # with their fsync unchanged, and are copied into the evidence once every store has closed.
        stores = Path(stack.enter_context(tempfile.TemporaryDirectory(dir='/dev/shm', prefix='rosy-vla-p0-')))
        stack.callback(shutil.copytree, stores, out, dirs_exist_ok=True)
        env = dict(os.environ, PYTHONPATH=str(ROOT/'integrations/robots/omx/src'), HF_HUB_OFFLINE='1',
                   TRANSFORMERS_OFFLINE='1')
        child = stack.enter_context(process([str(python), '-u', str(Path(__file__).with_name('policy_chain_vla_child.py'))],
            out, 'vla-child', env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True))
        base.sdk_send(child, dict(joint_names=list(cfg.joint_names), checkpoint=checkpoint_dir, task=TASK,
            camera_shape=list(SHAPE), limits=[list(cfg.position_limits[n]) for n in cfg.joint_names],
            max_step_rad=MAX_STEP_RAD, stale_delay_s=STALE_DELAY_S))
        ready = emit_line(child)
        assert ready.get('ready') is True and ready['ros_imported'] is False, ready
        (out/'child-ready.json').write_text(json.dumps(ready, indent=2))
        future = None
        def controllers_ready():
            nonlocal future
            if future is None and controllers.service_is_ready():
                future = controllers.call_async(ListControllers.Request())
            if future is not None and future.done():
                result, future = future.result(), None
                return (any(c.name == 'arm_controller' and c.state == 'active' for c in result.controller)
                        and runtime.action_port.server_is_ready() and runtime.latest_joint_state is not None
                        and rig.accepted >= 2)
            return False
        until(controllers_ready, 90, 'vendor controller, joint state and both cameras required')
        checkpoint = {k: ready[k] for k in ('checkpoint_sha256', 'hub_repo', 'hub_revision', 'checkpoint') if k in ready}
        policy = installation(out, runtime, calibration, cfg, checkpoint)
        fence_db = stores/'stop.sqlite3'
        ActionStore(fence_db)
        fence = LocalStopController(fence_db, workcell_id=cfg.workcell_id, instance_id=cfg.instance_id)
        fence.rearm(authority_epoch=1, dispatch_generation=1, operator_confirmed=True, fleet_fence_current=lambda *_: True)
        identity = AttemptIdentity('sim-local-mission', 'step', 'action', 'attempt', cfg.workcell_id, cfg.instance_id,
                                   'a'*64, 1, 1)
        revision = policy.recheck()['revision']
        fleet = stack.enter_context(approved_fleet(stores/'fleet', workcell_id=cfg.workcell_id, instance_id=cfg.instance_id,
            policy_revision=revision, rig_revision=RIG, calibration_revision=cfg.calibration_revision))
        scope = LeaseScope(identity, 'sim-episode', revision, runtime.owner.session_id, fleet.window['window_id'], RIG,
                           cfg.calibration_revision, fleet.scope)
        # Same preparation as policy_chain_gazebo.py: import and build CORE/uvicorn and touch Fleet before the
        # short lease starts, so first-use cost is not charged to the lease (2026-10-25 P0 run expired it).
        began = runtime.monotonic()
        closed_app = create_app({}, SimpleNamespace(arm_policy=None, safety=SimpleNamespace(estop=False, estop_listeners=[])))
        uvicorn.Config(closed_app, log_level='warning', lifespan='off').load()
        fleet.admin('GET', '/api/fleet/workcells/'+cfg.workcell_id+'/policy')
        (out/'preparation-timing.json').write_text(json.dumps(dict(prepared_s=runtime.monotonic()-began)))
        exchanges = []
        def request(method, path, body=None):
            began = runtime.monotonic()
            row = dict(method=method, path=path, started_s=began)
            try:
                return fleet.device(method, path, body)
            except Exception as error:
                row['error_type'] = type(error).__name__
                raise
            finally:
                row['elapsed_s'] = runtime.monotonic()-began
                exchanges.append(row)
                (out/'exchanges.json').write_text(json.dumps(exchanges, indent=2))
        consumer = FleetLeaseConsumer(scope, request=request, monotonic=runtime.monotonic)
        journal = PolicyExecutionJournal(stores/'execution.sqlite3')
        renewals = []
        renew = consumer.renew
        fetch = consumer._fetch
        def timed_fetch(old):
            try:
                return fetch(old)
            finally:
                if renewals and 'done_s' not in renewals[-1]:
                    renewals[-1]['fetched_s'] = runtime.monotonic()
        consumer._fetch = timed_fetch
        def timed_renew(session):
            row = dict(called_s=runtime.monotonic(), remaining_s=session.lease.expires_at_ns/1e9-runtime.monotonic())
            renewals.append(row)
            try:
                return renew(session)
            except Exception as error:
                cause = error.__context__  # renew() raises `from None`; the check that failed is kept here.
                row['error'] = f'{type(error).__name__}: {error}'[:200]
                row['cause'] = f'{type(cause).__name__}: {cause}'[:300] if cause else None
                row['hold_reason'] = session.hold_reason
                raise
            finally:
                row['done_s'] = runtime.monotonic()
                (out/'renewals.json').write_text(json.dumps(renewals, indent=2))
        consumer.renew = timed_renew
        chain = stack.enter_context(SimPolicyChain(policy=policy, runtime=runtime, fence=fence, consumer=consumer,
            journal=journal, owner_identity=lambda: dict(simulation=True, workcell_id=cfg.workcell_id,
                instance_id=cfg.instance_id, profile='sim-omx-vla-p0'), camera_current=rig.current,
            capture=rig.capture, principal='sim-sdk', installed_rig_revision=RIG, enabled=True))
        credential = secrets.token_urlsafe(32)
        token_file = out/'sdk.private'
        token_file.touch(mode=0o600, exist_ok=False)
        token_file.write_text(credential)
        config = dict(auth=dict(tokens=[dict(id='sim-sdk', role='operator',
                                             sha256=hashlib.sha256(credential.encode()).hexdigest())]))
        services = SimpleNamespace(config=config, arm_policy=chain.port, safety=SimpleNamespace(estop=False, estop_listeners=[]))
        app = create_app(config, services)
        commands, observations, refusals = [], [], []
        # Record from the port's own return values: re-parsing each ~600 KB observation body in this process held
        # the GIL long enough to push the lease renewal past its 0.25 s exchange bound (2026-10-25 P0 runs).
        observe, submit = chain.port.observation, chain.port.submit
        def observed(*args, **kwargs):
            value = observe(*args, **kwargs)
            observations.append(dict(observation_id=value['observation_id'], at_s=runtime.monotonic(),
                                     served=[c['frame_sha256'] for c in value['cameras']],
                                     captured=[camera.captures[-1]['frame_sha256'] for camera in rig.cameras]))
            return value
        def submitted(*args, **kwargs):
            value = submit(*args, **kwargs)
            if value.get('accepted') is True:
                commands.append(dict(command_id=value['command_id'], at_s=runtime.monotonic()))
            return value
        chain.port.observation, chain.port.submit = observed, submitted
        async def traced(scope_, receive, send):
            status = None
            async def delivered(message):
                nonlocal status
                if message['type'] == 'http.response.start':
                    status = message['status']
                if (message['type'] == 'http.response.body' and message.get('body')
                        and status is not None and status >= 400):
                    refusals.append(dict(path=scope_.get('path'), status=status, response=json.loads(message['body']),
                                         at_s=runtime.monotonic(), hold_reason=chain.session.hold_reason,
                                         owner=runtime.owner.state))
                    (out/'refusals.json').write_text(json.dumps(refusals, indent=2))
                await send(message)
            await app(scope_, receive, delivered)
        core = stack.enter_context(HttpServer(traced))
        base.sdk_send(child, dict(url=core.url, token_file=str(token_file), policy_revision=revision))
        connected = emit_line(child)
        assert connected.get('connected') is True and [c['name'] for c in connected['cameras']] == [n for n, _ in CAMERAS]
        steps = []
        def run_step(op='step'):
            if commands:
                last = commands[-1]['command_id']
                state = lambda: dict(owner=runtime.owner.recovery_state(), hold_reason=chain.session.hold_reason,
                                     events=[e['kind'] for e in journal.read(last)['events']][-4:])
                try:
                    until(lambda: any(e['kind'] == 'TERMINAL_RESULT' for e in journal.read(last)['events']), 8,
                          'previous goal terminal')
                    until(lambda: runtime.owner.state == 'ready', 3, 'owner ready')
                except AssertionError as error:
                    raise AssertionError(f'{error}: {json.dumps(state(), default=str)[:1500]}') from None
                time.sleep(max(0., commands[-1]['at_s']+TIMING['period_ns']/1e9+.05-runtime.monotonic()))
            base.sdk_send(child, dict(op=op))
            reply = emit_line(child)
            steps.append(reply)
            return reply
        for _ in range(PRELUDE_STEPS):
            reply = run_step()
            assert 'stages' in reply and not reply.get('refused'), reply
            assert observations[-1]['served'] == observations[-1]['captured'], 'both frames must be the captured ones'
            candidate = journal.read(commands[-1]['command_id'])['intent']['candidate']
            assert candidate['camera_frames'] == observations[-1]['captured'], candidate
        result = dict(case=case)
        if case == 'stale':
            reply = run_step('stale')
            assert reply.get('refused') is True and (reply['code'], reply['status']) == ('ARM_POLICY_FORBIDDEN', 403), reply
            assert chain.session.hold_reason == 'policy_action_stale', chain.session.hold_reason
            result.update(stale_reply=reply)
        else:
            before = len(commands)
            reply = run_step()
            assert len(commands) == before+1, reply
            handle = runtime.action_port.last_handle
            assert not handle.done(), 'the stop or withdrawal must happen during this goal'
            began = time.monotonic()
            if case == 'stop':
                base.sdk_send(child, dict(op='stop'))
                assert emit_line(child).get('stopped') is True
            else:
                fleet.operator('POST', fleet.base+'/windows/'+scope.window_id+'/close',
                               dict(operator_confirmed=True, reason='SIM in-motion revocation'))
            until(handle.done, 3, 'exact owned goal cancel terminal')
            assert handle.status == 5 and handle.cancel_acknowledged is True
            assert chain.session.hold_reason and runtime.owner.state == 'hold'
            assert not fence.is_open(authority_epoch=1, dispatch_generation=1) or case == 'revoke'
            result.update(cancel_status=handle.status, cancel_ack=handle.cancel_acknowledged,
                          cancel_after_s=time.monotonic()-began)
        base.sdk_send(child, dict(op='reconnect'))
        reconnect = emit_line(child)
        assert all(r['refused'] for r in reconnect['results']), reconnect
        with closing(sqlite3.connect(fleet.db)) as db:
            leases = db.execute('SELECT lease_id, issued_ns, expires_ns FROM fleet_policy_lease').fetchall()
        result.update(policy_revision=revision, timing=TIMING, checkpoint=checkpoint, child=ready, steps=steps,
                      observations=observations, commands=commands, refusals=refusals, reconnect=reconnect,
                      hold_reason=chain.session.hold_reason, owner_state=runtime.owner.state, leases=leases,
                      camera_accepted=[c.accepted for c in rig.cameras], camera_rejected=[c.rejected for c in rig.cameras],
                      scope='D-866 P0 SIM contract probe; untrained base model, clamped proposals, no task success')
        (out/'chain-result.json').write_text(json.dumps(result, indent=2, default=str))
        print(f'OMX_VLA_P0_{case.upper()}_PASS='+json.dumps(dict(case=case, hold_reason=result['hold_reason'],
              steps=len(steps), reconnect_refused=True)), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('stale', 'stop', 'revoke'), required=True)
    case = parser.parse_args().case
    out = Path(os.environ['OUT']).resolve()
    assert out.is_dir() and os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') == 'LOCALHOST'
    # As policy_chain_gazebo.py: one BLAS thread per process, so the scope's CPU quota is not oversubscribed
    # (the lease renewal's short Fleet exchange starved in the 2026-10-25 P0 run without this).
    os.environ.update({key: '1' for key in ('LP_NUM_THREADS', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')})
    # py-spy --gil (P0 2026-10-25): 82% of GIL time was rclpy's executor rebuilding its wait set. At the default
    # 5 ms switch interval each GIL hand-back in a renewal exchange waited behind it (server 5 ms, client up to
    # 166 ms), and renewals expired the 1 s lease. The lease and transport bounds are unchanged.
    sys.setswitchinterval(.0005)
    group = Path('/sys/fs/cgroup')/next(line.removeprefix('0::') for line in
        Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')).lstrip('/')
    (out/'cpu-profile.json').write_text(json.dumps(dict(cpu_max=(group/'cpu.max').read_text(),
        cpu_before=(group/'cpu.stat').read_text())))
    world_file, calibration = vla_world(out)
    env = dict(os.environ, OMX_CELL_WORLD=str(world_file.with_suffix('')), OMX_CELL_LOG_DIR=str(out),
               OMX_CELL_DOMAIN_ID=os.environ['ROS_DOMAIN_ID'])
    with ExitStack() as stack:
        stack.enter_context(process(['bash', 'deploy/robot/omx/run_cell_sim.sh'], out, 'vendor', env=env))
        stack.enter_context(process(['ros2', 'run', 'ros_gz_bridge', 'parameter_bridge',
            *[topic+'@sensor_msgs/msg/Image[gz.msgs.Image' for _, topic in CAMERAS]], out, 'camera-bridge'))
        rclpy.init()
        node = Node('omx_vla_p0_'+uuid4().hex[:8], parameter_overrides=[Parameter('use_sim_time', value=True)])
        profile = CellPlanningProfile.load(ROOT/'deploy/robot/omx/sim/cell_profile.yaml')
        cfg = profile.arm_command_config(workcell_id='sim_policy_cell', instance_id='sim_policy_arm',
            calibration_revision='sim-cal-'+calibration[:12], allowed_owners=('learned_policy',))
        # SIM-only: with two rendered cameras Gazebo paused joint_states up to 0.53 s of sim time (2026-10-25
        # intake trace), past the profile's 0.5 s. The owner's staleness check is unchanged; only this probe's
        # bound is 1.0 s. Real and production owners keep their own values.
        cfg = replace(cfg, max_joint_state_age_s=JOINT_STATE_AGE_S)
        runtime = RosArmCommandRuntime(node, cfg, poll_period_s=.01, owner_clock='steady')
        stalls, gc_pauses = deque(maxlen=2000), deque(maxlen=2000)
        def heartbeat():  # Process-wide stalls: a 10 ms sleeper that wakes late was kept off the GIL or paused.
            while True:
                began = time.monotonic()
                time.sleep(.01)
                late = time.monotonic()-began-.01
                if late > .05:
                    stalls.append(dict(at_s=began, late_s=late))
        threading.Thread(target=heartbeat, daemon=True, name='stall-heartbeat').start()
        gc_began = {}
        def gc_timing(phase, info):
            if phase == 'start':
                gc_began['s'] = time.monotonic()
            elif time.monotonic()-gc_began.get('s', time.monotonic()) > .01:
                gc_pauses.append(dict(at_s=gc_began['s'], pause_s=time.monotonic()-gc_began['s'], **info))
        gc.callbacks.append(gc_timing)
        intake_trace = deque(maxlen=4000)  # Same joint intake trace as policy_chain_gazebo.py, to tell gaps apart.
        intake = runtime._joint_state_intake
        snapshot = intake.snapshot
        def traced_snapshot(*args, **kwargs):
            entry = dict(callback_s=time.monotonic(), previous_stamp_ns=intake._last_stamp_ns, **kwargs)
            try:
                value = snapshot(*args, **kwargs)
                entry.update(sequence=value.sequence, adjusted_received_at=value.received_at)
                return value
            except Exception as error:
                entry['rejected'] = str(error)[:200]
                raise
            finally:
                intake_trace.append(entry)
        intake.snapshot = traced_snapshot
        rig = Rig(node, runtime.monotonic, calibration)
        controllers = node.create_client(ListControllers, '/controller_manager/list_controllers')
        started = (node.get_clock().now().nanoseconds, time.monotonic())
        executor = MultiThreadedExecutor(num_threads=4)
        executor.add_node(node)
        errors = []
        def work():
            try:
                scenario(case, out, runtime, rig, controllers, calibration)
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=work, name='omx-vla-p0')
        worker.start()
        try:
            while worker.is_alive():
                executor.spin_once(timeout_sec=.1)
            worker.join()
        finally:
            runtime._timer.cancel()
            stopped = executor.shutdown(timeout_sec=5)
            drained = threading.Event()
            def drain():
                executor._executor.shutdown(wait=True)  # Same pinned-Jazzy drain as policy_chain_gazebo.py.
                drained.set()
            threading.Thread(target=drain, daemon=True).start()
            workers_stopped = drained.wait(5)
            memory_peak = group/'memory.peak'
            (out/'teardown.json').write_text(json.dumps(dict(executor_stopped=stopped, workers_stopped=workers_stopped,
                cpu_after=(group/'cpu.stat').read_text(),
                real_time_factor=(node.get_clock().now().nanoseconds-started[0])/1e9/max(1e-9, time.monotonic()-started[1]),
                primary_error=repr(errors[0]) if errors else None,
                memory_peak=memory_peak.read_text().strip() if memory_peak.exists() else None), indent=2))
            (out/'stalls.json').write_text(json.dumps(dict(stalls=list(stalls), gc=list(gc_pauses)), indent=2))
            (out/'joint-intake.json').write_text(json.dumps(list(intake_trace), default=str))
            assert stopped and workers_stopped, 'own executor/workers did not drain'
            runtime.destroy()
            node.destroy_node()
            rclpy.try_shutdown()
        if errors:
            raise errors[0]
        print('OMX_VLA_P0_EXIT_OK', flush=True)


if __name__ == '__main__':
    main()
