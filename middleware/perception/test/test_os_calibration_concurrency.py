from concurrent.futures import ThreadPoolExecutor
from threading import Event
from pathlib import Path
import subprocess
import sys

import pytest

from control import calibration_storage as storage
from control.calibration_record import decode_record

PKG_ROOT = Path(__file__).resolve().parents[1]

CONTEXT = dict(robot_id='rosy_01', hardware_model='Pinky Pro', geometry_revision='g1',
               sensor_revision='s1', data_generation='release-1')


def test_second_writer_is_rejected_and_can_retry_after_commit(tmp_path, monkeypatch):
    path = str(tmp_path / 'calibration.yaml')
    update = 'safety_node: {ros__parameters: {imu_roll0: 1.0}}'
    storage.merge_calibration(path, update, context=CONTEXT, actor='first')
    entered, release = Event(), Event()
    encode = storage.encode_record

    def paused(*args, **kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(5), 'test writer was not released'
        return encode(*args, **kwargs)

    monkeypatch.setattr(storage, 'encode_record', paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(storage.merge_calibration, path, update, context=CONTEXT, actor='first')
        try:
            assert entered.wait(5)
            with pytest.raises(ValueError, match='busy'):
                storage.merge_calibration(path, update, context=CONTEXT, actor='second')
        finally:
            release.set()
        first.result(timeout=5)
    storage.merge_calibration(path, 'safety_node: {ros__parameters: {imu_pitch0: 2.0}}',
                              context=CONTEXT, actor='second')
    metadata, values = decode_record((tmp_path / 'calibration.yaml').read_text(), CONTEXT)
    assert metadata['revision'] == 3
    assert values['/**/safety_node']['ros__parameters'] == {'imu_roll0': 1., 'imu_pitch0': 2.}


def test_stale_revision_cannot_overwrite_new_measurement(tmp_path):
    path = tmp_path / 'calibration.yaml'
    update = 'safety_node: {ros__parameters: {imu_roll0: 1.0}}'
    storage.merge_calibration(str(path), update, context=CONTEXT, actor='first', expected_revision=0)
    original = path.read_bytes()
    with pytest.raises(ValueError, match='revision'):
        storage.merge_calibration(str(path), update, context=CONTEXT, actor='second', expected_revision=0)
    assert path.read_bytes() == original


def test_process_exit_releases_lock_without_removing_lock_file(tmp_path):
    path = tmp_path / 'calibration.yaml'
    script = ('from control.calibration_lock import calibration_lock\n'
              'import sys\n'
              'with calibration_lock(sys.argv[1]):\n'
              ' print("locked", flush=True)\n'
              ' sys.stdin.read()\n')
    process = subprocess.Popen([sys.executable, '-c', script, str(path)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, cwd=PKG_ROOT)
    try:
        assert process.stdout.readline().strip() == 'locked'
        with pytest.raises(ValueError, match='busy'):
            storage.merge_calibration(str(path), 'safety_node: {ros__parameters: {imu_roll0: 1.0}}')
    finally:
        process.terminate()
        process.communicate(timeout=5)
    storage.merge_calibration(str(path), 'safety_node: {ros__parameters: {imu_roll0: 1.0}}')
    assert path.is_file()
    assert path.with_name(path.name + '.lock').is_file()


def test_create_only_commit_rechecks_destination_under_lock(tmp_path):
    path = tmp_path / 'calibration.yaml'
    update = 'safety_node: {ros__parameters: {imu_roll0: 1.0}}'
    storage.merge_calibration(str(path), update, create_only=True)
    original = path.read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        storage.merge_calibration(str(path), update, create_only=True)
    assert path.read_bytes() == original
