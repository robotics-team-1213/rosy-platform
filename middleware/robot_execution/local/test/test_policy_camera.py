"""Exercise the Gazebo provider body without importing ROS on a pytest host."""
import ast
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'middleware/devices/omx/adapter'),
               str(ROOT/'middleware/robot_execution/local/src')]
from rosy.execution.local.omx_policy import CameraSnapshot


def provider():
    tree = ast.parse(Path(__file__).with_name('policy_chain_gazebo.py').read_text())
    camera = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Camera')
    scope = dict(threading=threading, hashlib=hashlib, CameraSnapshot=CameraSnapshot, contextmanager=contextmanager,
                 Image=object, qos_profile_sensor_data=object(), SHAPE=(3, 24, 32),
                 TIMING={'max_observation_age_ns': 500_000_000})
    exec(compile(ast.Module(body=[camera], type_ignores=[]), '<actual Camera provider>', 'exec'), scope)
    node = NS(create_subscription=lambda *args: None,
              get_clock=lambda: NS(now=lambda: NS(nanoseconds=20_000_000_000)))
    return scope['Camera'](node, lambda: 100.0, 'a'*64)


def test_camera_preserves_source_age():
    camera = provider()
    camera.receive(NS(header=NS(stamp=NS(sec=19, nanosec=510_000_000)),
                        encoding='rgb8', height=24, width=32, step=96, data=bytes(2304)))
    assert camera._latest[1].received_at_ns == 99_510_000_000


def test_capture_pins_original_without_blocking_watchdog_current():
    camera = provider()
    def frame(stamp, value):
        return NS(header=NS(stamp=NS(sec=19,nanosec=stamp)),encoding='rgb8',
                  height=24,width=32,step=96,data=bytes([value])*2304)
    camera.receive(frame(900_000_000,0))
    attempted, updated = threading.Event(), threading.Event()
    readings, workers = [], []
    def update():
        attempted.set()
        camera.receive(frame(990_000_000,1))
        updated.set()
    try:
        with camera.capture() as (raw, original):
            writer = threading.Thread(target=update)
            workers.append(writer)
            writer.start()
            assert attempted.wait(1) and not updated.wait(.05)
            reader = threading.Thread(target=lambda:readings.append(camera.current()))
            workers.append(reader)
            reader.start()
            reader.join(.5)
            assert not reader.is_alive(), 'watchdog must not wait for capture lock'
            assert readings == [(original,)]
            assert original.received_at_ns == 99_900_000_000
            assert hashlib.sha256(raw).hexdigest() == original.frame_sha256
    finally:
        for worker in workers: worker.join(2)
    assert updated.is_set() and not any(worker.is_alive() for worker in workers)
    assert camera.current()[0] != original
