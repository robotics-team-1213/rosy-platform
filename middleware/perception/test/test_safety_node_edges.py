"""D-171 track 1: the ROS edge the ROS-free mixins call stays in the nodes, unchanged.

The mixins (goal_escape, safety scale/gate/obstacles/hazard/bumper) no longer build
messages; SafetyNode and GoalNode do. This pins what each edge method builds and where
the moved topics are created (type, name, depth, order), without ROS: the node methods
are compiled from source against stand-in message types.
"""
import ast
import json
from pathlib import Path
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
