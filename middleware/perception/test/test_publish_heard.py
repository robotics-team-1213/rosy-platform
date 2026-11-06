"""Diagnostic safety topics skip the publish while unheard; stop inputs always publish.

Compiled from source without ROS, like test_safety_node_edges.
"""
import ast
from pathlib import Path

from test_safety_node_edges import EDGES, SAFETY, Float32, methods, node_class

GATED = {'left', 'right', 'rear_left', 'rear_right', 'open', 'open_yaw', 'frontier_yaw', 'frontier',
         'route_yaw', 'route', 'exit_yaw', 'exit', 'radius'}
ALWAYS = {'range', 'us', 'rear', 'cliff', 'block', 'tilt', 'pickup', 'rear_clear', 'can_rev', 'motion_limits'}


class Pub:
    def __init__(self, subs=None):
        self.subs, self.sent = subs, []

    def publish(self, msg):
        self.sent.append(msg)

    def get_subscription_count(self):
        if self.subs is None:
            raise RuntimeError('graph unavailable')
        return self.subs


def edge():
    return methods(EDGES, 'RosEdges', 'publish_heard', 'publish_float')


def test_unheard_is_skipped_and_heard_is_published_in_the_same_call():
    e, p = edge(), Pub(0)
    e.publish_heard(None, p, Float32(data=1.0)); e.publish_float(None, p, 2.0)
    assert p.sent == []
    p.subs = 1                      # a subscriber matched: the very next call carries the value
    e.publish_heard(None, p, Float32(data=1.0)); e.publish_float(None, p, 2.0)
    assert p.sent == [Float32(data=1.0), Float32(data=2.0)]


def test_count_failure_or_missing_count_publishes():
    e = edge()
    broken, bare = Pub(None), type('B', (), {'sent': [], 'publish': lambda s, m: s.sent.append(m)})()
    e.publish_heard(None, broken, Float32(data=1.0)); e.publish_heard(None, bare, Float32(data=1.0))
    e.publish_float(None, broken, 1.0); e.publish_float(None, bare, 1.0)
    assert len(broken.sent) == 2 and len(bare.sent) == 2


def _tick():
    return next(n for n in node_class(SAFETY, 'SafetyNode').body if getattr(n, 'name', '') == 'tick')


def _gated_topics():
    return {c.args[0].attr.removesuffix('_pub') for c in ast.walk(_tick())
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == 'publish_heard'}


def _published_topic(statement):
    call = statement.value if isinstance(statement, ast.Expr) else None
    if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == 'publish'
            and isinstance(call.func.value, ast.Attribute)):
        return call.func.value.attr.removesuffix('_pub')
    return None


def test_tick_gates_only_the_diagnostic_topics():
    assert _gated_topics() == GATED


def test_every_stop_input_is_a_direct_statement_of_tick():
    assert ALWAYS <= {_published_topic(statement) for statement in _tick().body}


def test_only_invalid_geometry_can_leave_tick_before_the_stop_inputs():
    """An invalid profile leaves early on purpose (GateInputs or a halt carries it); nothing else may."""
    body = _tick().body
    last = max(i for i, statement in enumerate(body) if _published_topic(statement) in ALWAYS)
    exits = [ast.unparse(statement.test) if isinstance(statement, ast.If) else type(statement).__name__
             for statement in body[:last] if not isinstance(statement, ast.FunctionDef)  # a local helper's return
             if any(isinstance(node, (ast.Return, ast.Raise)) for node in ast.walk(statement))]
    assert exits == ['not self.profile_valid']
