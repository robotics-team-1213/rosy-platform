"""Exercise the Gazebo provider body without importing ROS on a pytest host."""
import ast
import hashlib
from pathlib import Path
import threading
from types import SimpleNamespace as NS

from rosy.execution.local.omx_policy import CameraSnapshot


def test_camera_preserves_source_age():
    tree = ast.parse(Path(__file__).with_name('policy_chain_gazebo.py').read_text())
    camera = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Camera')
    scope = dict(threading=threading, hashlib=hashlib, CameraSnapshot=CameraSnapshot,
                 Image=object, qos_profile_sensor_data=object(), SHAPE=(3, 24, 32),
                 TIMING={'max_observation_age_ns': 500_000_000})
    exec(compile(ast.Module(body=[camera], type_ignores=[]), '<actual Camera provider>', 'exec'), scope)
    node = NS(create_subscription=lambda *args: None,
              get_clock=lambda: NS(now=lambda: NS(nanoseconds=20_000_000_000)))
    provider = scope['Camera'](node, lambda: 100.0, 'cal')
    provider.receive(NS(header=NS(stamp=NS(sec=19, nanosec=510_000_000)),
                        encoding='rgb8', height=24, width=32, step=96, data=bytes(2304)))
    assert provider._latest[1].received_at_ns == 99_510_000_000
