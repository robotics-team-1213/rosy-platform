"""Existing OMX owner adapter. No serial, torque, controller lifecycle, reset or HOLD recovery."""
from dataclasses import asdict
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import queue
import threading
import time

from collection_profile import require, validate_profile
from collection_session import validate_environment, validate_observation


def resource_key(action, domain):
    require(isinstance(action, str) and action.startswith('/') and '//' not in action
            and action == action.rstrip('/') and '/.' not in action, 'canonical action name required')
    require(isinstance(domain, str) and domain.isdigit(), 'explicit ROS_DOMAIN_ID required')
    return hashlib.sha256(json.dumps([int(domain), action]).encode()).hexdigest()[:24]


def process_identity(pid, expected_start):
    require(type(pid) is int and pid > 1, 'confirmed live process PID required')
    stat = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
    require(stat[0] not in ('Z', 'X') and stat[19] == str(expected_start), 'process stopped/replaced')


class RosBackend:
    mode = 'hardware'
    def __init__(self, profile, acceptance, teacher):
        validate_profile(profile, mode='hardware', acceptance=acceptance, teacher=teacher)
        import rclpy
        from rclpy.executors import MultiThreadedExecutor
        from omx_adapter.command_owner import ArmCommandConfig
        from omx_adapter.ros_runtime import RosArmCommandRuntime
        from collection_ros_inputs import RosInputs
        self.profile, self.acceptance, self.teacher = copy.deepcopy(profile), copy.deepcopy(acceptance), copy.deepcopy(teacher)
        self.lock, self.events = threading.RLock(), queue.Queue(maxsize=1024)
        self.event_lock, self.facts, self.command_id = threading.Lock(), {}, None
        self.fault, self.closed, self.armed = None, threading.Event(), False
        self.runtime, self.node, self.executor, self.thread, self.supervisor = None, None, None, None, None
        self.rclpy = rclpy
        self.guard = None
        try:
            runtime_dir = Path(f'/run/user/{os.getuid()}')
            require(runtime_dir.is_dir() and not runtime_dir.is_symlink()
                    and runtime_dir.stat().st_uid == os.getuid(), 'private runtime directory required')
            key = resource_key(profile['ros']['trajectory_action'], os.environ.get('ROS_DOMAIN_ID'))
            descriptor = os.open(runtime_dir/f'rosy-omx-action-{key}.lock',
                                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            self.guard = os.fdopen(descriptor, 'a')
            fcntl.flock(self.guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.verify_processes()
            rclpy.init()
            self.node = rclpy.create_node('omx_collection', namespace=profile['ros']['namespace'])
            require(not self.node.get_parameter('use_sim_time').value, 'hardware requires wall/steady clocks')
            self.inputs = RosInputs(self.node, profile)
            config = dict(profile['ros']['owner_config'])
            for key in ('joint_names', 'allowed_owners'):
                config[key] = tuple(config[key])
            owner = ArmCommandConfig(**config)
            require(owner.joint_names == tuple(profile['joint_names']) and owner.calibration_revision == profile['calibration_revision']
                    and owner.workcell_id == profile['workcell_id'] and owner.instance_id == profile['instance_id']
                    and owner.allowed_owners == ('rule_based',), 'collection/owner identity differs')
            self.runtime = RosArmCommandRuntime(self.node, owner,
                joint_state_topic=profile['ros']['joint_state_topic'],
                trajectory_action=profile['ros']['trajectory_action'], on_goal_event=self.on_event)
            self.executor = MultiThreadedExecutor(num_threads=4)
            self.executor.add_node(self.node)
            self.thread = threading.Thread(target=self.executor.spin, daemon=True)
            self.thread.start()
            self.supervisor = threading.Thread(target=self.monitor, daemon=True)
            self.supervisor.start()
        except Exception:
            self.close()
            raise

    def verify_processes(self):
        ros = self.profile['ros']
        process_identity(ros['controller_pid'], ros['controller_start_ticks'])
        process_identity(ros['watchdog_pid'], ros['watchdog_start_ticks'])
        binary = Path(f'/proc/{ros["controller_pid"]}/exe').resolve(strict=True)
        require(hashlib.sha256(binary.read_bytes()).hexdigest() == ros['controller_binary_sha256'],
                'active controller executable differs')

    def on_event(self, event):
        # ROS callbacks never fsync or wait on the writer. Overflow revokes the session.
        try:
            row = asdict(event)
            self.events.put_nowait(row)
            with self.event_lock:
                self.facts.setdefault(event.command_id, {})[event.kind] = row
        except Exception:
            self.fault = 'bounded ROS event queue failed'

    def observe(self):
        validate_profile(self.profile, mode='hardware', acceptance=self.acceptance, teacher=self.teacher)
        require(self.fault is None, 'collection supervisor: '+str(self.fault))
        raw = Path(self.profile['ros']['environment_state']).read_bytes()
        require(len(raw) <= 128*1024, 'oversized environment receipt')
        environment = json.loads(raw)
        validate_environment(environment, self.profile, now_ns=time.time_ns())
        sample = self.inputs.snapshot(environment)
        validate_observation(sample, self.profile, time.time_ns())
        return sample

    def verify_exclusion(self):
        from rclpy.action.graph import get_action_client_names_and_types_by_node
        for name, namespace in self.node.get_node_names_and_namespaces():
            if (name, namespace) == (self.node.get_name(), self.node.get_namespace()):
                continue
            clients = get_action_client_names_and_types_by_node(self.node, name, namespace)
            require(all(action != self.profile['ros']['trajectory_action'] for action, _ in clients),
                    'another action owner/client is present')

    def monitor(self):
        while not self.closed.wait(.05):
            if not self.armed:
                continue
            try:
                self.verify_processes()
                self.inputs.verify_publishers()
                self.verify_exclusion()
                self.observe()
            except Exception as exc:
                self.fault = str(exc)
                # Independent of collection storage and the event observer's delivery lock.
                self.runtime.owner.preempt('collection environment/telemetry failure')
                return

    def ready(self, timeout=5):
        deadline, last = time.monotonic()+timeout, None
        while time.monotonic() < deadline:
            try:
                self.verify_processes(); self.inputs.verify_publishers(); self.verify_exclusion()
                sample = self.observe()
                require(self.runtime.action_port.server_is_ready(), 'native action server unavailable')
                require(self.runtime.latest_joint_state is not None, 'owner has no joint state')
                return sample
            except (ValueError, KeyError, OSError) as exc:
                last = exc
                time.sleep(.05)
        raise ValueError('preflight not ready: '+str(last))

    def submit(self, step, command_id):
        from omx_adapter.command_owner import TrajectoryCommand
        with self.lock:
            self.verify_processes(); self.inputs.verify_publishers(); self.verify_exclusion(); self.observe()
            self.armed = True
            current, config = self.runtime.latest_joint_state, self.runtime.owner.config
            require(current is not None, 'owner joint state unavailable')
            command = TrajectoryCommand(workcell_id=config.workcell_id, instance_id=config.instance_id,
                command_id=command_id, session_id=self.runtime.owner.session_id, owner='rule_based',
                positions=dict(zip(self.profile['joint_names'], step['positions'])), duration_s=step['duration_s'],
                source_state_sequence=current.sequence, calibration_revision=config.calibration_revision,
                expected_start_state_positions=dict(current.positions),
                start_state_tolerances=dict(config.max_start_state_tolerances))
            self.command_id = command_id
            return asdict(self.runtime.submit(command))

    def terminal(self):
        handle = self.runtime.action_port.last_handle
        if handle is None or not handle.done():
            return None
        if handle.succeeded():
            with self.event_lock:
                facts = self.facts.get(self.command_id, {})
                accepted, terminal = facts.get('GOAL_ACCEPTED'), facts.get('TERMINAL_RESULT')
            require(accepted is not None and terminal is not None
                    and accepted['goal_id'] == terminal['goal_id'] and terminal['status'] == 4
                    and terminal['result_code'] == 0, 'missing native current-command terminal evidence')
        return dict(succeeded=handle.succeeded(), status=handle.status, source='native_follow_joint_trajectory')

    def drain_events(self):
        result = []
        while True:
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                return result

    def stop(self, reason):
        with self.lock:
            decision = self.runtime.owner.preempt('collection stop')
            self.armed = False
        handle = self.runtime.action_port.last_handle
        deadline = time.monotonic()+2
        while handle is not None and not handle.done() and time.monotonic() < deadline:
            time.sleep(.01)
        return dict(hold_requested=self.runtime.owner.state == 'hold', decision=asdict(decision), reason=reason,
                    terminal_observed=handle is None or handle.done(),
                    cancel_acknowledged=None if handle is None else handle.cancel_acknowledged,
                    physical_stop_verified=False)

    def close(self):
        self.closed.set()
        if self.runtime is not None:
            self.stop('collection process exit')
        if self.supervisor is not None:
            self.supervisor.join(timeout=2)
        if self.executor is not None:
            self.executor.shutdown(timeout_sec=2)
        if self.thread is not None:
            self.thread.join(timeout=2)
        if self.runtime is not None:
            self.runtime.destroy()
        if self.node is not None:
            self.node.destroy_node()
        if self.rclpy.ok():
            self.rclpy.shutdown()
        if self.guard is not None:
            self.guard.close()
