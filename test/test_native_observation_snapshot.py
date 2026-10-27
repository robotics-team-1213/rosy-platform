"""Native observation IPC keeps source clocks and never needs ROS middleware."""
import json
import importlib.util
from pathlib import Path
import sys
import time

import pytest

from core_common.observation_snapshot import SnapshotChannel


def test_latest_atomic_snapshot_is_shared_without_refreshing_capture(tmp_path):
    producer = SnapshotChannel('/camera/image_raw', root=tmp_path)
    consumer = SnapshotChannel('/camera/image_raw', root=tmp_path)
    producer.write('jpeg', b'first', captured_at=time.time(), quality={'sharp': True})
    first = consumer.read()
    assert first['payload'] == b'first' and first['quality'] == {'sharp': True}
    assert consumer.read()['monotonic'] == first['monotonic']
    producer.write('jpeg', b'second', captured_at=time.time())
    assert consumer.read()['payload'] == b'second'
    assert len(list(tmp_path.iterdir())) == 1
    assert SnapshotChannel('/other/image_raw', root=tmp_path).read() is None


@pytest.mark.parametrize('wall_delta,mono_delta', [(3, 0), (-1, 0), (0, 3), (0, -1)])
def test_stale_future_and_clock_reset_are_not_fresh(tmp_path, wall_delta, mono_delta):
    channel = SnapshotChannel('camera', root=tmp_path)
    channel.write('jpeg', b'jpeg', captured_at=time.time())
    sample = channel.read()
    assert channel.read(wall=sample['captured_at'] + wall_delta,
                        monotonic=sample['monotonic'] + mono_delta) is None


def test_corrupt_and_oversized_files_fail_closed(tmp_path):
    channel = SnapshotChannel('camera', root=tmp_path)
    channel.write('jpeg', b'jpeg', captured_at=time.time())
    channel.path.write_bytes(b'not a snapshot')
    assert channel.read() is None
    with pytest.raises(ValueError):
        channel.write('jpeg', b'x' * (2 * 1024 * 1024), captured_at=time.time())


def test_joint_payload_is_json_and_cannot_overwrite_camera(tmp_path):
    channel = SnapshotChannel('/omx_commissioning/arm_a/joint_states', root=tmp_path)
    positions = {'joint1': 1.25}
    channel.write('joints', json.dumps(positions).encode(), captured_at=time.time())
    assert json.loads(channel.read()['payload']) == positions


def test_failed_write_preserves_previous_complete_snapshot(tmp_path, monkeypatch):
    import core_common.observation_snapshot as module
    channel = SnapshotChannel('camera', root=tmp_path)
    channel.write('jpeg', b'first', captured_at=time.time())
    def fail(*args):
        raise OSError('disk failed')
    monkeypatch.setattr(module.os, 'replace', fail)
    with pytest.raises(OSError):
        channel.write('jpeg', b'next', captured_at=time.time())
    assert channel.read()['payload'] == b'first'
    assert len(list(tmp_path.iterdir())) == 1


def test_native_view_reads_selected_camera_and_three_arms_without_ros(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'deploy/robot/omx/commissioning_view.py'
    spec = importlib.util.spec_from_file_location('native_test_view', path)
    view = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(view)
    monkeypatch.setenv('ROSY_OBSERVATION_DIR', str(tmp_path))
    for name in ('rclpy', 'sensor_msgs', 'cv_bridge'):
        monkeypatch.setitem(sys.modules, name, None)
    arms = {f'arm_{i}': f'/omx_commissioning/arm_{i}/joint_states' for i in range(3)}
    store = view.ObservationStore(arms=arms, cameras={'wrist': '/wrist/image_raw'})
    stamp = time.time()
    SnapshotChannel('/wrist/image_raw').write('jpeg', b'jpeg', captured_at=stamp, quality={'ok': True})
    for key in arms.values():
        SnapshotChannel(key).write('joints', json.dumps(dict.fromkeys(
            ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'gripper_joint_1'], .25)).encode(),
            captured_at=stamp)
    SnapshotChannel('/unselected/image_raw').write('jpeg', b'ignored', captured_at=stamp)
    view.consume_native(store)
    first = store.snapshot()
    view.consume_native(store)
    second = store.snapshot()
    assert store.image('wrist') == b'jpeg'
    assert set(second['cameras']) == {'wrist'}
    assert all(item['fresh'] and len(item['values']) == 6 for item in second['arms'].values())
    assert second['cameras']['wrist']['sequence'] == first['cameras']['wrist']['sequence'] == 1
    assert second['cameras']['wrist']['receipt_age_s'] >= first['cameras']['wrist']['receipt_age_s']
    assert store.image('wrist', wall=stamp + 3) is None


def test_operational_entry_points_cannot_import_ros_even_lazily():
    import ast
    root = Path(__file__).resolve().parents[1]
    for relative in ('deploy/robot/omx/commissioning_view.py', 'deploy/robot/omx/hardware_observer.py',
                     'deploy/robot/omx/workcell_observation_bridge.py',
                     'middleware/devices/omx/adapter/omx_adapter/camera_source.py'):
        tree = ast.parse((root / relative).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom): names = [node.module or '']
            else: continue
            assert not any(name.split('.')[0] in {'rclpy', 'rclcpp', 'sensor_msgs', 'cv_bridge'}
                           for name in names), relative
