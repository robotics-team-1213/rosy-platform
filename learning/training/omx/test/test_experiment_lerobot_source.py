"""Uploaded datasets keep closed paths, generic dimensions, and confirmed splits."""
import copy
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import experiment_lerobot_source as source
import experiment_lerobot_worker as worker
import experiment_robot_adapters as robots


def test_video_headers_are_checked_without_decoding(tmp_path,monkeypatch):
    class Container:
        streams=SimpleNamespace(video=[SimpleNamespace(codec_context=SimpleNamespace(width=64,height=32))])
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def decode(self,*args): raise AssertionError('header validation must precede decoding')
    monkeypatch.setitem(sys.modules,'av',SimpleNamespace(open=lambda path:Container()))
    source.check_video_header(tmp_path/'local.mp4',dict(shape=[32,64,3]))
    with pytest.raises(ValueError,match='dimensions'):
        source.check_video_header(tmp_path/'local.mp4',dict(shape=[16,16,3]))


def manifest():
    return [dict(name='meta/info.json', size=2, sha256=hashlib.sha256(b'{}').hexdigest())]


@pytest.mark.parametrize('name', ['../info.json', '/meta/info.json', 'meta/../info.json',
    'meta\\info.json', 'meta//info.json', '.cache/token', 'code.py',
    'videos/other/chunk-000/file-000.mp4', 'meta/.hidden.json'])
def test_manifest_rejects_unsafe_and_unsupported_names(name):
    with pytest.raises(ValueError):
        source.validate_files([dict(manifest()[0], name=name)])


def test_manifest_is_canonical_and_case_collisions_are_rejected():
    files = manifest() + [dict(name='README.md', size=0, sha256='0'*64)]
    assert source.manifest_revision(files) == source.manifest_revision(list(reversed(files)))
    assert source.validate_files(files)[0]['name'] == 'README.md'
    with pytest.raises(ValueError):
        source.validate_files(files + [dict(files[1])])


def test_profile_camera_keys_are_preserved_in_uploaded_video_paths():
    for key in ('arm_a.wrist', 'arm-b-wrist', 'TopCamera_2'):
        name = f'videos/observation.images.{key}/chunk-000/file-000.mp4'
        assert source.allowed(name) == name


def test_disjoint_noncontiguous_split_with_empty_validation():
    inspection = dict(revision='1'*64, episodes=[dict(index=i) for i in [0, 2, 7, 9]])
    chosen = dict(train=[0, 7], validation=[], eval=[9])
    checked = source.validate_split(chosen, inspection)
    assert {key: checked[key] for key in chosen} == chosen
    for bad in [dict(chosen, train=[7, 0]), dict(chosen, eval=[7]),
                dict(chosen, eval=[]), dict(chosen, train=[True]), dict(chosen, eval=[1])]:
        with pytest.raises(ValueError):
            source.validate_split(bad, inspection)


def adapter_info(robot, size, names=None):
    vector = dict(dtype='float32', shape=[size], names=names)
    return dict(codebase_version='v3.0', fps=30, robot_type=robot, total_episodes=4, total_frames=20,
        data_path=source.DATA_PATH, features={'observation.state': vector, 'action': vector,
            'observation.images.top': dict(dtype='image', shape=[32,48,3])})


def test_only_omx_ai_has_an_adapter():
    joints = [f'{joint}.pos' for joint in ('shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper')]
    robots.check(adapter_info('omx_follower', 6, joints))
    robots.check(adapter_info('omx_follower', 6))
    robots.check(adapter_info('bi_omx_follower', 12, [f'arm_{arm}.{name}' for arm in 'ab' for name in joints]))
    for bad in (adapter_info('so100', 6), adapter_info(None, 6), adapter_info('omx_follower', 7),
                adapter_info('bi_omx_follower', 6), adapter_info('omx_follower', 6, ['a','b','c','d','e','f'])):
        with pytest.raises(ValueError):
            robots.check(bad)


def test_a_new_study_needs_an_adapter_but_an_earlier_result_stays_verifiable(monkeypatch, tmp_path):
    other = adapter_info('so100', 6)
    assert source.check_info(other) == other
    monkeypatch.setattr(source, 'verify_files', lambda *_: None)
    monkeypatch.setattr(source, 'read_json', lambda *_, **__: other)
    with pytest.raises(ValueError, match='no adapter'):
        source.inspect(tmp_path, [])


def test_metadata_is_bounded():
    info = dict(codebase_version='v3.0', fps=20, robot_type='omx_follower', total_episodes=4,
        total_frames=20, data_path='data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet',
        features={'observation.state': dict(dtype='float32', shape=[6], names=None),
                  'action': dict(dtype='float32', shape=[6], names=None),
                  'observation.images.front': dict(dtype='image', shape=[32,48,3])})
    assert source.check_info(info) == info
    for key, value in [('fps', True), ('data_path', '../{file_index}.parquet'),
                       ('codebase_version', 'v2.1'), ('total_episodes', 1001)]:
        with pytest.raises(ValueError):
            source.check_info(dict(info, **{key: value}))
    changed = copy.deepcopy(info)
    changed['features']['action']['shape'] = [65]
    with pytest.raises(ValueError):
        source.check_info(changed)


def test_worker_environment_never_inherits_tokens_or_pythonpath(tmp_path, monkeypatch):
    monkeypatch.setenv('HF_TOKEN', 'do-not-pass')
    monkeypatch.setenv('PYTHONPATH', 'untrusted')
    monkeypatch.setenv('HTTPS_PROXY', 'untrusted')
    env = worker.offline_environment(tmp_path)
    assert not {'HF_TOKEN','PYTHONPATH','HTTPS_PROXY'} & env.keys()
    assert env['HF_HUB_OFFLINE'] == env['HF_DATASETS_OFFLINE'] == '1'
    assert env['HF_HUB_DISABLE_IMPLICIT_TOKEN'] == '1'
    assert env['HF_HOME'] == str(tmp_path/'cache'/'huggingface')


def test_raw_embedded_images_refuse_external_paths_before_decode():
    feature = dict(dtype='image', shape=[32, 48, 3])
    for cell in [dict(path='/etc/passwd', bytes=None), dict(path='outside.png', bytes=b'x'),
                 dict(path=None, bytes=b'')]:
        with pytest.raises(ValueError):
            source.check_image_cell(cell, feature)


def test_closed_inspect_request_and_result_binding(tmp_path):
    request = dict(schema='rosy.lerobot-inspect-request/1', study_id='a', project_id='p',
        source_root=str(tmp_path/'source'), files=manifest(),
        manifest_revision=source.manifest_revision(manifest()))
    with pytest.raises(ValueError):
        worker.check_request(dict(request, command='anything'))
    with pytest.raises(ValueError):
        worker.check_result(tmp_path, dict(schema='rosy.lerobot-inspect-result/1'), request)
