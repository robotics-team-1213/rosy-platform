"""D-171 track 1: the ROS edge the ROS-free mixins call stays in the nodes, unchanged.

The mixins (goal_escape, safety scale/gate/obstacles/hazard/bumper) no longer build
messages; SafetyNode and GoalNode do. This pins what each edge method builds and where
the moved topics are created (type, name, depth, order), without ROS: the node methods
are compiled from source against stand-in message types.
"""
import ast
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

DRIVE = Path(__file__).resolve().parents[2] / 'drive'
SAFETY = DRIVE / 'motion_limits/adapter/node.py'
EDGES = DRIVE / 'motion_limits/adapter/ros_edges.py'  # SafetyNode's RosEdges mixin (D-766 split)
GOAL = DRIVE / 'runtime/goal_node.py'


class Message:
    def __init__(self, *args, **fields):
        self.args, self.fields = args, fields

    def __eq__(self, other):
        return type(self) is type(other) and (self.args, self.fields) == (other.args, other.fields)


class String(Message): pass
class Bool(Message): pass
class Float32(Message): pass
class Twist(Message): pass


class Time(Message):
    @classmethod
    def from_msg(cls, stamp):
        return cls(stamp)


class TransformException(Exception):
    pass


def node_class(path, name):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)


def methods(path, cls, *names):
    picked = [n for n in node_class(path, cls).body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in picked} == set(names)
    scope = dict(String=String, Bool=Bool, Float32=Float32, Twist=Twist, Time=Time,
                 TransformException=TransformException, json=json)
    exec(compile(ast.Module(body=picked, type_ignores=[]), str(path), 'exec'), scope)
    return SimpleNamespace(**{name: scope[name] for name in names})


def after(path, cls, call, count):
    """Source of the `count` statements that follow `call` in the node's __init__."""
    init = next(n for n in node_class(path, cls).body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
    lines = [ast.unparse(n) for n in init.body]
    at = lines.index(call)
    return lines[at + 1:at + 1 + count]


class Publisher:
    def __init__(self):
        self.sent = []

    def publish(self, msg):
        self.sent.append(msg)


def test_safety_publish_edges_build_the_same_messages():
    edge = methods(EDGES, 'RosEdges', 'publish_text', 'publish_bool', 'publish_float', 'zero_twist')
    pub = Publisher()
    edge.publish_text(None, pub, 'stop')
    edge.publish_bool(None, pub, True)
    edge.publish_float(None, pub, -1.0)
    assert pub.sent == [String(data='stop'), Bool(data=True), Float32(data=-1.0)]
    first, second = edge.zero_twist(None), edge.zero_twist(None)
    assert first == Twist() and first is not second          # a fresh message each time, as Twist() was


def test_drive_sign_parameter_write_is_the_same_call():
    method = next(n for n in node_class(EDGES, 'RosEdges').body
                  if isinstance(n, ast.FunctionDef) and n.name == 'set_linear_sign_parameter')
    assert ast.unparse(method.body[-1]) == (
        "self.set_parameters([Parameter('cmd_linear_sign', Parameter.Type.DOUBLE, value)])")


def test_safety_tf_and_time_edges():
    edge = methods(EDGES, 'RosEdges', 'stamp_time', 'lookup_base_from', 'lookup_odom_base')
    calls = []
    node = SimpleNamespace(lidar_tf=SimpleNamespace(lookup_transform=lambda *args: calls.append(args) or 'tf'))
    assert edge.stamp_time(node, 'stamp') == Time.from_msg('stamp')
    assert edge.lookup_base_from(node, 'laser', 'stamp') == 'tf'
    assert edge.lookup_odom_base(node) == 'tf'
    assert calls == [('base_link', 'laser', Time.from_msg('stamp')), ('odom', 'base_link', Time())]

    def missing(*args):
        raise TransformException('frame laser does not exist')
    node.lidar_tf.lookup_transform = missing
    with pytest.raises(ValueError, match='^frame laser does not exist$'):
        edge.lookup_base_from(node, 'laser', 'stamp')
    assert edge.lookup_odom_base(node) is None


def test_safety_node_creates_the_obstacle_subscriptions_where_the_mixin_did():
    assert after(SAFETY, 'SafetyNode', 'self.init_obstacles()', 2) == [
        "self.create_subscription(String, 'obstacles/tracks', self.on_obstacle_tracks, 10)",
        "self.create_subscription(String, 'camera/observation', self.on_camera_observation, 10)"]


def test_goal_node_creates_the_escape_topics_where_the_mixin_did():
    assert after(GOAL, 'GoalNode', 'self.init_escape()', 3) == [
        "self.escape_pub = self.create_publisher(String, 'goal/straight_escape', 10)",
        "self.create_subscription(String, 'safety/motion_limits', self.on_escape_limits, 1)",
        "self.create_subscription(String, 'goal/straight_escape_result', self.on_escape_result, 10)"]
    pub = Publisher()
    methods(GOAL, 'GoalNode', 'publish_escape').publish_escape(SimpleNamespace(escape_pub=pub), {'id': 'e1'})
    methods(GOAL, 'GoalNode', 'publish_escape').publish_escape(SimpleNamespace(escape_pub=pub), None)
    assert pub.sent == [String(data='{"id": "e1"}'), String(data='null')]


def test_shared_robot_transform_buffer_translates_frames_without_constructing_tf2_buffer(monkeypatch):
    constructed = []

    class FakeTf2Buffer:
        def __init__(self, *args, **kwargs):
            constructed.append((args, kwargs))

    monkeypatch.setitem(sys.modules, 'tf2_ros', SimpleNamespace(Buffer=FakeTf2Buffer))
    perception_root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(perception_root))
    monkeypatch.delitem(sys.modules, 'nodes.tf_buffer', raising=False)
    tf_mod = importlib.import_module('nodes.tf_buffer')

    calls = []

    class FakeSharedBuffer:
        def lookup_transform(self, target, source, t, *args, **kwargs):
            calls.append(('lookup', target, source, t, args, kwargs))
            return 'tx'

        def lookup_transform_full(self, target, tt, source, st, fixed, *args, **kwargs):
            calls.append(('full', target, tt, source, st, fixed, args, kwargs))
            return 'tx_full'

    params = {'frame_prefix': SimpleNamespace(value='rosy_01')}
    fake_node = SimpleNamespace(
        has_parameter=lambda name: name in params,
        get_parameter=lambda name: params[name],
        get_namespace=lambda: '/rosy_01',
    )
    shared = tf_mod.SharedRobotTransformBuffer(fake_node, FakeSharedBuffer())
    assert constructed == []
    assert shared.robot_frame('base_link') == 'rosy_01/base_link'
    assert shared.robot_frame('map') == 'map'
    assert shared.lookup_transform('odom', 'base_link', 't0', timeout=1.0) == 'tx'
    assert shared.lookup_transform_full('odom', 't1', 'base_footprint', 't2', 'map') == 'tx_full'
    assert calls == [
        ('lookup', 'rosy_01/odom', 'rosy_01/base_link', 't0', (), {'timeout': 1.0}),
        ('full', 'rosy_01/odom', 't1', 'rosy_01/base_footprint', 't2', 'map', (), {}),
    ]


