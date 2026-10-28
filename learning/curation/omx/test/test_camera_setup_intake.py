"""D-792 S3: real OMX episodes get shadow camera setup checks at intake, from their own first and last frames."""
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'learning/curation/omx'), str(ROOT / 'learning/curation/perception'),
                str(ROOT / 'test/learning/perception')]
import camera_setup  # noqa: E402
import camera_setup_intake  # noqa: E402
import collection_intake  # noqa: E402
import camera_reference  # noqa: E402
from test_camera_setup import COMMON, K, WRIST_POSE, rotate, scene  # noqa: E402


def session(role, frames, joints=None):
    blobs, rows = {}, []
    for i, frame in enumerate(frames):
        path = f'episodes/000000/{role}-{i:06d}.rgb'
        blobs[path] = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).tobytes()
        row = dict(images={role: dict(path=path)})
        if joints is not None:
            row['joint_positions_rad'] = joints
        rows.append(row)
    model = {role: dict(width=640, height=480, k=[600., 0, 320, 0, 600, 240, 0, 0, 1])}
    blobs['camera_info.jsonl'] = json.dumps(dict(time_ns=1, cameras=model)).encode() + b'\n'
    blobs['profile.json'] = json.dumps(dict(joint_names=WRIST_POSE['joint_names'])).encode()
    return dict(samples=[rows], manifest=dict(session_id='s1', camera_shapes={role: [480, 640, 3]}), blobs=blobs)


