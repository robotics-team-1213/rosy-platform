"""One executor choice for every control node (D-185 R3); ROS-free, so the host tests it.

ROSY_EXECUTOR selects how a node is spun:
  - unset or 'single': ``rclpy.spin(node)`` exactly as before (global SingleThreadedExecutor);
  - 'events': ``rclpy.experimental.EventsExecutor``, which cut an idle 15-subscription node
    from 50-58% to 15% of a core in the 2026-09-24 domain-228 experiment. It is experimental
    in Jazzy, so it is opt-in until the rig A/B and device measurement (D-185 R8) accept it.
'events' spins the executor natively (add_node, spin, remove_node), the same loop the rig
uses, instead of rclpy.spin's Python spin_once loop. Known differences under 'events': callbacks
run in arrival order rather than wait-set order, a context shut down from another thread raises
ExternalShutdownException, and a callback that raises (watch_node --once exits through
SystemExit) is also logged as FATAL by the native executor before it propagates.
Callers pass their ``rclpy`` module; nothing here imports ROS.
"""
import importlib
import os

KINDS = ('events', 'single')


def executor_kind(environ=os.environ):
    kind = environ.get('ROSY_EXECUTOR', 'single').strip().lower() or 'single'
    if kind not in KINDS:
        raise ValueError(f"ROSY_EXECUTOR must be one of {', '.join(repr(k) for k in KINDS)}, not {kind!r}")
    return kind


def make_executor(rclpy, kind, import_module=importlib.import_module):
    if kind == 'events':
        return import_module(rclpy.__name__ + '.experimental').EventsExecutor()
    return rclpy.executors.SingleThreadedExecutor()


def spin(node, rclpy, environ=os.environ, import_module=importlib.import_module):
    kind = executor_kind(environ)
    if kind == 'single':
        rclpy.spin(node)
        return
    executor = make_executor(rclpy, kind, import_module)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.remove_node(node)