def test_safety_node_uses_shared_tf_buffer_without_creating_transform_listener():
    init = next(n for n in node_class(SAFETY, 'SafetyNode').body
                if isinstance(n, ast.FunctionDef) and n.name == '__init__')
    assert 'tf_buffer' in [kw.arg for kw in init.args.kwonlyargs]
    assert 'in_process_topics' in [kw.arg for kw in init.args.kwonlyargs]
    src = ast.unparse(init)
    assert 'SharedRobotTransformBuffer(self, tf_buffer)' in src
    assert 'self.lidar_tf_listener = None' in src
    assert "'scan' not in self._in_process_topics" in src
    assert "'us' not in self._in_process_topics" in src
    assert "'imu' not in self._in_process_topics" in src


def test_evidence_refresh_profile_publishes_only_when_profile_changes():
    evidence_path = DRIVE / 'motion_limits/adapter/evidence.py'
    tree = ast.parse(evidence_path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Evidence')
    picked = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ('refresh_profile', 'publish_calibration_applied')]
    import hashlib
    scope = {
        'json': json, 'time': importlib.import_module('time'), 'math': importlib.import_module('math'),
        'hashlib': hashlib, 'SimpleNamespace': SimpleNamespace, 'String': String,
        'LIDAR_X': 0.0, 'rotation_radius': lambda r: r, 'RotationEnvelope': lambda *_a: None,
    }
    exec(compile(ast.Module(body=picked, type_ignores=[]), str(evidence_path), 'exec'), scope)
    sent = []

    class Holder:
        def __init__(self):
            self.robot_r, self.stop_d, self.clear_d = 0.08, 0.2, 0.3
            self.rear_stop_d, self.rear_clear_d = 0.2, 0.3
            self.lidar_yaw, self.cmd_linear_sign, self.half_w = 0.0, 1.0, 0.5
            self.us_stop, self.us_clear, self.lidar_mount = 0.02, 0.03, None
            self.calibration_lease = SimpleNamespace(active=None, report=lambda _t: {})
            self.profile = SimpleNamespace(revision='boot')
            self.profile_valid, self.profile_error = True, None
            self._last_profile_key = None
            self._sensor_only = True
            self.profile_pub = Publisher()
            self._params = {
                'rotation_footprint_xy': [],
                'safety_max_linear': 0.14, 'safety_max_angular': 0.10,
                'footprint_guard_enabled': False, 'simulation_motion_sweep_enabled': False,
                'imu_angular_velocity_unit': 'deg_s',
            }

        def get_parameter(self, name):
            return SimpleNamespace(value=self._params[name])

        def _refresh_distances(self):
            pass

        refresh_profile = scope['refresh_profile']
        publish_calibration_applied = scope['publish_calibration_applied']

    holder = Holder()
    holder.refresh_profile()
    holder.refresh_profile()
    assert len(holder.profile_pub.sent) == 1
    holder.stop_d = 0.25
    holder.refresh_profile()
    assert len(holder.profile_pub.sent) == 2
    assert sent == []