def stored_reference(tmp_path, role, fingerprint, check_pose=None):
    still = cv2.imencode('.jpg', scene(), [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()
    doc = camera_setup.make_reference(
        cv2.imdecode(np.frombuffer(still, np.uint8), cv2.IMREAD_COLOR), measured={},
        check_pose=check_pose, **{**COMMON, 'camera_role': role, 'reference_still': hashlib.sha256(still).hexdigest(),
                                  'intrinsics': {**K, 'camera_info_sha256': fingerprint}})
    path = tmp_path / f"{doc['revision']}.json"
    path.write_text(json.dumps(doc), encoding='utf-8')
    path.with_suffix('.jpg').write_bytes(still)
    return path


def test_fixed_camera_is_checked_before_and_after_each_episode(tmp_path):
    record = session('top', [scene(), rotate(scene(), pan=1.5)])
    fingerprint = camera_setup_intake.camera_info_fingerprints(record['blobs'])['top']
    reference = camera_setup_intake.load_reference(stored_reference(tmp_path, 'top', fingerprint))
    report = camera_setup_intake.report([record], [(record, dict(episode_index=0))], {'top': reference})
    assert report['mode'] == 'shadow' and report['camera_info_sha256'] == {'top': fingerprint}
    check = report['episodes'][0]['checks']['top']
    assert check['reference_revision'] == reference[0]['revision']
    assert check['before']['verdict'] == 'ok'
    assert check['after']['verdict'] == 'adjust' and check['after']['d_pan_deg'] == pytest.approx(1.5, abs=0.2)


def test_wrist_camera_without_recorded_joints_is_unmeasurable_not_ok(tmp_path):
    record = session('front', [scene(), scene()])
    fingerprint = camera_setup_intake.camera_info_fingerprints(record['blobs'])['front']
    reference = camera_setup_intake.load_reference(stored_reference(tmp_path, 'front', fingerprint, WRIST_POSE))
    old = camera_setup_intake.report([record], [(record, dict(episode_index=0))], {'front': reference})
    check = old['episodes'][0]['checks']['front']
    assert check['before']['verdict'] == check['after']['verdict'] == 'unmeasurable'
    record = session('front', [scene(), scene()], joints=WRIST_POSE['positions_rad'])
    new = camera_setup_intake.report([record], [(record, dict(episode_index=0))], {'front': reference})
    assert new['episodes'][0]['checks']['front']['before']['verdict'] == 'ok'


def test_a_tampered_still_or_unknown_role_is_refused(tmp_path):
    record = session('top', [scene(), scene()])
    path = stored_reference(tmp_path, 'top', 'c' * 64)
    reference = camera_setup_intake.load_reference(path)
    with pytest.raises(ValueError, match='not a recorded camera'):
        camera_setup_intake.report([record], [(record, dict(episode_index=0))], {'front': reference})
    path.with_suffix('.jpg').write_bytes(b'\xff\xd8 not the still')
    with pytest.raises(ValueError, match='does not match'):
        camera_setup_intake.load_reference(path)


def test_reference_options_are_one_path_per_role():
    assert camera_reference.parse(['top=/a.json', 'front=/b.json']) == {
        'top': Path('/a.json'), 'front': Path('/b.json')}
    for bad in (['top'], ['top=/a', 'top=/b'], ['=/a']):
        with pytest.raises(ValueError):
            camera_reference.parse(bad)


@pytest.mark.parametrize('role', ['front', 'wrist'])
def test_fixed_reference_cannot_measure_a_wrist_stream(tmp_path, role):
    record = session(role, [scene(), scene()])
    fingerprint = camera_setup_intake.camera_info_fingerprints(record['blobs'])[role]
    reference = camera_setup_intake.load_reference(stored_reference(tmp_path, 'top', fingerprint))
    with pytest.raises(ValueError, match='camera role'):
        camera_setup_intake.report([record], [(record, dict(episode_index=0))], {role: reference})


@pytest.mark.parametrize('role', ['front', 'wrist'])
def test_wrist_reference_requires_its_confirmation_pose(tmp_path, role):
    record = session(role, [scene(), scene()])
    fingerprint = camera_setup_intake.camera_info_fingerprints(record['blobs'])[role]
    reference = camera_setup_intake.load_reference(stored_reference(tmp_path, role, fingerprint))
    with pytest.raises(ValueError, match='check pose'):
        camera_setup_intake.report([record], [(record, dict(episode_index=0))], {role: reference})


def test_reference_role_accepts_the_wrist_alias(tmp_path):
    record = session('front', [scene(), scene()], joints=WRIST_POSE['positions_rad'])
    fingerprint = camera_setup_intake.camera_info_fingerprints(record['blobs'])['front']
    reference = camera_setup_intake.load_reference(stored_reference(tmp_path, 'wrist', fingerprint, WRIST_POSE))
    report = camera_setup_intake.report([record], [(record, dict(episode_index=0))], {'front': reference})
    assert report['episodes'][0]['checks']['front']['before']['verdict'] == 'ok'


def test_changed_calibration_is_not_measured_using_the_first_camera_model(tmp_path):
    record = session('top', [scene(), scene()])
    fingerprint = camera_setup_intake.camera_info_fingerprints(record['blobs'])['top']
    reference = camera_setup_intake.load_reference(stored_reference(tmp_path, 'top', fingerprint))
    later = json.loads(record['blobs']['camera_info.jsonl'])
    later['time_ns'] = 2
    later['cameras']['top']['k'][0] = 650.
    record['blobs']['camera_info.jsonl'] += json.dumps(later).encode() + b'\n'
    for i, row in enumerate(record['samples'][0]):
        row['time_ns'] = 3 + i
    report = camera_setup_intake.report([record], [(record, dict(episode_index=0))], {'top': reference})
    check = report['episodes'][0]['checks']['top']
    assert check['before']['verdict'] == check['after']['verdict'] == 'unmeasurable'
    assert 'top' not in report['camera_info_sha256']


def test_calibration_changes_do_not_invalidate_an_unchanged_other_camera():
    first = dict(time_ns=1, cameras={'top': {'k': [600.]}, 'front': {'k': [700.]}})
    later = dict(time_ns=2, cameras={'top': {'k': [600.]}, 'front': {'k': [710.]}})
    blobs = {'camera_info.jsonl': b'\n'.join(json.dumps(row).encode() for row in [first, later]) + b'\n'}
    assert camera_setup_intake.camera_info_fingerprints(blobs) == {
        'top': hashlib.sha256(json.dumps(first['cameras']['top'], sort_keys=True).encode()).hexdigest()}
